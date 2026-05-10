# Technical Architecture

> How the system works. Constitution document — refer here for tech stack, runtime mechanics, data layer design, and the technical principles that should not change without explicit reason.

**Last reviewed:** 2026-05-09

---

## System Diagram

```
DATA LAYER (shared between AI and Dashboard)
─────────────────────────────────────────────────────────────────
  Sleeper API     ─┐
  nfl_data_py     ─┤
  The Odds API    ─┼──▶  fetchers/  ──▶  cache/      (current state, overwritten)
  FantasyPros API ─┤                ──▶  snapshots/  (time-series, append-only)
  NWS (forecast)  ─┘


AI HALF
─────────────────────────────────────────────────────────────────
                    strategy_redraft.md  ───┐
                                             ├──▶  Advisor (Sonnet API call)
  data/cache + data/snapshots ───────────────┤      pre-filtered context
                                             │      structured output
  user question ─────────────────────────────┘      logs to advisor_log/


DASHBOARD HALF
─────────────────────────────────────────────────────────────────
  data/cache + data/snapshots + data/advisor_log  ──▶  Streamlit + Altair panels
                                                        - Roster status
                                                        - Last week's matchup
                                                        - Market value trends
                                                        - Recent advisor outputs
                                                        - One analytical view
```

The data layer is the contract between the two halves. The AI doesn't read directly from APIs at advisor-call time; it reads from cache/snapshots. The dashboard reads the same files. The scheduler keeps the data layer fresh on a configured cadence.

---

## Tech Stack

### Language: Python end-to-end

- Claude Code is materially better at Python than R
- Anthropic SDK is Python-first
- Async API calls to multiple data sources favor Python's asyncio
- Splitting languages = worst of both worlds

### Storage: JSON files; DuckDB only when needed

- Strategy doc: plain markdown
- Cached API responses: JSON (current cache) + parquet (time-series snapshots, when they get bigger)
- Advisor log: JSONL (one line per call, append-only)
- DuckDB if SQL queries against accumulated history get useful — pip-installable, no server, reads parquet/JSON directly. Skip SQLite/Postgres.

### Data Fetching

- `requests` for the simple REST calls (current code uses this; async is overkill for a single-user system)
- `nfl_data_py` for nflverse data
- For nflverse datasets not yet exposed in nfl_data_py, download Parquet directly from `github.com/nflverse/nflverse-data/releases`

### Claude API: `anthropic` SDK

- **Sonnet** for advisor calls (currently `claude-sonnet-4-6`)
- **Opus** held in reserve for high-judgment work (e.g., specialized advisors with rich strategy context)
- **Haiku** held in reserve for high-frequency or low-stakes calls

### Dashboard

- **Streamlit** — lowest setup cost, decent default aesthetics, matches "limited interactive" goal
- **Altair** — declarative grammar of graphics, ggplot-quality aesthetics in Python
- **Plotly** for charts that need richer interactivity if Altair runs out
- **Custom theme via `config.toml`**

---

## Project Layout

### Current state (flat, pre-reorg)

```
fantasy-ai/
├── STATUS.md
├── project_management/        # constitution docs + journal (this file lives here)
├── application/               # currently flat — code reorg pending
│   ├── advisor.py             # AI entry point (prototype, evolves toward Phase 3 spec)
│   ├── context.py             # context assembly
│   ├── sleeper.py             # data fetcher
│   ├── nfl_stats.py           # data fetcher
│   ├── odds.py                # data fetcher
│   ├── fantasypros.py         # data fetcher
│   ├── weather.py             # stadium lookup + NWS forecast stub
│   ├── leagues.py             # league type detection + strategy doc loader
│   ├── scheduler.py           # cron-style data refresh
│   ├── config.example.py      # config.py is gitignored
│   └── data/                  # cache + (eventually) snapshots + advisor_log (gitignored)
└── _deferred/
    └── synthesis_pipeline/    # frozen v2 work, see its README
```

### Target state (post-reorg)

```
fantasy-ai/
├── STATUS.md
├── project_management/
└── application/
    ├── ai/                    # advisor + context + prompts
    ├── dashboard/             # Streamlit app
    ├── data/
    │   ├── fetchers/          # sleeper.py, nfl_stats.py, odds.py, fantasypros.py, weather.py
    │   ├── cache/             # current state JSON, gitignored
    │   ├── snapshots/         # time-series parquet, gitignored
    │   └── advisor_log/       # JSONL, gitignored
    ├── strategy/              # strategy_redraft.md, eventually strategy_dynasty.md, etc.
    ├── shared/                # leagues.py, common config loaders
    ├── scheduler.py           # stays at top level
    ├── config.example.py
    └── requirements.txt
```

The structural reorg (file moves + import updates) is on the open-questions list in `PRODUCT_ROADMAP.md`. Until executed, the docs reference the target layout while the code remains flat.

---

## Data Sources

Full reference: `data_sources.txt`

| Source | Role | Auth | Notes |
|---|---|---|---|
| LeagueLogs | Market values, blurbs, NFL state | None | Skill positions only; trend fields stubbed at zero — derive locally from snapshots |
| Sleeper | League/roster/matchups, projections | None | Currently the primary fetcher — works |
| nfl_data_py | Production stats, snap %, target share, NGS, EPA | None | Python interface to nflverse |
| The Odds API | Vegas lines (free) + player props (paid) | API key | 500 credits/mo budget |
| FantasyPros | Projections + news | API key | Plan-dependent |
| NFL official | Practice participation, inactives | None | Not currently fetched |
| NWS | Weather forecast | None | Stub exists; integration TBD |
| datawithbliss | Stadium location only | None | Used for stadium lat/lng + roof type. Historical-weather portion was dropped. |

**Known data gaps:**
- Coverage tendencies (man/zone) — PFF only, not in v1 stack
- Weather forecast — NWS integration is a stub in `weather.py`
- K/DEF — minimal coverage by design

---

## The AI Advisor — Implementation Pattern (Phase 3 target)

```
1. User asks a typed question (start/sit is the v1 advisor type)
2. Python loads the appropriate strategy doc via shared/leagues.py
3. Python pre-filters strategy rules by relevance to the question type
4. Python pre-filters data context to what the question needs
   (e.g., start/sit only needs the two players in question + matchup + Vegas + injury)
5. Single Sonnet API call: pre-filtered strategy + pre-filtered data + question
6. Structured response (decision + confidence + rules invoked + data referenced)
7. Log: question, rules invoked, data fetched, output, timestamp → advisor_log/
```

Today, `application/advisor.py` does steps 5-6 only — and it dumps the entire context as JSON instead of pre-filtering. Phase 3 is the work to bring it to spec.

---

## Cost Management Mechanism

**Architectural cost control:** the advisor types are fixed surfaces with predictable token usage. No open-ended chat-style API calls.

**Pre-filtering as cost control:** Python filters strategy rules + data tokens before assembling the API call. Smaller context → smaller cost. The LLM is not paid to parse data it doesn't need.

**Caching:**
- Per-source TTLs documented in `data_sources.txt`
- Time-series snapshots are append-only and serve dashboard trend views
- Advisor outputs are logged with input snapshot, so the dashboard can flag when an old recommendation is stale

**Runtime costs:** TBD; tracked from day one in the advisor log.

---

## Time-Series Snapshots — Why They Exist

The dashboard's market-value-trend chart and any "rising/falling" view requires history. The current fetchers overwrite their cache on each refresh, losing the time dimension. Phase 2 adds:

- `data/snapshots/league_logs/YYYY-MM-DD-HHmm.parquet` (or similar) for LeagueLogs market values, written by the LeagueLogs fetcher
- `data/snapshots/projections/YYYY-WW.parquet` for weekly projection history
- A snapshot retention policy (likely keep all of one season; archive older)

The advisor doesn't need snapshots for v1 — it queries current state. The dashboard does. Snapshots are the data-layer feature that makes the dashboard a peer product rather than a viewer.

---

## Cache Invalidation Pattern

Cached advisor outputs in the dashboard get stale (a Tuesday recommendation is half-stale by Sunday morning when injury news drops).

**Design rule:** every logged advisor call stores its input snapshot, not just its timestamp.

```
Logged Tuesday 9:00 AM
Inputs: Wednesday practice = (not yet observed)
        Vegas total = 47.5
        Weather forecast = clear
[Dashboard surfaces "regenerate?" if any input has materially changed]
```

The user (or the system) detects when conditions have shifted enough to warrant regeneration.

---

## Technical Design Principles

The things that should not change without explicit reason. If you find yourself wanting to change one of these, escalate to a roadmap discussion first.

1. **Pre-filter data deterministically; don't ask the LLM to parse what's important.** This is the cost-management throughline of the entire architecture. The current `advisor.py` violates this and Phase 3 fixes it.
2. **The strategy doc is markdown, not vector-embedded retrieval.** Markdown rules are auditable, editable, and human-readable. RAG would lose this.
3. **The data layer is shared.** AI and Dashboard read from the same fetchers + caches + snapshots. Avoid building parallel data paths.
4. **Each fetcher has a single concern.** One source, one cache file, one snapshot stream where applicable.
5. **Reasoning patterns over player names.** Player-specific takes go stale; reasoning patterns transfer across seasons.
6. **Single source of truth per fact.** Constitution docs hold current state. Journals record evolution. Never duplicate.
7. **The dashboard does its own work.** At least one analytical view in the dashboard does not depend on any advisor call.

---

## Deferred Capabilities (See `_deferred/`)

The transcript-synthesis pipeline that was originally intended to produce the strategy doc has been frozen for v1 and preserved at `_deferred/synthesis_pipeline/`. It includes the four pass prompts, the token vocabulary contract, the raw transcripts, intermediate caches, and the v1 truncated strategy MDs. See that folder's README for resume instructions when v2 begins.

The token vocabulary contract is part of that deferred work, not a v1 dependency.

---

## Known Gaps

- **Code reorg not yet done.** Target layout above; current layout still flat.
- **Time-series snapshot code does not exist yet.** Fetchers currently overwrite. Phase 2 work.
- **Advisor output log does not exist yet.** `advisor.py` prints to stdout. Phase 2 work.
- **Pre-filtered context not yet implemented.** Phase 3 work.
- **NWS forecast integration is a stub** in `weather.py`. Implement or drop in Phase 2.
- **Specialized advisor types do not exist.** Phase 3 builds the start/sit one.

## File Inventory

### Constitution docs (rarely change)
- `STATUS.md` (project root) — current state in one paragraph
- `project_management/PROJECT_OVERVIEW.md` — why and what
- `project_management/PRODUCT_ROADMAP.md` — when and phasing
- `project_management/TECHNICAL_ARCHITECTURE.md` — how (this file)
- `project_management/data_sources.txt` — data source reference

### Per-session evolution
- `project_management/journal/INDEX.md`
- `project_management/journal/_TEMPLATE.md`
- `project_management/journal/YYYY-MM-DD-slug.md`

### Application code (flat, pre-reorg)
- See "Current state" above

### Strategy
- `application/strategy/strategy_redraft.md` — to be produced via interview (Phase 1)

### Generated artifacts (gitignored)
- `application/data/cache/*` — current state caches
- `application/data/snapshots/*` — time-series (Phase 2)
- `application/data/advisor_log/*.jsonl` — advisor call log (Phase 2)

### Deferred to v2
- `_deferred/synthesis_pipeline/` — see its README
