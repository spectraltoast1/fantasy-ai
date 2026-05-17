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
- **Dashboard:** Streamlit + Altair (not yet built)
- **Storage:** JSON (cache), parquet (snapshots), JSONL (advisor log - future)
- **HTTP:** requests library
- **Future query layer:** DuckDB (v2+, not in scope for v1)

---

## Folder Structure

```
fantasy-ai/
├── STATUS.md
├── project_management/
│   ├── TECHNICAL_ARCHITECTURE.md   (this file)
│   ├── data_sources.txt
│   └── journal/
├── application/
    ├── ai/                    # advisor + context + prompts (future)
    ├── dashboard/             # Streamlit app (not yet built)
    ├── data/
    │   ├── fetchers/          # one Python script per data source (tracked in git)
    │   ├── cache/             # current state JSON (gitignored)
    │   ├── snapshots/         # time-series parquet (gitignored)
    │   └── advisor_log/       # JSONL advisor call log (future, gitignored)
    ├── strategy/              # strategy_redraft.md (future)
    ├── shared/                # league detection, config loaders
    ├── scheduler.py
    ├── config.example.py
    └── requirements.txt
```

Note: The codebase is currently flat (pre-reorg). The structure above is the target state. Do not move existing files - leave them where they are. Write new files to the target locations above.

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
- `sleeper.py` - most complete, consider the working baseline
- `odds.py`, `fantasypros.py` - exist but untested, treat as stubs to be rebuilt
- `weather.py` - NWS forecast is stubbed; stadium location data may be worth preserving
- `nfl_stats.py` - built on deprecated nfl_data_py; to be replaced with nflreadpy fetcher
- `leaguelogs.py` - does not exist yet

Do not modify existing fetcher files. Write new fetchers to `application/data/fetchers/`.

---

## Technical Principles

These do not change without an explicit architectural decision:

1. **polars only** - no pandas anywhere in the codebase
2. **One fetcher per source** - no combined fetchers
3. **The data layer is shared** - dashboard and AI advisor read from the same cache/snapshots; no parallel data paths
4. **Pre-filter data before any API call** - do not send the LLM more context than it needs (cost control)
5. **The strategy doc is markdown** - not vector-embedded; rules must be auditable and human-readable
6. **Single source of truth per fact** - constitution docs hold current state; never duplicate across docs