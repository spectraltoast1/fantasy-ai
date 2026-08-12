# Appendix: Store Schema

**Scope:** the served Postgres store. Referenced from `ARCHITECTURE.md`. For how the data gets *into* these
tables, see appendix: data-collection; for the reads' meaning, see appendix: engine-decision-reads.

The served store is **14 data tables + the `league_catalog`** (15 in all), generated from the derived
parquet by `application/data/serve/build_db.py` (do not hand-edit `schema.sql`; re-emit it). **Every row
carries `league_id` + `season`**, indexed on its real filter columns and a composite `(league_id, season)`.
Most analytic tables are "tall" — one slice per `as_of_week` — which is what lets the app replay any week.
**All 15 carry `ENABLE ROW LEVEL SECURITY`, emitted by `--emit`** since P5/S2d, so a full load can no
longer drop it (`--verify` asserts it).

**The catalog table was renamed from `demo_manifest` in P5/S2d, and the rename carries the meaning.**
`demo_manifest` named both the frozen corpus parquet and this table, which was a straight copy of it —
harmless until S2d made them hold different counts. **The parquet is a CORPUS artifact and stays at 31
slices** (`compute_demo_slices`, `check_matchup_result` and the L2 ledger all count on it); **the table is
a SERVE artifact and is 32**, the 31 plus the generated demo clone, unioned by `build_db._catalog()` from
`demo_manifest.parquet` + `synthetic_catalog.parquet`. The clone is never appended to the corpus parquet.

| Table | Grain | Holds |
|---|---|---|
| `season` | player × week | The nfl-stats↔Sleeper join — player identity, records, all-play. The widest table. |
| `teams` | roster_id | roster_id → team/owner names + `owner_id` (owner-keyed-dossier prereq). |
| `lineup_slots` | league | Starting skill-slot config; drives optimal lineup + the 1QB/superflex label. |
| `league_settings` | section × key | Scoring + playoff config (e.g. reception value, playoff teams/week). |
| `player_signal` | player × as_of_week | Spike/opportunity read — is production real or noise. |
| `production_vor` | player × as_of_week | Production value-over-replacement; the Players table default sort. |
| `market_vor` | player × snapshot_date | Market VOR + `trade_gap` + `is_cross_time` (the 2026×2025 POC flag). |
| `ros_synthesis` | player × week | AI ROS bull/bear/situation grades + headlines + confidence. Sparse; currently loads 0 rows. |
| `bracket_odds` | roster_id × as_of_week | `playoff_odds`, `proj_wins`, `avg_seed`, `magic_wins` (10k Monte Carlo). |
| `positional_depth` | roster_id × position × as_of_week | Per-position starter/surplus/marginal value. |
| `manager_dossiers` | roster_id (+`owner_id` indexed) | AI manager dossier headline + tendencies. |
| `projection_consensus` | player × week 1–18 | Forward band: `center_ppr` / `p25/50/75_ppr` / `band_ppr`. |
| `schedule` | week × roster_id | Pairings only — points are dropped upstream so future results never reach the client. |
| `league_catalog` | lineage × season | The catalog `GET /api/leagues` reads: lineage→seasons tree, viewer, panels. 32 rows = the 31 corpus slices + the demo clone. |

**Naming wart:** the `projection_consensus` columns are named `*_ppr` (`center_ppr`, `p50_ppr`, …) but hold
**league** points, not PPR — a `*_ppr` name here does *not* imply PPR scoring. The rename is parked (it would
touch `queries.js` + the persisted columns). See appendix: scoring-mechanism.

**Not in the served store (deliberately):** the engine-improvement **ledger** — `predictions_{season}`,
`outcomes_{season}`, `resolutions_{season}`, `engine_scorecard_{season}` — lives under
`snapshots/derived/ledger/`. It is the immutable tuning/validation spine; the front end never reads it. See
appendix: engine-improvement-loop.

**Load model (current):** `build_db.py --load` does a full **DROP+CREATE** reload; the DDL is a **union**
across slices (e.g. division-aware leagues carry a `teams.division` column others leave NULL). There is no
incremental in-season refresh yet — building one is V1 project P2.
