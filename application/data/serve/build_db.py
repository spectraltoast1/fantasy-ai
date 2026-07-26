"""Derived-store -> Postgres loader: the multi-league publish seam (Stage-B B3).

Loads ALL demo slices (`data_layer.read_demo_manifest()` — 31 (league_id, season) rows across
12 lineages) from the **derived store** into Supabase Postgres, keyed by league_id + season.
Every read is routed through ``data_layer`` (the I/O-through-data_layer rule) — the readers know
each dataset's tree (some derived reads live under ``derived/league/<id>/``, the base reads under
the raw/join tree), so there are no hand-built paths.

Per (slice, dataset) the load is **skip-if-absent**: not every slice has every panel. Base
analytics exist for all 31; ``manager_dossiers`` for the ~11 computed slices; ``market_vor`` for
the one is_mine slice; ``ros_synthesis`` for **zero** — its only file is the 2026 news world and
no slice is season 2026, so the year-matched per-slice read never finds it (the ROS panel is empty
by design; a future year-matched news read just loads in). A missing dataset loads zero rows for
that slice — never crash, never fabricate.

Three modes (run from the repo root with the data venv, application/venv):

    application/venv/bin/python -m application.data.serve.build_db --emit
        Regenerate schema.sql (DDL) + MANIFEST.md from the derived-store schemas.

    application/venv/bin/python -m application.data.serve.build_db --dry-run
        Offline: print the per-(slice, dataset) load/skip matrix + expected row counts,
        WITHOUT connecting to Postgres. Inspect the plan before any production write.

    application/venv/bin/python -m application.data.serve.build_db --load
        Apply schema.sql (DROP + CREATE) then COPY every present (slice, dataset) in. Idempotent.

    application/venv/bin/python -m application.data.serve.build_db --verify
        Assert per-table row counts == the sum over slices that have the dataset, and print
        per-table distinct-league_id counts (panel gating) + an is_mine parity spot-check.

``league_id`` is stamped per slice; ``season`` where the parquet lacks its own. The ``schedule``
parquet already carries a ``league_id`` column (B1) — it is asserted equal to the slice and dropped
before COPY so every table has exactly one. Read-only on all parquet — never recompute derived data.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, namedtuple
from pathlib import Path

import polars as pl
import psycopg
from psycopg.types.json import Jsonb

from application.api.db import database_url
from application.config import SLEEPER_LEAGUE_ID
from application.data import data_layer as dl

LEAGUE_ID = str(SLEEPER_LEAGUE_ID)   # the is_mine live slice — the --emit / parity reference league

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]  # serve -> data -> application -> <repo root>
_SCHEMA_SQL = _HERE / "schema.sql"
_MANIFEST = _HERE / "MANIFEST.md"

# --- the demo slate is the work-list ---------------------------------------------------------
Dataset = namedtuple("Dataset", "table path ref")
# path(season, league_id, scoring_key) -> Path — the derived parquet for that slice (existence
# check + the bytes to load). We load the RAW parquet (all as-of-weeks / snapshots), NOT the
# data_layer read_* accessors — those apply the app's "latest slice" semantics, which would drop
# every week but the newest and break the week switcher. data_layer still owns the PATHS (no
# hand-built paths); the loader is a byte-faithful mirror of each file.
# ref: optional () -> Path, a representative parquet for --emit schema when the is_mine slice can't
# supply it (ros_synthesis lives at its 2026 news season, decoupled from any slice season).


def _lpath(pather):
    """Wrap a league-keyed (season, league_id) path helper into the uniform (season, lid, sk) shape."""
    return lambda s, lid, sk: pather(s, lid)


def _ros_ref_path() -> Path:
    """The is_mine league's ros_synthesis parquet (2026 news season) — --emit schema reference only.
    Never loaded onto a season-mismatched slice; the load reads ros per-slice at the slice's season."""
    files = sorted(dl._league_dir(LEAGUE_ID).glob("ros_synthesis_*.parquet"))
    if not files:
        raise SystemExit("no ros_synthesis parquet found for the schema reference")
    return files[-1]


# 12 league-keyed datasets + 1 scoring-keyed (projection_consensus). Order = load order.
DATASETS: list[Dataset] = [
    Dataset("season",            _lpath(dl._join_season_path), None),
    Dataset("teams",             _lpath(dl._sleeper_teams_path), None),
    Dataset("lineup_slots",      _lpath(dl._lineup_slots_path), None),
    Dataset("league_settings",   _lpath(dl._league_settings_path), None),
    Dataset("player_signal",     _lpath(dl._player_signal_path), None),
    Dataset("production_vor",    _lpath(dl._production_vor_path), None),
    Dataset("market_vor",        _lpath(dl._market_vor_path), None),
    Dataset("ros_synthesis",     _lpath(dl._ros_synthesis_path), _ros_ref_path),
    Dataset("bracket_odds",      _lpath(dl._bracket_odds_path), None),
    Dataset("positional_depth",  _lpath(dl._positional_depth_path), None),
    Dataset("manager_dossiers",  _lpath(dl._manager_dossiers_path), None),
    Dataset("projection_consensus", lambda s, lid, sk: dl._projection_consensus_path(s, sk), None),
    Dataset("schedule",          _lpath(dl._schedule_path), None),
]

_MANIFEST_TABLE = "demo_manifest"   # the 14th table — the lineage catalog GET /api/leagues reads

# Per-table columns to index — what the frontend/catalog filters/joins on, plus (league_id, season)
# added to every table below. manager_dossiers adds (league_id, owner_id) — the owner-keyed-dossier
# prerequisite (OWNER_KEYED_MANAGER_PROFILES.md): keep it a read-swap later, not a reload.
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
    "manager_dossiers": [("roster_id",), ("league_id", "owner_id")],
    "projection_consensus": [("week",), ("sleeper_player_id",)],
    "schedule": [("week",), ("matchup_id",), ("roster_id",)],
    _MANIFEST_TABLE: [("lineage_id",)],
}


def _slices() -> list[tuple[str, int, str]]:
    """(league_id, season, scoring_key) for the 31 demo slices, deterministic order (season, league)."""
    rows = [(str(r["league_id"]), int(r["season"]), str(r["scoring_key"]))
            for r in dl.read_demo_manifest().iter_rows(named=True)]
    rows.sort(key=lambda t: (t[1], t[0]))
    return rows


def _ref() -> tuple[int, str, str]:
    """(season, league_id, scoring_key) of the is_mine live slice — the --emit schema reference."""
    r = (dl.read_demo_manifest()
         .filter(pl.col("is_mine") & pl.col("panels_market")).row(0, named=True))
    return int(r["season"]), str(r["league_id"]), str(r["scoring_key"])


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
        # All-null column (e.g. projection_consensus.disagreement_ppr): parquet carries no usable
        # type. Pick a numeric default so the column exists and stays NULL.
        return "DOUBLE PRECISION"
    return "TEXT"  # String/Categorical and anything else (incl. JSON-encoded-as-string)


def _plan(table: str, schema):
    """Return (ddl_columns, add_season, jsonb_cols) for a per-slice league table.

    ddl_columns: ordered [(name, pgtype)] = league_id, [season], *parquet columns.
    add_season:  True when the parquet lacks its own season column (we stamp the slice's).
    jsonb_cols:  parquet column names that map to JSONB (nested list/struct).
    A pre-existing ``league_id`` column must be dropped by the caller before this (schedule).
    """
    schema = dict(schema)
    schema.pop("league_id", None)
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


def _index_stmts(table: str, extra_composite=("league_id", "season")) -> list[str]:
    out = []
    for cols_tuple in [*INDEXES.get(table, []), extra_composite]:
        idx = "_".join(cols_tuple)
        collist = ", ".join(cols_tuple)
        out.append(f'CREATE INDEX IF NOT EXISTS "ix_{table}_{idx}" ON "{table}" ({collist});')
    return out


def emit() -> None:
    """Regenerate schema.sql + MANIFEST.md from the derived-store schemas (reference = is_mine slice)."""
    rs, rl, rk = _ref()
    if rl != LEAGUE_ID:
        raise SystemExit(f"is_mine reference slice {rl} != config LEAGUE_ID {LEAGUE_ID}")

    ddl_parts: list[str] = [
        "-- GENERATED by application/data/serve/build_db.py --emit. Do not hand-edit.",
        "-- Re-run --emit to regenerate. One table per derived dataset + the demo_manifest catalog.",
        "-- Every per-slice table carries league_id and season for the multi-league store.\n",
    ]
    man_rows: list[str] = []

    for ds in DATASETS:
        ref_path = ds.ref() if ds.ref else ds.path(rs, rl, rk)
        schema = pl.read_parquet_schema(ref_path)
        n = pl.scan_parquet(ref_path).select(pl.len()).collect().item()
        cols, _add_season, jsonb_cols = _plan(ds.table, schema)

        col_defs = ",\n".join(f"    {name} {typ}" for name, typ in cols)
        stmts = [f'DROP TABLE IF EXISTS "{ds.table}" CASCADE;',
                 f'CREATE TABLE "{ds.table}" (\n{col_defs}\n);',
                 *_index_stmts(ds.table)]
        ddl_parts.append("\n".join(stmts) + "\n")

        display_schema = dict(schema)
        display_schema.pop("league_id", None)
        coltypes = ", ".join(f"{name}:{pg_type(dt)}" for name, dt in display_schema.items())
        note = " *(JSONB: " + ", ".join(sorted(jsonb_cols)) + ")*" if jsonb_cols else ""
        man_rows.append(f"| `{ds.table}` | derived-store | per-slice | ~{n} | {len(display_schema)} | {coltypes}{note} |")

    # The demo_manifest catalog table — loaded whole, no league_id/season stamping (native columns).
    man_schema = dl.read_demo_manifest().schema
    man_defs = ",\n".join(f"    {name} {pg_type(dt)}" for name, dt in man_schema.items())
    stmts = [f'DROP TABLE IF EXISTS "{_MANIFEST_TABLE}" CASCADE;',
             f'CREATE TABLE "{_MANIFEST_TABLE}" (\n{man_defs}\n);',
             *_index_stmts(_MANIFEST_TABLE)]
    ddl_parts.append("\n".join(stmts) + "\n")
    man_coltypes = ", ".join(f"{name}:{pg_type(dt)}" for name, dt in man_schema.items())
    man_rows.append(f"| `{_MANIFEST_TABLE}` | demo_manifest.parquet | catalog | 31 | {len(man_schema)} | {man_coltypes} |")

    _SCHEMA_SQL.write_text("\n".join(ddl_parts))

    manifest = [
        "# Loader manifest — derived store -> Postgres (multi-league, Stage-B B3)",
        "",
        "Generated by `build_db.py --emit`. One table per derived dataset (loaded per demo slice, "
        "skip-if-absent) + the `demo_manifest` catalog. `league_id` is stamped per slice; `season` "
        "where the parquet lacks its own. Nested columns become JSONB.",
        "",
        f"Source: the derived store via `data_layer` · schema reference = is_mine slice `{LEAGUE_ID}` "
        f"({rs}). Row counts are the reference slice's; the load spans all 31 slices.",
        "",
        "| Table | Source | Grain | Ref rows | Cols | Columns (parquet -> pg type) |",
        "|---|---|---|---|---|---|",
        *man_rows,
    ]
    _MANIFEST.write_text("\n".join(manifest) + "\n")
    print(f"emitted {_SCHEMA_SQL.relative_to(_REPO_ROOT)} and {_MANIFEST.relative_to(_REPO_ROOT)}")


def _run_sql_script(cur, sql: str) -> None:
    """Execute a multi-statement DDL script (psycopg executes one command per call)."""
    body = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    for stmt in (s.strip() for s in body.split(";")):
        if stmt:
            cur.execute(stmt)


def _copy_slice(conn, table: str, df: pl.DataFrame, lid: str, season: int) -> int:
    """COPY one slice's dataframe into `table`, stamping league_id (+ season if absent). Returns rows.

    If the parquet already carries a league_id column (schedule, B1), assert it equals the slice and
    drop it so the table has exactly one league_id.
    """
    if "league_id" in df.columns:
        vals = set(df["league_id"].unique().to_list())
        if not vals <= {lid}:
            raise SystemExit(f"{table} {lid}/{season}: parquet league_id {vals} != slice {lid}")
        df = df.drop("league_id")
    cols, add_season, jsonb_cols = _plan(table, df.schema)
    col_names = [name for name, _ in cols]
    copy_sql = f'COPY "{table}" ({", ".join(col_names)}) FROM STDIN'
    with conn.cursor() as cur:
        with cur.copy(copy_sql) as cp:
            for row in df.iter_rows(named=True):
                values: list = [lid]
                if add_season:
                    values.append(season)
                for pcol in df.columns:
                    v = row[pcol]
                    if pcol in jsonb_cols:
                        v = Jsonb(v) if v is not None else None
                    values.append(v)
                cp.write_row(values)
    conn.commit()
    return df.height


def _copy_plain(conn, table: str, df: pl.DataFrame) -> int:
    """COPY a table whose parquet already carries its own keys — no stamping (the demo_manifest catalog)."""
    jsonb_cols = {n for n, dt in df.schema.items() if pg_type(dt) == "JSONB"}
    copy_sql = f'COPY "{table}" ({", ".join(df.columns)}) FROM STDIN'
    with conn.cursor() as cur:
        with cur.copy(copy_sql) as cp:
            for row in df.iter_rows(named=True):
                cp.write_row([Jsonb(row[c]) if (c in jsonb_cols and row[c] is not None) else row[c]
                              for c in df.columns])
    conn.commit()
    return df.height


def load() -> None:
    """Apply schema.sql then COPY every present (slice, dataset) + the demo_manifest catalog."""
    if not _SCHEMA_SQL.exists():
        raise SystemExit("schema.sql missing — run --emit first.")
    schema_sql = _SCHEMA_SQL.read_text()
    slices = _slices()

    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            _run_sql_script(cur, schema_sql)
        conn.commit()

        # the catalog table (once, whole, unstamped)
        n = _copy_plain(conn, _MANIFEST_TABLE, dl.read_demo_manifest())
        print(f"loaded {_MANIFEST_TABLE:22s} {n:>6d} rows  (catalog)")

        totals: dict[str, int] = defaultdict(int)
        present: dict[str, int] = defaultdict(int)
        for lid, season, sk in slices:
            for ds in DATASETS:
                p = ds.path(season, lid, sk)
                if not p.exists():
                    continue
                df = pl.read_parquet(p)
                totals[ds.table] += _copy_slice(conn, ds.table, df, lid, season)
                present[ds.table] += 1

    print("\n-- per-table load summary (rows / slices present of 31) --")
    for ds in DATASETS:
        print(f"loaded {ds.table:22s} {totals[ds.table]:>6d} rows  <- {present[ds.table]:>2d} slice(s)")


def _disk_expectations():
    """Per-table (expected_rows, {league_ids present}) recomputed from the derived store on disk."""
    exp_rows: dict[str, int] = defaultdict(int)
    exp_leagues: dict[str, set] = defaultdict(set)
    for lid, season, sk in _slices():
        for ds in DATASETS:
            p = ds.path(season, lid, sk)
            if p.exists():
                exp_rows[ds.table] += pl.scan_parquet(p).select(pl.len()).collect().item()
                exp_leagues[ds.table].add(lid)
    return exp_rows, exp_leagues


def dry_run() -> None:
    """Offline: print the load/skip plan + expected counts, no DB connection."""
    exp_rows, exp_leagues = _disk_expectations()
    print("=== dry-run — derived-store load plan (no DB write) ===")
    print(f"{'table':22s} {'slices':>7s} {'rows':>9s}")
    for ds in DATASETS:
        print(f"{ds.table:22s} {len(exp_leagues[ds.table]):>7d} {exp_rows[ds.table]:>9d}")
    print(f"{_MANIFEST_TABLE:22s} {'1':>7s} {dl.read_demo_manifest().height:>9d}  (catalog)")
    print("\nexpected panel gating: base datasets = 31 slices, manager_dossiers = "
          f"{len(exp_leagues['manager_dossiers'])}, market_vor = {len(exp_leagues['market_vor'])}, "
          f"ros_synthesis = {len(exp_leagues['ros_synthesis'])} (year-match; empty by design).")


def verify() -> None:
    """Assert per-table row counts == the on-disk sum over present slices; print league counts + parity."""
    exp_rows, exp_leagues = _disk_expectations()
    rs, rl, _rk = _ref()
    ok = True
    print(f"{'table':22s} {'disk':>8s} {'postgres':>9s} {'leagues':>8s}  result")
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            for ds in DATASETS:
                cur.execute(f'SELECT count(*), count(DISTINCT league_id) FROM "{ds.table}"')
                db_n, n_leagues = cur.fetchone()
                e = exp_rows[ds.table]
                match = "OK" if db_n == e else "*** MISMATCH ***"
                ok = ok and db_n == e
                print(f"{ds.table:22s} {e:>8d} {db_n:>9d} {n_leagues:>8d}  {match}")

            cur.execute(f'SELECT count(*) FROM "{_MANIFEST_TABLE}"')
            man_n = cur.fetchone()[0]
            man_match = "OK" if man_n == 31 else "*** MISMATCH ***"
            ok = ok and man_n == 31
            print(f"{_MANIFEST_TABLE:22s} {31:>8d} {man_n:>9d} {'-':>8s}  {man_match}")

            # Parity spot-check: the is_mine live slice's per-table counts (ros_synthesis intended 0).
            print(f"\n-- is_mine parity spot-check (league {rl}, season {rs}) --")
            for ds in DATASETS:
                cur.execute(
                    f'SELECT count(*) FROM "{ds.table}" WHERE league_id = %s AND season = %s',
                    (rl, rs),
                )
                print(f"  {ds.table:22s} {cur.fetchone()[0]:>6d}")

    if not ok:
        raise SystemExit("VERIFY FAILED — row-count mismatch vs the derived store on disk")
    print("\nVERIFY OK — every table matches the on-disk sum over present slices; "
          "panel gating visible above (ros_synthesis = 0 by the year-match rule).")


def main() -> None:
    ap = argparse.ArgumentParser(description="Derived store -> Postgres loader (multi-league, Stage-B B3).")
    ap.add_argument("--emit", action="store_true", help="regenerate schema.sql + MANIFEST.md")
    ap.add_argument("--dry-run", action="store_true", help="print the load/skip plan offline (no DB)")
    ap.add_argument("--load", action="store_true", help="apply schema.sql and load all slices")
    ap.add_argument("--verify", action="store_true", help="assert row counts + print league counts + parity")
    args = ap.parse_args()
    if not (args.emit or args.dry_run or args.load or args.verify):
        ap.error("nothing to do — pass --emit, --dry-run, --load and/or --verify")
    if args.emit:
        emit()
    if args.dry_run:
        dry_run()
    if args.load:
        load()
    if args.verify:
        verify()


if __name__ == "__main__":
    main()
