# ARCHITECTURE

**What this is:** the current technical design of fantasy-ai — the system **as it is today**. History lives
in `sessions/` and `_deprecated/`; deep mechanism rationale lives in `context/appendices/`. The rules for
*changing* code are in `CODING_BIBLE.md`.
**Updated:** 2026-07-26

---

## Stack

- **Backend** — a FastAPI **read** API (`application/api/`: `routes.py` · `reads.py` · `calcs.py` ·
  `projections.py`) over **Supabase-hosted Postgres** (`DATABASE_URL`).
- **Frontend** — React + Vite SPA (`application/frontend/`): Players, Teams, League, Matchups, Manager
  Dossier.
- **Hosting** — one Fly.io app (`fantasy-ai-api`, region `iad`) serves the built SPA at `/` and `/api` on the
  **same origin** (no CORS) from a multi-stage Docker image. Live at https://fantasy-ai-api.fly.dev/;
  scale-to-zero.
- **Data / compute** — **polars only** (no pandas); numpy for the Monte-Carlo simulation; nflreadpy for NFL
  stats; `math.erf` for the normal CDF.

## The two seams (non-negotiable — enforced by the Coding Bible)

- **`application/data/data_layer.py`** — the only code that knows where data lives; every Python read/write
  routes through it.
- **`application/frontend/src/queries.js`** — the single client-side data seam, now a thin API client
  (`fetch('/api/…')`). View components never touch data access.

## Data flow (build-time batch — no runtime ingestion yet)

```
fetchers → cache/ + snapshots/ → join → derived transforms (parquet) → build_db.py → Postgres → /api → SPA
```

- **Fetchers** (one per source, `application/data/fetchers/`): Sleeper (rosters / matchups / transactions /
  projections), nflreadpy (weekly stats + expected-points components), LeagueLogs (daily market values),
  news RSS (situation news). Sleeper + nflreadpy are pulled on demand; LeagueLogs + news are daily
  collectors. → *see appendix: data-collection.*
- **Join** — `join_nfl_sleeper_weekly.py` produces the authoritative player×week table (Sleeper is the
  authoritative left table).
- **Derived transforms** (`transforms/` + `ai/`) compute the reads. Most are "tall" — one slice per
  `as_of_week` — so the app can replay any week. → *see appendix: engine-decision-reads.*
- **Load** — `application/data/serve/build_db.py` loads the derived parquet into Postgres (a DROP+CREATE full
  reload today).
- **Key limitation:** the pipeline is **build-time and offline** — there is **no runtime / incremental
  in-season refresh** path yet. Building one is a V1 project. → `projects/v1/` (P2).

## The store (Postgres)

**13 tables + a `demo_manifest` catalog**, every row keyed `league_id` / `season` and indexed on its filter
columns: `season` (player×week), `teams`, `lineup_slots`, `league_settings`, `player_signal`,
`production_vor`, `market_vor`, `ros_synthesis`, `bracket_odds`, `positional_depth`, `manager_dossiers`,
`projection_consensus`, `schedule`. The engine-improvement **ledger** (predictions / outcomes / resolutions /
scorecard) is deliberately **not** in the served store — it's the tuning/validation spine. → *see appendix:
store-schema, engine-improvement-loop.*

## Read endpoints

`/health` · `/health/db` · `/api/weeks` · `/api/league-meta` · `/api/players` · `/api/players/{id}` ·
`/api/standings` · `/api/teams/{id}` · `/api/managers/{id}` · `/api/league` · `/api/positional-talent` ·
`/api/matchups` · `/api/matchups/{id}` · `/api/leagues` (catalog). **Read-only** — there is no write/ingest
surface. Every read takes an optional `?league_id=`(+`?season=`+`?viewer_roster_id=`) via the `slice_params`
dependency, defaulting to the owner's league (a 404 guards an unknown `league_id`); `/api/leagues` is the one
unscoped catalog read.

## Scoring

`scoring_key` ∈ {`ppr`, `half`, `std`, `cust-…`} **classifies the reception tier only** — two same-key
leagues can still score ~10% of player-weeks differently (bonuses / INT / first-down points). *Realized*
points arrive pre-scored from Sleeper (`sleeper_points`); the *projected* center is scored at the consumption
layer by the dispatcher (`transforms/_scoring.py`), so one set of projections serves any league.
Scoring-scoped substrate (`projection_consensus`, `ros_player_band`) is shared per key. → *see appendix:
scoring-mechanism.*

## Multi-league / multi-user (current state)

- **Multi-league** — live: the store is fully keyed, every read is parameterized on `league_id`(+`season`),
  and the SPA has league + season selectors (from `/api/leagues`) that switch across the 12 demo lineages.
- **Viewer identity** — `viewer_roster_id` (per league, from the catalog) is the "you" seam; a request with no
  `viewer_roster_id` falls back to `MY_USERNAME`'s roster (the default). The `MY_USERNAME` Fly secret stays as
  that default resolver.
- **Multi-user / auth** — none today: single-tenant, one owner-role Postgres connection, RLS enabled with no
  policies. Postgres was chosen so **Supabase Auth** is a later bolt-on. Adding it is a V1 project. →
  `projects/v1/` (P5).

## Scope & rules

Skill positions only (QB / RB / WR / TE); DST and K are out. V1 target is redraft, PPR/half, 1QB or
superflex. The design laws and engineering principles that govern all code live in **`CODING_BIBLE.md`**.
