"""Derived-store -> Postgres loader: the multi-league publish seam (Stage-B B3).

Loads ALL served slices — the 31 frozen corpus demo slices (`data_layer.read_demo_manifest()`,
12 lineages) PLUS any generated synthetic league (`read_synthetic_catalog`, P5/S2d: the public demo
clone) — from the **derived store** into Supabase Postgres, keyed by league_id + season. The two
sources are unioned by `_catalog()`; keeping them separate is what lets the CORPUS stay at 31 while
the SERVED catalog grows.
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

    application/venv/bin/python -m application.data.serve.build_db --reload-league <league_id>
        Per-league SCOPED RELOAD (the in-season incremental path): in one transaction, DELETE that
        league's rows across the 14 data tables and re-COPY its slice — every other league untouched.
        Advances one league to a new as_of_week without a whole-DB DROP+CREATE. --load stays the
        fallback + the byte-parity oracle's baseline (see serve/check_scoped_reload.py).

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
from application.api import settings
from application.data import data_layer as dl

# The is_mine live slice — the --emit / parity reference league. Resolved env-first (LEAGUE_ID) with a
# config.py fallback via settings, so the loader imports where config.py is absent (CI / the Fly image —
# values from env), mirroring db.database_url(). None only if neither is set → the reference-league paths
# (--emit / the parity oracle) fail clearly; the per-league scoped reload takes an explicit id regardless.
LEAGUE_ID = str(settings.league_id() or "")

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


# --- the honest-band boundary (P2/S3b) --------------------------------------------------------
# The ROS band is served ONLY where it was built under the live constants. 2020-2025 sit in the
# FROZEN CORPUS at pre-8c CENTER_SHRINK=1.0 — the immutable out-of-sample certification baseline the
# L2 predictions ledger was derived from — so those files are never loaded here and never rebuilt.
# (Serving them would also contradict the card: production_vor.ros_value is honest at 0.8, so a stale
# ros_center would render ~1.25x above the VOR beside it.) A future corpus re-backfill under a new
# code_version — the annual pipeline's job, not a session's — is what lowers this constant.
FIRST_HONEST_BAND_SEASON = 2026

# A path that never exists: the "not served for this slice" signal every consumer already understands
# — load()/load_league()'s skip-if-absent, verify()'s disk expectation, and --dry-run's plan all read
# it the same way, so the boundary is stated once here instead of special-cased in each loop.
_NOT_SERVED = _HERE / "__not_served__" / "frozen_corpus_band.parquet"


def _honest_band_path(season: int, _lid, scoring_key) -> Path:
    """The ros_player_band parquet for a slice — scoring-keyed (the league_id is ignored, exactly like
    projection_consensus), and absent below FIRST_HONEST_BAND_SEASON so the frozen corpus never loads."""
    if int(season) < FIRST_HONEST_BAND_SEASON:
        return _NOT_SERVED
    return dl._ros_player_band_path(season, scoring_key)


def _band_ref_path() -> Path:
    """The honest 2026 band parquet — --emit schema reference only (the _ros_ref_path precedent).

    No demo slice keys 2026 yet, so no slice can supply this table's DDL; it comes from the file the
    first live 2026 league will load. Emitting the table before any row exists is the point: the wire
    is in place, and the panel lights up when a 2026 league is onboarded."""
    p = dl._ros_player_band_path(FIRST_HONEST_BAND_SEASON, _ref()[2])
    if not p.exists():
        raise SystemExit(f"no {FIRST_HONEST_BAND_SEASON} ros_player_band for the schema reference: {p}")
    return p


# 12 league-keyed datasets + 2 scoring-keyed (projection_consensus, ros_player_band). Order = load order.
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
    Dataset("ros_player_band",   _honest_band_path, _band_ref_path),
    Dataset("schedule",          _lpath(dl._schedule_path), None),
]

# The lineage catalog `GET /api/leagues` reads. Renamed from `demo_manifest` in P5/S2d, and the
# rename is the point: `demo_manifest` named BOTH this table and the corpus parquet it used to be a
# straight copy of, and S2d makes them hold different counts — the parquet keeps its 31 frozen corpus
# slices, this table gains the generated demo clone. Renaming the thing that CHANGED leaves the one
# that didn't alone. (`corpus_manifest` was unavailable: it names the frozen 271-league manifest.)
_MANIFEST_TABLE = "league_catalog"

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
    "ros_player_band": [("as_of_week",), ("sleeper_player_id",)],
    "schedule": [("week",), ("matchup_id",), ("roster_id",)],
    _MANIFEST_TABLE: [("lineage_id",)],
}


def _catalog() -> pl.DataFrame:
    """THE served catalog: the 31 frozen corpus slices, PLUS any generated synthetic league (P5/S2d),
    PLUS every league a real user has connected (P5/S4a). 31 + 1 + N.

    The concatenation is the layer boundary in one expression. ``demo_manifest.parquet`` is a CORPUS
    artifact and stays at 31 rows — ``compute_demo_slices``, ``check_matchup_result`` and the L2
    ledger all count on that. The demo clone is a SERVE artifact with its own parquet. Appending the
    clone to the corpus manifest instead would have been one line shorter and would have quietly made
    the engine's work-list 32.

    S4a applied the same reasoning a third time rather than arguing with it: a connected league is
    neither corpus nor generated, it arrives one at a time forever, and it is the only one of the
    three a WORKER may write. Three sources, three owners, one served catalog.

    ``how="vertical"`` is polars' STRICT concat — identical names, order and dtypes — which is why
    ``write_connected_league`` casts rather than merely selecting. A dtype slip in one connected row
    would raise here, i.e. take out the catalog for every visitor.
    """
    return pl.concat([dl.read_demo_manifest(), dl.read_synthetic_catalog(),
                      dl.read_connected_catalog()], how="vertical")


def _slices() -> list[tuple[str, int, str]]:
    """(league_id, season, scoring_key) for every served slice, deterministic order (season, league)."""
    rows = [(str(r["league_id"]), int(r["season"]), str(r["scoring_key"]))
            for r in _catalog().iter_rows(named=True)]
    rows.sort(key=lambda t: (t[1], t[0]))
    return rows


def _ref() -> tuple[int, str, str]:
    """(season, league_id, scoring_key) of the is_mine live slice — the --emit schema reference.

    This one row decides the DDL for the ENTIRE database, so the filter must resolve to exactly one
    row and `.row(0)` would silently take the first of many. It reads ``read_demo_manifest()`` and
    NOT ``_catalog()``, which is the structural reason a synthetic or connected league can never
    become the schema reference — S4a's connected rows live in their own parquet and are not visible
    from here at all. The assertion states that rather than leaving it to be inferred from which
    reader happens to be called.
    """
    mine = dl.read_demo_manifest().filter(pl.col("is_mine") & pl.col("panels_market"))
    if mine.height != 1:
        raise SystemExit(
            f"the --emit schema reference is ambiguous: {mine.height} rows in demo_manifest satisfy "
            f"(is_mine & panels_market), expected exactly 1. Every table's DDL is derived from this "
            f"single slice, so a second row would change the schema depending on row order.")
    r = mine.row(0, named=True)
    return int(r["season"]), str(r["league_id"]), str(r["scoring_key"])


def _table_schema(ds: "Dataset") -> dict:
    """The UNION of columns across every slice that has this dataset (+ the --emit reference), so the
    DDL is a superset. Slices are heterogeneous: division-aware corpus leagues carry a ``division``
    column the is_mine slice lacks. Each column resolves to the first NON-Null dtype seen (an all-Null
    column stays Null -> DOUBLE via pg_type). A per-slice COPY names only its own columns, so a slice
    missing a union column simply leaves it NULL."""
    rs, rl, rk = _ref()
    ref_path = ds.ref() if ds.ref else ds.path(rs, rl, rk)
    sources = [ref_path] + [ds.path(s, lid, sk) for lid, s, sk in _slices()]
    merged: dict = {}
    for p in sources:
        if not p.exists():
            continue
        for name, dt in pl.read_parquet_schema(p).items():
            if name not in merged or (merged[name].base_type() == pl.Null and dt.base_type() != pl.Null):
                merged[name] = dt
    merged.pop("league_id", None)
    return merged


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


def _rls_stmt(table: str) -> str:
    """Row-level security for a generated table (P5/S2d).

    **Why this is emitted rather than remembered.** RLS was enabled by hand in the Supabase console.
    A later `--emit`/`--load` recreated `ros_player_band` — and it came back WITHOUT RLS, because a
    DROP takes every out-of-band property with it and nothing put this one back. That is the general
    failure, not a one-off: any property applied outside the generator (RLS, a grant, a trigger) is
    destroyed by the next full load. Emitting it makes the property reproducible instead of
    remembered, which is the same argument as generating the demo clone rather than inserting it.

    Defence-in-depth, not the authorization boundary: the app connects as an owner-role user that
    BYPASSES RLS, and isolation is enforced in the API layer (`reads.authorize_slice`). What this
    protects is the Data API surface, which is off today and would otherwise be one console toggle
    away from exposure.
    """
    return f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;'


def emit() -> None:
    """Regenerate schema.sql + MANIFEST.md from the derived-store schemas (reference = is_mine slice)."""
    rs, rl, rk = _ref()
    if rl != LEAGUE_ID:
        raise SystemExit(f"is_mine reference slice {rl} != config LEAGUE_ID {LEAGUE_ID}")

    ddl_parts: list[str] = [
        "-- GENERATED by application/data/serve/build_db.py --emit. Do not hand-edit.",
        "-- Re-run --emit to regenerate. One table per derived dataset + the league_catalog table.",
        "-- Every per-slice table carries league_id and season for the multi-league store.\n",
    ]
    man_rows: list[str] = []

    for ds in DATASETS:
        ref_path = ds.ref() if ds.ref else ds.path(rs, rl, rk)
        schema = _table_schema(ds)   # UNION across slices — superset DDL (e.g. teams.division)
        n = pl.scan_parquet(ref_path).select(pl.len()).collect().item()
        cols, _add_season, jsonb_cols = _plan(ds.table, schema)

        col_defs = ",\n".join(f"    {name} {typ}" for name, typ in cols)
        stmts = [f'DROP TABLE IF EXISTS "{ds.table}" CASCADE;',
                 f'CREATE TABLE "{ds.table}" (\n{col_defs}\n);',
                 *_index_stmts(ds.table),
                 _rls_stmt(ds.table)]
        ddl_parts.append("\n".join(stmts) + "\n")

        display_schema = dict(schema)
        display_schema.pop("league_id", None)
        coltypes = ", ".join(f"{name}:{pg_type(dt)}" for name, dt in display_schema.items())
        note = " *(JSONB: " + ", ".join(sorted(jsonb_cols)) + ")*" if jsonb_cols else ""
        man_rows.append(f"| `{ds.table}` | derived-store | per-slice | ~{n} | {len(display_schema)} | {coltypes}{note} |")

    # The league_catalog table — loaded whole, no league_id/season stamping (native columns).
    man_schema = _catalog().schema
    man_defs = ",\n".join(f"    {name} {pg_type(dt)}" for name, dt in man_schema.items())
    # The catalog table is a SEPARATE block from the DATASETS loop, which is exactly how it would
    # have been missed: it is the 15th table and the easiest one to forget.
    stmts = [f'DROP TABLE IF EXISTS "{_MANIFEST_TABLE}" CASCADE;',
             f'CREATE TABLE "{_MANIFEST_TABLE}" (\n{man_defs}\n);',
             *_index_stmts(_MANIFEST_TABLE),
             _rls_stmt(_MANIFEST_TABLE)]
    ddl_parts.append("\n".join(stmts) + "\n")
    man_coltypes = ", ".join(f"{name}:{pg_type(dt)}" for name, dt in man_schema.items())
    man_rows.append(f"| `{_MANIFEST_TABLE}` | demo_manifest.parquet + synthetic_catalog.parquet | "
                    f"catalog | {_catalog().height} | {len(man_schema)} | {man_coltypes} |")

    _SCHEMA_SQL.write_text("\n".join(ddl_parts))

    manifest = [
        "# Loader manifest — derived store -> Postgres (multi-league, Stage-B B3)",
        "",
        "Generated by `build_db.py --emit`. One table per derived dataset (loaded per demo slice, "
        "skip-if-absent) + the `league_catalog` table. `league_id` is stamped per slice; `season` "
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


def _assert_columns_live(conn, table: str, col_names: list[str], lid: str, season: int) -> None:
    """Refuse a COPY whose columns the DEPLOYED table does not have (P5/S4a's onboarding preflight).

    `_table_schema` builds each table's DDL as a UNION across the slices that existed at the last
    ``--emit``, and `_copy_slice_tx` names only the slice's OWN columns — which is what makes the
    superset tolerant: a slice missing a union column just leaves it NULL. The reverse has no such
    grace. A slice carrying a column the union never saw makes Postgres raise `UndefinedColumn`
    mid-COPY, inside a transaction, naming one column and nothing about why.

    That is a real onboarding failure mode for a STRANGER's league, because the union was computed
    over the corpus and the demo, not over whatever shape a new user brings. `teams.division` is the
    known shape-dependent column and it *is* emitted; measured 2026-08-14 across all 14 datasets ×
    272 on-disk leagues, **no** column on disk is absent from the deployed DDL. So this fires on a
    shape the store has never seen, which is exactly when a bare `UndefinedColumn` would be least
    informative.

    It does NOT fix the problem, deliberately: the remedy is `--emit` + `--load`, which DROPs every
    table on the production database and needs a planned outage (S2d spent 145s on one). A refusal
    that names the column, the table and the remedy is the honest stop.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s", (table,))
        live = {r[0] for r in cur.fetchall()}
    if not live:
        raise SystemExit(f'table "{table}" does not exist in this database — run build_db --load.')
    missing = [c for c in col_names if c not in live]
    if missing:
        raise SystemExit(
            f'{lid}/{season}: "{table}" is missing column(s) {missing} in the deployed database.\n'
            f"  This league carries a shape the schema was never emitted for — the DDL is a UNION\n"
            f"  across the slices present at the last --emit, and this slice is outside it.\n"
            f"  Remedy (OPERATOR, needs a planned outage — it DROPs every table):\n"
            f"    build_db --emit && build_db --load && fly deploy\n"
            f"  Do NOT run that from an onboarding job.")


def _copy_slice_tx(conn, table: str, df: pl.DataFrame, lid: str, season: int) -> int:
    """COPY one slice's dataframe into `table`, stamping league_id (+ season if absent). Returns rows.
    Does NOT commit — the caller owns the transaction (the full load commits per slice; the per-league
    scoped reload batches all deletes+copies into a single commit).

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
    _assert_columns_live(conn, table, col_names, lid, season)
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
    return df.height


def _copy_slice(conn, table: str, df: pl.DataFrame, lid: str, season: int) -> int:
    """COPY one slice and commit — the full-load path (one commit per slice, unchanged from before)."""
    n = _copy_slice_tx(conn, table, df, lid, season)
    conn.commit()
    return n


def _copy_plain(conn, table: str, df: pl.DataFrame) -> int:
    """COPY a table whose parquet already carries its own keys — no stamping (the league_catalog)."""
    jsonb_cols = {n for n, dt in df.schema.items() if pg_type(dt) == "JSONB"}
    copy_sql = f'COPY "{table}" ({", ".join(df.columns)}) FROM STDIN'
    with conn.cursor() as cur:
        with cur.copy(copy_sql) as cp:
            for row in df.iter_rows(named=True):
                cp.write_row([Jsonb(row[c]) if (c in jsonb_cols and row[c] is not None) else row[c]
                              for c in df.columns])
    conn.commit()
    return df.height


def upsert_catalog_row(conn, lid: str) -> int:
    """Replace this league's `league_catalog` row(s) from `_catalog()`. Does NOT commit.

    THE SCOPED ALTERNATIVE TO `reload_manifest`, and the reason the worker can catalog a league at
    all. `reload_manifest` TRUNCATEs the whole table and re-COPYs it from the LOCAL store — on the
    worker that store is a seeded, read-only, possibly-stale copy, so calling it there could erase
    catalog rows the laptop knows about. That is the same whole-file-overwrite shape the parquet
    wall had, reappearing at the Postgres layer; the same answer applies, one row instead of all.

    DELETE-then-INSERT rather than `ON CONFLICT`: `league_catalog` has no primary key and no unique
    constraint (only two non-unique indexes), so there is no conflict target to name. Both
    statements share the caller's transaction — the same single-commit shape `load_league` uses —
    so a concurrent reader sees the pre- or post-state and never a gap.
    """
    rows = _catalog().filter(pl.col("league_id").cast(str) == str(lid))
    if not rows.height:
        raise SystemExit(f"{lid} is not in any catalog parquet — nothing to upsert. Onboarding "
                         "writes the connected_catalog row BEFORE the load.")
    cols = list(rows.columns)
    with conn.cursor() as cur:
        cur.execute(f'DELETE FROM "{_MANIFEST_TABLE}" WHERE league_id = %s', (str(lid),))
        placeholders = ", ".join(["%s"] * len(cols))
        for row in rows.iter_rows(named=True):
            cur.execute(f'INSERT INTO "{_MANIFEST_TABLE}" ({", ".join(cols)}) '
                        f"VALUES ({placeholders})", [row[c] for c in cols])
    return rows.height


def reload_manifest() -> None:
    """Refresh ONLY the league_catalog table (Stage-B B4 catalog-only write) — TRUNCATE +
    re-COPY in one transaction, leaving the 31 data-slice tables untouched. The table schema is
    unchanged (only panel-flag values differ), so no DROP/CREATE/--emit is needed; atomic, so a
    concurrent reader never sees the catalog empty.

    **Laptop only.** It rebuilds the table from `_catalog()` on the LOCAL store, so a machine whose
    store is a seeded snapshot would publish that snapshot over the real thing — deleting connected
    leagues it has never heard of. The refusal is here rather than in `data_layer`'s allow-list
    because this writes POSTGRES, not the file store; it is the first boundary guard at that layer,
    and the worker's scoped equivalent is `upsert_catalog_row`.
    """
    if dl.store_role() == "worker":
        raise dl.StoreBoundaryError(
            "reload_manifest() is refused on this machine: STORE_ROLE=worker.\n"
            "  It TRUNCATEs league_catalog and re-COPYs it from this machine's local store, which on "
            "a worker is a seeded snapshot — so any league the laptop catalogued after the last seed "
            "would be silently deleted from the served catalog.\n"
            "  The store boundary is one-directional (context/appendices/store-boundary.md).\n"
            "  Remedy: a worker catalogs ONE league at a time via build_db.upsert_catalog_row, which "
            "the onboarder calls inside the load's transaction. Run reload_manifest on the laptop.")
    df = _catalog()          # the union, or a catalog-only refresh would drop the synthetic rows
    jsonb_cols = {n for n, dt in df.schema.items() if pg_type(dt) == "JSONB"}
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(f'TRUNCATE "{_MANIFEST_TABLE}"')
            copy_sql = f'COPY "{_MANIFEST_TABLE}" ({", ".join(df.columns)}) FROM STDIN'
            with cur.copy(copy_sql) as cp:
                for row in df.iter_rows(named=True):
                    cp.write_row([Jsonb(row[c]) if (c in jsonb_cols and row[c] is not None) else row[c]
                                  for c in df.columns])
        conn.commit()
    print(f"reloaded {_MANIFEST_TABLE} ({df.height} rows) — catalog-only; the 31 data slices untouched")


def _tables_present(conn) -> None:
    """Guard: the 14 data tables must already exist. A scoped reload REUSES the emitted union-superset
    schema and never DROP/CREATEs — a per-league CREATE would narrow the union (e.g. drop the division
    columns other leagues need). If a table is missing, the DB was never fully loaded — run --load first."""
    names = [ds.table for ds in DATASETS]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY(%s)", (names,))
        have = {r[0] for r in cur.fetchall()}
    missing = [t for t in names if t not in have]
    if missing:
        raise SystemExit(f"tables missing {missing} — run --load (full DROP+CREATE) first.")


def load_league(conn, lid: str, *, verify_schema: bool = True,
                catalog: bool = False) -> dict[str, int]:
    """Per-league SCOPED RELOAD — the incremental, in-season alternative to the whole-DB DROP+CREATE
    ``load()``. In ONE transaction: DELETE this league's rows from the 14 data tables, then re-COPY its
    present (slice, dataset) parquets; a single commit at the end. Every OTHER league — and by default
    the ``league_catalog`` — is left untouched. This is how a league advances to a new week (a fresh
    ``as_of_week`` slice) without rebuilding the DB.

    Atomicity (modeled on ``reload_manifest``): all DELETEs + COPYs share one transaction / one commit, so
    a concurrent API reader never sees the league half-deleted (it sees the pre- or post-state, never a
    gap). Never DROP/CREATE — reuses the existing union-superset schema; ``_tables_present`` guards that it
    exists. Returns per-table rows copied.

    ``catalog=True`` (P5/S4a onboarding) additionally upserts this league's ``league_catalog`` row in
    the SAME transaction, so a first connect is atomic end to end: the league becomes discoverable
    and readable together, or neither. The weekly refresh leaves it False — a league already in the
    catalog does not need its row rewritten every week.
    """
    if verify_schema:
        _tables_present(conn)
    # A redraft league_id is unique per season, so this is normally one (season, scoring_key) slice; if a
    # league_id ever spanned seasons the DELETE (by league_id) clears all and every slice is re-COPYd.
    slices = [(s, sk) for l, s, sk in _slices() if l == lid]
    if not slices:
        raise SystemExit(f"league {lid} is not a served slice — nothing to reload (cataloging a "
                         "brand-new league is onboarding/P5, not the scoped reload).")
    counts: dict[str, int] = defaultdict(int)
    with conn.cursor() as cur:
        for ds in DATASETS:
            cur.execute(f'DELETE FROM "{ds.table}" WHERE league_id = %s', (lid,))
    for season, sk in slices:
        for ds in DATASETS:
            p = ds.path(season, lid, sk)
            if not p.exists():
                continue   # skip-if-absent, exactly like load()
            counts[ds.table] += _copy_slice_tx(conn, ds.table, pl.read_parquet(p), lid, season)
    if catalog:
        counts[_MANIFEST_TABLE] = upsert_catalog_row(conn, lid)
    conn.commit()   # single atomic commit for the whole league
    return dict(counts)


def reload_league(lid: str) -> None:
    """Scoped reload of one league (owns its connection, like ``reload_manifest``)."""
    with psycopg.connect(database_url()) as conn:
        counts = load_league(conn, lid)
    total = sum(counts.values())
    print(f"reloaded league {lid} — {total} rows across {len(counts)} table(s); "
          f"every other league + league_catalog untouched")
    for ds in DATASETS:
        if counts.get(ds.table):
            print(f"  {ds.table:22s} {counts[ds.table]:>6d} rows")


def load() -> None:
    """Apply schema.sql then COPY every present (slice, dataset) + the league_catalog."""
    if not _SCHEMA_SQL.exists():
        raise SystemExit("schema.sql missing — run --emit first.")
    schema_sql = _SCHEMA_SQL.read_text()
    slices = _slices()

    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            _run_sql_script(cur, schema_sql)
        conn.commit()

        # the catalog table (once, whole, unstamped)
        n = _copy_plain(conn, _MANIFEST_TABLE, _catalog())
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
    print(f"{_MANIFEST_TABLE:22s} {'1':>7s} {_catalog().height:>9d}  (catalog)")
    print(f"\nexpected panel gating: base datasets = {len(_slices())} slices, manager_dossiers = "
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

            # Derived from the same union the load reads, not a literal. It WAS a literal 31, which
            # would have been the one executable count-site to fail the moment the clone landed —
            # and it would have failed as "the loader is broken" rather than "a constant is stale".
            cur.execute(f'SELECT count(*) FROM "{_MANIFEST_TABLE}"')
            man_n = cur.fetchone()[0]
            man_exp = _catalog().height
            man_match = "OK" if man_n == man_exp else "*** MISMATCH ***"
            ok = ok and man_n == man_exp
            print(f"{_MANIFEST_TABLE:22s} {man_exp:>8d} {man_n:>9d} {'-':>8s}  {man_match}")

            # RLS, asserted for the first time (P5/S2d). Nothing anywhere read `relrowsecurity`
            # before this, which is precisely why `ros_player_band` sat with RLS off for weeks
            # without anything noticing. A property that is emitted but never checked is still
            # remembered rather than guaranteed.
            print("\n-- row-level security (every generated table) --")
            cur.execute("""
                SELECT c.relname, c.relrowsecurity FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname = ANY(%s)
            """, ([ds.table for ds in DATASETS] + [_MANIFEST_TABLE],))
            rls = dict(cur.fetchall())
            expected = [ds.table for ds in DATASETS] + [_MANIFEST_TABLE]
            off = sorted(t for t in expected if not rls.get(t))
            missing = sorted(t for t in expected if t not in rls)
            if missing:
                print(f"*** {len(missing)} table(s) MISSING from the database: {missing}")
                ok = False
            if off:
                print(f"*** RLS OFF on {len(off)}: {off}  — re-run --emit then --load")
                ok = False
            else:
                print(f"all {len(expected)} generated tables have RLS enabled  OK")

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
    ap.add_argument("--reload-manifest", action="store_true",
                    help="refresh ONLY the league_catalog table (TRUNCATE+COPY; data slices untouched)")
    ap.add_argument("--reload-league", metavar="LID", default=None,
                    help="per-league SCOPED RELOAD: delete + re-COPY one league in one transaction "
                         "(incremental; every other league + league_catalog untouched)")
    ap.add_argument("--verify", action="store_true", help="assert row counts + print league counts + parity")
    args = ap.parse_args()
    if not (args.emit or args.dry_run or args.load or args.reload_manifest or args.reload_league or args.verify):
        ap.error("nothing to do — pass --emit, --dry-run, --load, --reload-manifest, --reload-league and/or --verify")
    if args.emit:
        emit()
    if args.dry_run:
        dry_run()
    if args.load:
        load()
    if args.reload_manifest:
        reload_manifest()
    if args.reload_league:
        reload_league(args.reload_league)
    if args.verify:
        verify()


if __name__ == "__main__":
    main()
