# Technical Architecture

> Engineering context document for Claude Code. Describes the stack, folder structure, data layer design, and technical principles. Updated regularly as the project evolves.

**Last reviewed:** 2026-05-17

---

## Project Summary

A fantasy football analytics dashboard (v1) and AI advisor (v2+). V1 is a pure analytics dashboard - no AI component. The data layer is shared between the dashboard and the future AI advisor. All fetchers write to a common data layer that both halves read from.

---

## Tech Stack

- **Language:** Python end-to-end
- **Data manipulation:** polars (not pandas) - nflreadpy returns polars DataFrames; use polars syntax throughout
- **NFL stats:** nflreadpy (successor to deprecated nfl_data_py) - returns polars DataFrames
- **Dashboard:** Dash + Plotly (not yet built)
- **Storage:** JSON (cache), parquet (snapshots), JSONL (advisor log - future)
- **HTTP:** requests library
- **Future query layer:** DuckDB (v2+, not in scope for v1)

---

## Version Roadmap (subject to change)
- **V1** — Team overview, league standings, matchup review (no AI)
- **V2** — Waiver wire analysis (requires Sleeper full player database fetcher)
- **V3** — Start/sit recommendations (requires FantasyPros projections fetcher)
- **V4** — Trade analysis (requires LeagueLogs player valuation)
- **V5** — AI-powered insights (major update, builds on complete data layer)
- **V6+** — More complex analytics (TBD)

## Known Scope Exclusions
**DST/K (V1):** Excluded from all V1 transforms and dashboard work. The nflreadpy → Sleeper ID join has ~85.5% coverage; DST/K are the primary gap. All joins and visualizations should assume skill positions only: QB, RB, WR, TE. Do not attempt to handle DST/K in V1 code — skip or drop non-joining rows at the join stage.

**Waiver wire / full player pool (V1):** The current Sleeper fetcher captures rostered players only. Full player pool analysis is V2 scope. When built, the Sleeper full player database fetch will be a separate fetcher (sleeper_players.py) per the separation of concerns principle — one concern per script, once-daily cadence.

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
├── _deprecated/                    # old flat fetchers, do not modify
├── _deferred/                      # synthesis pipeline, parked for v2
└── application/
    ├── dashboard/                  # Dash app (not yet built)
    ├── data/
    │   ├── fetchers/               # one Python script per source (tracked in git)
    │   │   └── nfl_stats.py        # ✅ built
            └── sleeper.py          # ✅ built
    │   ├── cache/                  # current state (gitignored)
    │   │   └── player_id_map.parquet  # gsis_id → sleeperPlayerId mapping
    │   └── snapshots/              # time-series parquet (gitignored)
    │       └── nflreadpy/
    │           └── nfl_stats_2025.parquet  # 18,539 rows × 121 cols, weeks 1-18
    ├── shared/                     # league detection, config loaders
    ├── config.example.py
    └── requirements.txt
```

Note: The codebase is currently flat (pre-reorg). The structure above is the target state. Do not move existing files - leave them where they are. Write new files to the target locations above. Do not modify files in _deprecated/.

---

## Data Layer

### Concept

Two storage patterns:

- **cache/** - current state only. Overwritten on every refresh. Use for data where only "right now" matters (roster state, injury status, current odds, current projections).
- **snapshots/** - time-series, append-only. Each refresh adds a new record without overwriting prior ones. Use for data where trend history matters (weekly stats, market values over time).

### Current source assignments

| Source | Storage | Rationale |
|---|---|---|
| Sleeper | cache/ only | Roster/matchup/injury state - current week only needed |
| nflreadpy | snapshots/ only | Weekly player stats - trend visualization requires history |
| LeagueLogs | cache/ + snapshots/ | Current values to cache; snapshot weekly for trend derivation (trend fields are stubbed at zero in the API) |
| Odds API | cache/ only | Current week lines only needed for v1 |
| FantasyPros | cache/ only | Current projections and news only needed for v1 |

These assignments reflect current v1 decisions, not permanent rules. Future versions may snapshot additional sources (e.g., odds history for post-hoc analysis).

Cache files do not currently track fetch timestamp. Add a metadata.json sidecar file to each cache write before in-season use.

Data sources are subject to change.

### Player ID join

Each data source uses a different player identifier. The canonical join key for this project is `sleeperPlayerId`.

- nflreadpy uses `gsis_id`
- LeagueLogs uses `sleeperPlayerId` natively
- FantasyPros uses `fantasypros_id`

Use nflreadpy's `import_ids()` to maintain a mapping table at `application/data/cache/player_id_map.parquet`. Refresh this mapping on every nflreadpy fetch run.

---

## Fetchers

One script per data source in `application/data/fetchers/`. Each fetcher has a single concern - one source, one cache file, one snapshot stream where applicable.

Current fetcher state:
- `sleeper.py` - backfills + refresh modes
- `odds.py` - does not exist
- `fantasypros.py` - does not exist
- `weather.py` - does not exist
- `nfl_stats.py` - backfill + refresh modes, polars, player ID map
- `leaguelogs.py` - does not exist yet

## nflreadpy Notes

Package version: 0.1.5
Key functions: load_player_stats(), load_snap_counts(),
load_team_stats(), load_ff_playerids()
All functions return polars DataFrames
player_id in load_player_stats() is gsis_id format ("00-0023459")
Snap count join path: load_snap_counts().pfr_player_id →
load_ff_playerids().pfr_id → gsis_id
85.5% sleeper ID join coverage expected (DST/K lack Sleeper mappings)

## sleeper.py Notes

Player IDs are strings (e.g. "2307") throughout - never cast to int. This is the sleeperPlayerId join key.
Offseason-safe week logic: season_type == "offseason" returns 18 completed weeks, not 0. season_type == "pre" is the only state that returns 0.
Cache files are JSON. Snapshot files are parquet partitioned by season: snapshots/sleeper/<year>/
league_resolver.py is the only file that touches SLEEPER_USERNAME. The fetcher accepts league_id as a parameter only.
refresh() current-week snapshot writes will silently skip with an explicit log message during offseason - this is expected behavior.

---

## Technical Principles

These do not change without an explicit architectural decision:

1. **polars only** - no pandas anywhere in the codebase
2. **One fetcher per source** - no combined fetchers
3. **The data layer is shared** - dashboard and AI advisor read from the same cache/snapshots; no parallel data paths
4. **Pre-filter data before any API call** - do not send the LLM more context than it needs (cost control)
5. **The strategy doc is markdown** - not vector-embedded; rules must be auditable and human-readable
6. **Single source of truth per fact** - constitution docs hold current state; never duplicate across docs
7. **Skill positions only in V1** — QB, RB, WR, TE. DST and K are explicitly out of scope until a future version. Do not write V1 code that attempts to handle them.