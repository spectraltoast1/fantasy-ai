# Technical Architecture

> Engineering context document for Claude Code. Describes the stack, folder structure, data layer design, and technical principles. Updated regularly as the project evolves.

**Last reviewed:** 2026-05-31

---

## Project Summary

A fantasy football analytics dashboard (v1) and AI advisor (v2+). V1 is a pure analytics dashboard - no AI component. The data layer is shared between the dashboard and the future AI advisor. All fetchers write to a common data layer that both halves read from.

Winning a redraft fantasy football championship is about more than just collecting all of the best players. It is about how you manage your specific team in your specific league. Knowing when you need to act - or not act - as a team manager is as valuable as knowing which individual players to target or avoid. This tool focuses on helping you navigate your league using real data signals: how your team is trending, where your real weaknesses are, and what your opponents look like. The goal is fewer decisions driven by anxiety or noise, and more decisions made on league-winning signal.

---

## Tech Stack

- **Language:** Python for the data layer/pipeline; JS/React in the front-end playground
- **Data manipulation:** polars (not pandas) - nflreadpy returns polars DataFrames; use polars syntax throughout
- **NFL stats:** nflreadpy (successor to deprecated nfl_data_py) - returns polars DataFrames
- **Front-end:** React + Vite + DuckDB (decided). Original plan was Dash + Plotly; switched after a vertical slice in the real stack validated it and proved easier to iterate than a chat artifact.
- **Data delivery (V1):** client-side DuckDB-WASM — the browser reads parquet and runs SQL; no server, static hosting only. A server/API was **deliberately deferred, not ruled out** — switch to one when warranted (multiple users, data too large to ship to the browser, or secrets to protect). The swap point is the front-end data-access layer `src/queries.js`; the view components never call data access directly, so moving "read files" → "call API" won't touch them.
- **Query layer:** DuckDB — SQL directly over parquet. Adopted as the query layer (in use now in the front-end); carries into the production app.
- **Market values:** LeagueLogs API (keyed on sleeperPlayerId; QB/RB/WR/TE only; visible attribution required)
- **Scheduling:** launchd (macOS) for daily fetchers
- **Storage:** JSON (cache), parquet (snapshots), JSONL (advisor log - future)
- **HTTP:** requests library

---

## Client/Server Seam — Invariants

V1 runs client-side (DuckDB-WASM in the browser, no server). Going server-side
(a Python API) one day is **expected, not hypothetical** — the goal is to keep
that switch boring. This is a bounded, ~5-item surface, not a sprawling one. Keep
these invariants true and the switch stays a localized swap rather than a rewrite:

1. **All data access lives in `src/queries.js`.** It is the single seam. Going
   server-side means rewriting the bodies of its functions ("read parquet" → "call
   API") and nothing else in the data path. This is the one that makes everything
   below cheap.
2. **View components never touch data access directly.** `App.jsx` and future
   panels call `queries.js` functions and consume plain JS values/objects — never
   SQL, never DuckDB handles, never file paths. If a view knows it's reading a
   parquet file, the seam has leaked.
3. **No DuckDB-WASM specifics outside `queries.js`/`db.js`.** SQL strings, DuckDB
   quirks, and `.parquet` awareness stay behind the seam. A server build would
   change `db.js` (how data is located/loaded) without touching views.
4. **Data addressing is config-level, not scattered.** Today: symlinks in
   `public/data/` + `db.js` registering files. A server serves these instead. Keep
   "where the data is" in `db.js`, so the answer changes in one place.
5. **Don't bake in "no auth / no secrets / whole dataset fits in the browser."**
   These are the conditions that *trigger* the server decision (multiple users,
   data too large to ship, secrets to protect) — not things to pre-engineer now.
   Just don't write code that assumes their absence is permanent.

This is a one-time checklist, not a living log: if these hold, the migration is a
swap. It is intentionally kept here (single source of truth) rather than in a
separate decisions doc.

---

## Version Roadmap (subject to change)
- **V1** — Team overview, league standings, matchup review (no AI)
- **V2** — Waiver wire analysis (requires Sleeper full player database fetcher)
- **V3** — Start/sit recommendations (requires FantasyPros projections fetcher)
- **V4** — Trade analysis (LeagueLogs market value — data collection started 2026-05-31; features still V4)
- **V5** — AI-powered insights (major update, builds on complete data layer)
- **V6+** — More complex analytics (TBD)

## Known Scope Exclusions
**DST/K (V1):** Excluded from all V1 transforms and dashboard work. DSTs are stripped at join time via team abbreviation detection (Sleeper represents DSTs as all-uppercase team codes in matchup data). Kickers are removed by the SKILL_POSITIONS filter applied after the join. All joins and visualizations assume skill positions only: QB, RB, WR, TE.

**Waiver wire / full player pool (V1):** The Sleeper player registry is now cached via fetch_players() in sleeper.py (cache/sleeper/players.parquet, max once per 24 hours). This cache is used by the auditor at join time to resolve unknown-position players. Full player pool analysis against all available (non-rostered) players remains V2 scope.

**IR roster overages:** Managers using IR slots can carry more than the standard 17 roster spots. The join reconciliation handles this correctly — it counts whatever Sleeper reports. Expect 18-player rosters from 1–2 teams per week in-season.

**Zero-stat row context:** Rostered players who did not play (injured, suspended, inactive, not yet activated) appear in the join output with all stat columns at 0.0. No signal is provided for why they scored 0. Requires a separate Sleeper injury/status endpoint fetch to resolve. Treat 0-stat rows as "rostered, did not contribute" without assuming a specific reason.

---

## Folder Structure

```
fantasy-ai/
├── project_management/
│   ├── TECHNICAL_ARCHITECTURE.md   (this file)
    ├── STATUS.md
    ├── PRODUCT_ROADMAP.md
    ├── PROJECT_OVERVIEW.md
│   ├── data_sources.txt
│   └── journal/
└── application/
    ├── frontend/                   # production front-end — React + Vite + DuckDB-WASM (Node)
    │   ├── src/                     #   App.jsx (view), queries.js (data-access layer), db.js (DuckDB-WASM loader)
    │   └── public/data/             #   symlink → snapshots/.../season_2025.parquet (gitignored)
    ├── data/
        ├── data_layer.py           # ✅ built — centralized read/write module
    │   ├── fetchers/               # one Python script per source (tracked in git)
    │   │   ├── nfl_stats.py        # ✅ built
    │   │   ├── sleeper.py          # ✅ built
    │   │   ├── leaguelogs.py       # ✅ built — daily market-value snapshots
    │   │   └── scheduler/          #   tracked launchd plist + README for the daily snapshot job
    │   │       ├── com.fantasyai.leaguelogs-snapshot.plist
    │   │       └── README.md
    │   ├── cache/                  # current state (gitignored)
    │   │   ├── player_id_map.parquet  # gsis_id → sleeperPlayerId mapping
    │   │   └── sleeper/
    │   │       └── players.parquet    # Sleeper /players/nfl registry, refreshed ≤ once/day
    │   └── snapshots/              # time-series parquet (gitignored)
            ├── leaguelogs/
            │   └── market_values.parquet            # daily market-value history, all profiles
            └── nfl_sleeper_weekly_joined/
                ├── season_2025.parquet                  # join output, all weeks appended (one file per season)
                └── 2025/
                    └── remainders_2025_w{week}.parquet      # unresolved players; empty = clean join
    │       └── nflreadpy/
    │           └── nfl_stats_2025.parquet  # 18,539 rows × 121 cols, weeks 1-18
            └── sleeper/
                └── sleeper_2025/
                    └── ... # matchup and transaction parquet files for each week of the 2025 season
    ├── shared/                     # league detection, config loaders
    ├── transforms/ # one Python script per join/transform
        └── join_nfl_sleeper_weekly.py # ✅ built
    ├── config.example.py
    └── requirements.txt
```

---

## Data Layer

### Concept

Two storage patterns:

- **cache/** - current state only. Overwritten on every refresh. Use for data where only "right now" matters (roster state, injury status, current odds, current projections).
- **snapshots/** - time-series, append-only. Each refresh adds a new record without overwriting prior ones. Use for data where trend history matters (weekly stats, market values over time).

## I/O Architecture

All reads from and writes to the data layer (cache/, snapshots/) 
must go through application/data/data_layer.py. This is a 
non-negotiable architectural rule.

**What this means in practice:**
- Transform scripts import data_layer and call its functions — 
  they do not construct file paths or call polars read/write directly
- Dashboard components read via data_layer functions only
- Any new data entity requires a read and write function added 
  to data_layer.py before the consuming script is written

**data_layer.py organization:**
- Organized by data entity with a comment header per section
- Read and write functions for the same entity live together
- Section header naming matches the corresponding transform 
  script name (e.g. # --- Join: NFL + Sleeper Weekly ---)

**What never belongs in a transform or dashboard script:**
- pathlib.Path construction pointing at snapshots/ or cache/
- pl.read_parquet() or df.write_parquet() called directly
- Hardcoded file path strings

### Current source assignments

| Source | Storage | Rationale |
|---|---|---|
- external
| Sleeper | cache/ + snapshots/ | Matchup/roster/transaction state to snapshots/ (weekly history); player registry to cache/ (current state only, refreshed ≤ once/day) |
| nflreadpy | snapshots/ only | Weekly player stats - trend visualization requires history |
| LeagueLogs | snapshots/ only | Daily market-value snapshot of all profiles (redraft + dynasty). API serves only "now" (no history endpoint), so the value time-series exists only if we snapshot it. Keyed on sleeperPlayerId. |
| Odds API | cache/ only | Current week lines only needed for v1 |
| FantasyPros | cache/ only | Current projections and news only needed for v1 |

- internal
| nfl_sleeper_weekly_joined transform | snapshots/nfl_sleeper_weekly_joined/ | Joined output — one file per season (season_{season}.parquet), each week appended with a (season, week) dedup guard

These assignments reflect current v1 decisions, not permanent rules. Future versions may snapshot additional sources (e.g., odds history for post-hoc analysis).

Cache files do not currently track fetch timestamp. Add a metadata.json sidecar file to each cache write before in-season use.

Data sources are subject to change.

### Player ID join

Each data source uses a different player identifier. The canonical join key for this project is `sleeperPlayerId`.

- nflreadpy uses `gsis_id`
- LeagueLogs uses `sleeperPlayerId` natively
- FantasyPros uses `fantasypros_id`

Use nflreadpy's `import_ids()` to maintain a mapping table at `application/data/cache/player_id_map.parquet`. Refresh this mapping on every nflreadpy fetch run.

nfl_stats_{year}.parquet already includes sleeper_player_id as a column — this join is performed during the fetch step in nfl_stats.py. Transform scripts that read from the nflreadpy snapshot do not need to re-join via player_id_map.parquet.

---

## Fetchers

One script per data source in `application/data/fetchers/`. Each fetcher has a single concern - one source, one cache file, one snapshot stream where applicable.

Current fetcher state:
- `sleeper.py` - backfills + refresh modes
- `odds.py` - does not exist
- `fantasypros.py` - does not exist
- `weather.py` - does not exist
- `nfl_stats.py` - backfill + refresh modes, polars, player ID map
- `leaguelogs.py` - built; daily market-value snapshots (all profiles), scheduled by launchd at 4am ET

## nflreadpy Notes

Package version: 0.1.5
Key functions: load_player_stats(), load_snap_counts(),
load_team_stats(), load_ff_playerids()
All functions return polars DataFrames
player_id in load_player_stats() is gsis_id format ("00-0023459")
Snap count join path: load_snap_counts().pfr_player_id →
load_ff_playerids().pfr_id → gsis_id
Join coverage on nfl_sleeper_weekly_joined targets 100% of rostered skill-position players per week. The join is left-joined from Sleeper (authoritative), so players without nflreadpy stats that week (injured, inactive) appear with 0-stat rows rather than being dropped. The audit step resolves any remaining unknowns via the Sleeper player registry.

## sleeper.py Notes

Player IDs are strings (e.g. "2307") throughout - never cast to int. This is the sleeperPlayerId join key.
Offseason-safe week logic: season_type == "offseason" returns 18 completed weeks, not 0. season_type == "pre" is the only state that returns 0.
Cache files are JSON (league/user/roster state) or parquet (players registry). Snapshot files are parquet partitioned by season: snapshots/sleeper/<year>/
league_resolver.py is the only file that touches SLEEPER_USERNAME. The fetcher accepts league_id as a parameter only.
refresh() current-week snapshot writes will silently skip with an explicit log message during offseason - this is expected behavior.

players_points in matchup snapshots is stored as a serialized JSON string (map of sleeperPlayerId → points). Parse with json.loads before joining. Same applies to starters (JSON array of starter IDs).

fetch_players() caches the full Sleeper /players/nfl endpoint to cache/sleeper/players.parquet. Skips the network call if the cache is less than 24 hours old; pass force=True to override. Called automatically by refresh() and by audit_join.py when the cache is stale or missing. Can also be triggered standalone: python fetchers/sleeper.py fetch-players. Position values in this endpoint use Sleeper's internal codes: QB/RB/WR/TE for skill, K for kicker, DEF for defense.

## leaguelogs.py Notes

`snapshot` pulls every profile (discovered dynamically from /v1/market — the API contract is additive) and appends to snapshots/leaguelogs/market_values.parquet via data_layer.write_leaguelogs_market_snapshot(), idempotent with dedup on snapshot_date. `profiles` lists the current profile keys. Read history via data_layer.read_leaguelogs_market().

Dynasty profiles include rookie-pick rows (synthetic ids like "PICK#2026#01"), flattened into pick_* columns with is_pick=true. Redraft profiles have players only.

Market value is a black-box signal (methodology not published) — use for ranking/trend, not as ground truth. Mandatory attribution: any UI displaying the data must show "Powered by LeagueLogs API" (https://leaguelogs.com).

Scheduler: launchd agent `com.fantasyai.leaguelogs-snapshot` runs `snapshot` daily at 04:00 America/New_York. Canonical plist + README are tracked in application/data/fetchers/scheduler/; the live copy lives at ~/Library/LaunchAgents/. **Gotcha:** launchd cannot open log files inside ~/Documents (TCC-protected) → it fails with EX_CONFIG/78 and empty logs. Logs therefore live at ~/Library/Logs/fantasy-ai/. The launchd-spawned python can still read/write parquet under ~/Documents — only the log-file open is blocked, so no Full Disk Access is needed. This applies to any future launchd job in this repo.

---

## Transforms

One script per join in `application/data/transforms/`. Each transform reads 
via data_layer.py, performs a single join, and writes via data_layer.py.

- `join_nfl_sleeper_weekly.py` — joins nflreadpy weekly stats + Sleeper matchup data on sleeperPlayerId. Sleeper is the authoritative left table — all rostered skill-position players appear in the output regardless of whether nflreadpy has stats for them that week. DSTs are stripped at parse time; kickers are removed by the SKILL_POSITIONS filter after the join. Inactive/injured players appear with 0-stat rows. Appends the week's rows to the single season_{season}.parquet (replacing any existing rows for that (season, week) combo) and writes a remainders file. Calls audit_join automatically on completion. Accepts --season and --week as required CLI args.

- `audit_join.py` — audits and repairs the weekly join output for unresolved players. Reads the remainders file, checks the Sleeper player registry (refreshing it if stale), classifies each remainder as skill (appended to joined file with 0 stats), K/DEF (confirmed and discarded), or truly unknown (left in remainders for manual review). Idempotent — safe to re-run. Called automatically by join_nfl_sleeper_weekly.py; can also be run standalone with --season and --week args.

## Technical Principles

These do not change without an explicit architectural decision:

1. **polars only** - no pandas anywhere in the codebase, use polars until the project advances to a SQL backend
2. **One fetcher per source** - no combined fetchers
3. **The data layer is shared** - dashboard and AI advisor read from the same cache/snapshots; no parallel data paths
4. **Separation of concerns** - focus scripts around a single action, i.e. analysis scripts never read from cache or snapshots directly. All data access goes through dedicated read functions. These are the only code that knows where data lives or what format it's in.
5. **Pre-filter data before any API call** - do not send the LLM more context than it needs (cost control)
6. **The strategy doc is markdown** - not vector-embedded; rules must be auditable and human-readable
7. **Single source of truth per fact** - constitution docs hold current state; never duplicate across docs
8. **Skill positions only in V1** — QB, RB, WR, TE. DST and K are explicitly out of scope until a future version. Do not write V1 code that attempts to handle them.