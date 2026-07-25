"""Parquet -> Postgres loader: the store-migration publish seam.

Reads the exact parquet the frontend serves today
(``application/frontend/public/data/*.parquet``) and loads it into Supabase Postgres,
so the database is a byte-faithful copy of what's on screen. This permanently replaces
the hand-symlink "publish" step.

Two modes (run from the repo root with the data venv, application/venv):

    application/venv/bin/python -m application.data.serve.build_db --emit
        Inspect the 13 parquet schemas and (re)generate the reviewable artifacts:
        schema.sql (DDL) and MANIFEST.md.

    application/venv/bin/python -m application.data.serve.build_db --load
        Apply schema.sql (DROP + CREATE, so re-runs never duplicate) and COPY every
        dataset in. Idempotent.

    (--emit --load runs both.)

Scope: the single is_mine 2025 league (config.SLEEPER_LEAGUE_ID). ``league_id`` is
stamped on every table and ``season`` is ensured on every table (the file's real year
where the parquet lacks its own season column) so the multi-league phase needs no
reshape. Read-only on all parquet — never recompute or modify derived data.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl
import psycopg
from psycopg.types.json import Jsonb

from application.api.db import database_url
from application.config import SLEEPER_LEAGUE_ID

LEAGUE_ID = str(SLEEPER_LEAGUE_ID)

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]  # serve -> data -> application -> <repo root is application's parent>
_PUBLIC_DATA = _REPO_ROOT / "application" / "frontend" / "public" / "data"
_SCHEMA_SQL = _HERE / "schema.sql"
_MANIFEST = _HERE / "MANIFEST.md"

# table name -> (published parquet filename, real source season year).
# Authoritative list = these 13 datasets (historically the registerParquet set in
# frontend/src/db.js, removed in the Session-5 API-client swap; now this list + MANIFEST.md
# are the source of truth). (A 14th file, manager_features_2025.parquet, exists but is a
# backend AI-pipeline intermediate — NOT served, so excluded here.)
DATASETS: list[tuple[str, str, int]] = [
    ("season", "season_2025.parquet", 2025),
    ("teams", "teams_2025.parquet", 2025),
    ("lineup_slots", "lineup_slots_2025.parquet", 2025),
    ("league_settings", "league_settings_2025.parquet", 2025),
    ("player_signal", "player_signal_2025.parquet", 2025),
    ("production_vor", "production_vor_2025.parquet", 2025),
    ("market_vor", "market_vor_2025.parquet", 2025),
    ("ros_synthesis", "ros_synthesis_2026.parquet", 2026),  # 2026 news world — carry its real year
    ("bracket_odds", "bracket_odds_2025.parquet", 2025),
    ("positional_depth", "positional_depth_2025.parquet", 2025),
    ("manager_dossiers", "manager_dossiers_2025.parquet", 2025),
    ("projection_consensus", "projection_consensus_2025.parquet", 2025),
    ("schedule", "schedule_2025.parquet", 2025),
]

# Per-table columns to index — the ones the frontend actually filters/joins on
# (from queries.js), plus (league_id, season) added to every table below.
INDEXES: dict[str, list[tuple[str, ...]]] = {
    "season": [("week",), ("roster_id",), ("sleeper_player_id",), ("position",)],
    "teams": [("roster_id",)],
    "lineup_slots": [],
    "league_settings": [("section", "key")],
    "player_signal": [("sleeper_player_id",), ("as_of_week",)],
    "production_vor": [("as_of_week",), ("sleeper_player_id",), ("roster_id",)],
    "market_vor": [("snapshot_date",), ("sleeper_player_id",), ("roster_id",), ("position",)],
    "ros_synthesis": [("sleeper_player_id",), ("week",)],
    "bracket_odds": [("as_of_week",), ("roster_id",)],
    "positional_depth": [("as_of_week",), ("roster_id",), ("position",)],
    "manager_dossiers": [("roster_id",)],
    "projection_consensus": [("week",), ("sleeper_player_id",)],
    "schedule": [("week",), ("matchup_id",), ("roster_id",)],
}


def pg_type(dt: pl.DataType) -> str:
    """Map a polars dtype to a Postgres column type."""
    bt = dt.base_type()
    if bt in (pl.List, pl.Array, pl.Struct):
        return "JSONB"
    if bt == pl.Datetime:
        return "TIMESTAMP"
    if bt == pl.Date:
        return "DATE"
    if bt == pl.Boolean:
        return "BOOLEAN"
    if bt in (pl.Int8, pl.Int16, pl.Int32, pl.UInt8, pl.UInt16):
        return "INTEGER"
    if bt in (pl.Int64, pl.UInt32, pl.UInt64):
        return "BIGINT"
    if bt in (pl.Float32, pl.Float64):
        return "DOUBLE PRECISION"
    if bt == pl.Null:
        # All-null column (e.g. projection_consensus.disagreement_ppr): parquet carries
        # no usable type. Pick a numeric default so the column exists and stays NULL.
        return "DOUBLE PRECISION"
    return "TEXT"  # String/Categorical and anything else (incl. JSON-encoded-as-string)


def _plan(table: str, schema: dict[str, pl.DataType]):
    """Return (ddl_columns, add_season, jsonb_cols) for a table.

    ddl_columns: ordered [(name, pgtype)] = league_id, [season], *parquet columns.
    add_season:  True when the parquet lacks its own season column (we add a constant).
    jsonb_cols:  parquet column names that map to JSONB (nested list/struct).
    """
    add_season = "season" not in schema
    cols: list[tuple[str, str]] = [("league_id", "TEXT")]
    if add_season:
        cols.append(("season", "BIGINT"))
    jsonb_cols: set[str] = set()
    for name, dt in schema.items():
        t = pg_type(dt)
        if t == "JSONB":
            jsonb_cols.add(name)
        cols.append((name, t))
    return cols, add_season, jsonb_cols


def _schema_dict(fname: str) -> dict[str, pl.DataType]:
    return pl.read_parquet_schema(_PUBLIC_DATA / fname)


def emit() -> None:
    """Regenerate schema.sql and MANIFEST.md from the parquet schemas."""
    ddl_parts: list[str] = [
        "-- GENERATED by application/data/serve/build_db.py --emit. Do not hand-edit.",
        "-- Re-run --emit to regenerate. One table per published parquet dataset. Every",
        "-- table carries league_id and season for the multi-league phase.\n",
    ]
    man_rows: list[str] = []
    for table, fname, year in DATASETS:
        schema = _schema_dict(fname)
        n = pl.read_parquet(_PUBLIC_DATA / fname).height
        cols, _add_season, jsonb_cols = _plan(table, schema)

        col_defs = ",\n".join(f"    {name} {typ}" for name, typ in cols)
        stmts = [
            f'DROP TABLE IF EXISTS "{table}" CASCADE;',
            f'CREATE TABLE "{table}" (\n{col_defs}\n);',
        ]
        for cols_tuple in [*INDEXES.get(table, []), ("league_id", "season")]:
            idx = "_".join(cols_tuple)
            collist = ", ".join(cols_tuple)
            stmts.append(
                f'CREATE INDEX IF NOT EXISTS "ix_{table}_{idx}" ON "{table}" ({collist});'
            )
        ddl_parts.append("\n".join(stmts) + "\n")

        # manifest row
        coltypes = ", ".join(f"{name}:{pg_type(dt)}" for name, dt in schema.items())
        note = " *(JSONB: " + ", ".join(sorted(jsonb_cols)) + ")*" if jsonb_cols else ""
        man_rows.append(
            f"| `{table}` | `{fname}` | {year} | {n} | {len(schema)} | {coltypes}{note} |"
        )

    _SCHEMA_SQL.write_text("\n".join(ddl_parts))

    manifest = [
        "# Loader manifest — published parquet -> Postgres",
        "",
        "Generated by `build_db.py --emit`. One row per registered frontend dataset "
        "(`frontend/src/db.js`). `league_id` is added to every table; `season` is added "
        "where the parquet lacks its own. Nested columns become JSONB.",
        "",
        f"Source dir: `application/frontend/public/data/` · league_id `{LEAGUE_ID}`.",
        "",
        "| Table | Source parquet | Season | Rows | Cols | Columns (parquet -> pg type) |",
        "|---|---|---|---|---|---|",
        *man_rows,
    ]
    _MANIFEST.write_text("\n".join(manifest) + "\n")
    print(f"emitted {_SCHEMA_SQL.relative_to(_REPO_ROOT)} and {_MANIFEST.relative_to(_REPO_ROOT)}")


def _run_sql_script(cur, sql: str) -> None:
    """Execute a multi-statement DDL script (psycopg executes one command per call).

    Strips full-line ``--`` comments first so a semicolon inside a comment can't be
    mistaken for a statement terminator; the remaining DDL has ';' only as terminators.
    """
    body = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    for stmt in (s.strip() for s in body.split(";")):
        if stmt:
            cur.execute(stmt)


def load() -> None:
    """Apply schema.sql then COPY every dataset in. Idempotent (schema DROPs+CREATEs)."""
    if not _SCHEMA_SQL.exists():
        raise SystemExit("schema.sql missing — run --emit first.")
    schema_sql = _SCHEMA_SQL.read_text()

    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            _run_sql_script(cur, schema_sql)
        conn.commit()

        for table, fname, year in DATASETS:
            df = pl.read_parquet(_PUBLIC_DATA / fname)
            cols, add_season, jsonb_cols = _plan(table, df.schema)
            col_names = [name for name, _ in cols]
            parquet_cols = df.columns

            copy_sql = f'COPY "{table}" ({", ".join(col_names)}) FROM STDIN'
            with conn.cursor() as cur:
                with cur.copy(copy_sql) as cp:
                    for row in df.iter_rows(named=True):
                        values: list = [LEAGUE_ID]
                        if add_season:
                            values.append(year)
                        for pcol in parquet_cols:
                            v = row[pcol]
                            if pcol in jsonb_cols:
                                v = Jsonb(v) if v is not None else None
                            values.append(v)
                        cp.write_row(values)
            conn.commit()
            print(f"loaded {table:22s} {df.height:>6d} rows  <- {fname}")


def verify() -> None:
    """Assert every table's row count matches its source parquet, then sample-query."""
    ok = True
    print(f"{'table':22s} {'parquet':>8s} {'postgres':>9s}  season(s)   result")
    with psycopg.connect(database_url()) as conn:
        for table, fname, year in DATASETS:
            parquet_n = pl.read_parquet(_PUBLIC_DATA / fname).height
            with conn.cursor() as cur:
                cur.execute(f'SELECT count(*) FROM "{table}"')
                db_n = cur.fetchone()[0]
                cur.execute(
                    f'SELECT min(season), max(season), count(DISTINCT league_id) FROM "{table}"'
                )
                smin, smax, n_leagues = cur.fetchone()
            seasons = str(smin) if smin == smax else f"{smin}-{smax}"
            match = "OK" if db_n == parquet_n else "*** MISMATCH ***"
            ok = ok and db_n == parquet_n and n_leagues == 1
            print(f"{table:22s} {parquet_n:>8d} {db_n:>9d}  {seasons:>9s}   {match}")

        print("\n-- sample queries --")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sleeper_player_id, roster_id, round(vor::numeric, 2) "
                "FROM production_vor WHERE as_of_week = 4 ORDER BY vor DESC LIMIT 3"
            )
            print("production_vor @ as_of_week=4 (top 3 by vor):")
            for r in cur.fetchall():
                print("   ", r)
            cur.execute(
                "SELECT matchup_id, array_agg(roster_id ORDER BY roster_id) "
                "FROM schedule WHERE week = 1 GROUP BY matchup_id ORDER BY matchup_id"
            )
            print("schedule @ week=1 (matchup -> rosters):")
            for r in cur.fetchall():
                print("   ", r)
            cur.execute(
                "SELECT sleeper_player_id, jsonb_array_length(headlines) "
                "FROM ros_synthesis WHERE headlines IS NOT NULL "
                "AND jsonb_array_length(headlines) > 0 LIMIT 2"
            )
            print("ros_synthesis headlines (JSONB array lengths):")
            for r in cur.fetchall():
                print("   ", r)
    if not ok:
        raise SystemExit("VERIFY FAILED — row-count mismatch or league_id not singular")
    print("\nVERIFY OK — all row counts match; single league_id per table.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Parquet -> Postgres loader (store migration).")
    ap.add_argument("--emit", action="store_true", help="regenerate schema.sql + MANIFEST.md")
    ap.add_argument("--load", action="store_true", help="apply schema.sql and load data")
    ap.add_argument("--verify", action="store_true", help="assert row counts + sample queries")
    args = ap.parse_args()
    if not (args.emit or args.load or args.verify):
        ap.error("nothing to do — pass --emit, --load and/or --verify")
    if args.emit:
        emit()
    if args.load:
        load()
    if args.verify:
        verify()


if __name__ == "__main__":
    main()
