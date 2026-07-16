# Store Migration + Multi-League/Season/Week — Architecture & Migration Plan

**Last reviewed:** 2026-07-15 · **Status:** Scope / design doc — records the target architecture and the
ordered migration. Not yet started.

> **Decisions locked:** (1) migrate the data store from in-browser **DuckDB-WASM** to a **server-side
> SQLite + HTTP API**; (2) do that **store migration first** (single-league), then build
> multi-league/season on top of the new architecture.
>
> **Origin:** produced from an inspection of the current single-league frontend, data layer, and publish
> seam (2026-07-15). Supersedes the "V3+: multi-league support" line in
> `../core docs/PROJECT_OVERVIEW.md` with a concrete architecture.

---

## Context

**Why:** The frontend (`application/frontend/`, React + DuckDB-WASM) renders exactly **one league, one
season (2025), frozen at ~4 weeks**. The user wants to **click through ~10 leagues (a mix of their own +
others) across whatever years each league ran**, reading each as a fully-featured view — a stand-in for a
future product where a user authenticates, enters their Sleeper username, imports their leagues, and jumps
between any loaded league/season. Auth + the import UX are **out of scope**; this plan builds the
machinery and a ~10-league seeded demo.

**Corrected mental model (important):** today there is **no runtime frontend→backend query**. DuckDB runs
*in the browser*; it fetches static `.parquet` files (Vite serves `public/data/`) and runs SQL locally.
The Python/polars "backend" is a **build-time pipeline** that produces those parquet files, hand-symlinked
into `public/data/`. The seam between front and back is **files**, not an API. The "missing orchestrator"
I flagged is an **offline batch driver** to *generate* analytics for more slices — unrelated to any live
query path.

**The two findings that drive this plan:**
1. **The store is being migrated to server-side SQLite + API anyway**, and that seam (`db.js`, the publish
   step, the SQL dialect) is the *same* seam multi-league touches. So we migrate the store first, then
   build multi-league on it — where "switch league" becomes an API parameter / SQL filter, not a
   per-slice file swap.
2. **The analytics the UI renders exist for only one slice.** Raw joins exist for all 271 leagues, but
   the *derived* reads are complete only for the 2025 "mine" league. Corpus leagues have just the thin
   5-read spine; the narrative/market reads (`market_vor`, `manager_features`/`manager_dossiers`,
   `ros_league_view`, `ros_synthesis`) are **descoped from the corpus** (see
   `application/data/corpus/compute_spine.py`). Even the user's **2024** league has raw data but an
   **empty `derived/league/1132400260048977920/`**. This **backend content work is store-agnostic** and
   required regardless — it produces the derived data that the SQLite loader ingests.

---

## As-is architecture

| Layer | Today |
|---|---|
| **Frontend data access** | `queries.js` (~1037 lines of **DuckDB SQL** run in-browser) + `db.js` (DuckDB-WASM init: `fetch(parquet)` → `registerFileBuffer` under year-stripped aliases). Panels call loaders like `loadPlayers(asOfWeek)`. |
| **Transport** | Static file hosting. No server. League identity carried by the **symlink path**; `MY_USERNAME='spectraltoast1'` (`queries.js:20`) is the "you" seam. |
| **Publish** | **Hand-made symlinks** in `public/data/` (one league_id + year baked into each target). No script. |
| **Compute** | Python/polars transforms (`application/data/transforms/*`, `application/ai/*`), all `--season`-parameterized with optional `league_id=` defaulting to `_active_league(season)`. Storage already partitioned `derived/league/<id>/` and `derived/scoring/<key>/`. `compute_spine.py` batches the 5-read spine across 221 leagues. |

**Dimension status:** Week = ✅ already parameterized (`asOfWeek` → `queries.js` filters; `WeekSwitcher`
`App.jsx:214`). Season = ⚠️ hardcoded in `db.js` filenames but `queries.js` is season-agnostic via
aliases. League = ❌ no representation at all.

---

## To-be architecture (server-side SQLite + API)

```
┌──────────────┐   HTTP/JSON    ┌───────────────────────────┐   SQL    ┌──────────────┐
│  React app   │ ─────────────► │  API server (FastAPI)     │ ───────► │  SQLite DB   │
│ queries.js = │ ◄───────────── │  read endpoints + shaping │ ◄─────── │ (served store)│
│  API client  │                └───────────────────────────┘          └──────▲───────┘
└──────────────┘                                                               │ load
                                        build-time                    ┌────────┴────────┐
                                                                      │ compute pipeline│
                                                                      │ (polars → parquet│
                                                                      │  → SQLite loader)│
                                                                      └─────────────────┘
```

**Component roles:**
- **API server** — new `application/api/` (recommend **FastAPI + uvicorn**; Flask is a lighter
  alternative — a swappable execution-time choice). Owns the read endpoints; runs SQL against SQLite;
  performs the shaping/post-processing that currently lives in JS. Designed **auth-ready**: endpoints are
  structured so a later user/session layer can scope results to the logged-in user, but for the demo they
  serve the seeded leagues without auth. `viewer_roster_id` stands in for "the logged-in user's roster."
- **SQLite DB** — the **serving store** (gitignored, lives in `application/data/`, like the parquet
  today). Tables mirror the derived parquet schemas, indexed on filter columns (`as_of_week`, `week`,
  `roster_id`, `sleeper_player_id`, and — after Stage B — `league_id`, `season`).
- **SQLite loader** — new backend step that reads the derived parquet (compute-pipeline output) and writes
  SQLite tables. This **replaces the hand-symlink publish step**.
- **Frontend `queries.js`** — becomes a thin **API client**: each loader does `fetch('/api/…')` and
  returns the same-shaped object it does today, so **the panels (`Players.jsx`, `Teams.jsx`, …) are
  unchanged**. `db.js`/DuckDB-WASM is **removed**.

**Where the query logic goes (biggest Stage-A task):** the DuckDB SQL in `queries.js` moves **server-side
to SQLite SQL**, and the JS post-processing (`optimalLineup`/`expandSlots` `:994`, `normalCdf`/`erf`
`:1027`) moves to Python. Recommended: **port the SQL** (keeps the battle-tested query shape; apply a
SQLite-dialect pass). *Execution-time options to weigh:* (a) re-express reads in **polars** over SQLite —
aligns with the project's "polars + data_layer" non-negotiables but is a full rewrite; (b) as a
risk-reducer, run the existing SQL via **server-side DuckDB attached to the SQLite file** first, then swap
the dialect later — decouples "go client-server" from "change SQL dialect."

**Why multi-league gets *simpler* here:** with a SQLite store, all slices live in **one DB keyed by
`league_id`/`season`/`week`**. "Switch league" = an API parameter → a `WHERE league_id=? AND season=?`
filter. No per-slice files, no catalog.json-as-static-asset, no in-browser re-registration. The "catalog"
becomes a `GET /api/leagues` **endpoint** computed from the DB.

**League = a lineage across seasons:** redraft leagues get a **new `league_id` each season** (only dynasty
keeps one), so "the years a league ran" means following `previous_league_id` chains (in
`corpus_discovery.parquet`). `/api/leagues` groups per-season `league_id`s under a stable **lineage id** so
the Season selector shows all years and `(lineage, season)` resolves to the concrete `league_id`.

**Viewer identity as data:** replace `MY_USERNAME` with a per-slice `viewer_roster_id` from
`/api/leagues`; switch `isMe`/`myRosterId` in `queries.js`/server from `owner_name==MY_USERNAME` to
`roster_id==viewer_roster_id`. `null` → league-neutral mode (personal panels hide via `readiness.jsx`).

---

## Migration plan — two stages, backend-first

### STAGE A — Store migration (single-league; DuckDB-WASM → server SQLite + API)
Goal: identical single-league app, new architecture. Ship before touching multi-league.

- **A1 — API server skeleton + SQLite schema.** Scaffold `application/api/` (FastAPI + uvicorn). Define
  SQLite tables mirroring the 13 derived datasets for the current slice; indexes on `as_of_week`/`week`/
  `roster_id`/`sleeper_player_id`. Health endpoint + dev run target.
- **A2 — SQLite loader (new publish seam).** New backend step (e.g.
  `application/data/serve/build_sqlite.py`) reads the derived parquet for the current slice and writes the
  SQLite tables. Replaces the hand symlinks. (DuckDB `COPY`/sqlite extension or polars→sqlite.)
- **A3 — Port reads to server endpoints.** Move each `queries.js` loader's SQL to a FastAPI endpoint
  running SQLite SQL; move JS post-processing (optimal lineup, CDF) to Python. Endpoints:
  `/api/players`, `/api/players/{id}`, `/api/standings`, `/api/league`, `/api/teams/{rosterId}`,
  `/api/managers/{rosterId}`, `/api/weeks`, `/api/league-meta`, `/api/matchups`,
  `/api/matchups/{matchupId}` — each taking `as_of_week`. Apply the SQLite-dialect pass (window frames,
  `QUALIFY`→subquery, date fns).
- **A4 — Frontend becomes an API client.** Rewrite `queries.js` loaders as `fetch('/api/…')` returning the
  same shapes; **delete `db.js`/DuckDB-WASM** and its deps. Add a Vite dev proxy for `/api/*` → uvicorn;
  update `.claude/launch.json` to run **both** the API server and the Vite frontend.
- **A5 — Parity verification.** Confirm the single-league app is behaviorally identical to today
  (see Verification).

### STAGE B — Multi-league / multi-season on the new architecture
Goal: ~10 fully-browsable leagues across their years. Several sub-parts are store-agnostic and can start
during Stage A.

- **B0 — Demo selection + models (start during A).** Pick ~10 lineages from `corpus_manifest.parquet` /
  `leagues.parquet` with variety across `scoring_key`, `shape_key`, and **season span** (via
  `previous_league_id` chains); include the user's 2024+2025 lineage. Record `(lineage → {season:
  league_id})`, a `viewer_roster_id` per slice, and names (from `corpus_discovery.name`). Add a `demo`
  cohort + `viewer_roster_id` to `leagues.parquet`.
- **B1 — Backend correctness (store-agnostic).** **Fix `schedule` to be league-scoped** — today
  `export_schedule.py` writes `derived/schedule_<season>.parquet` (league-agnostic) but it holds
  league-specific `roster_id`/`matchup_id`; two same-season leagues collide. Carry `league_id` on the
  schedule (and confirm every derived dataset carries `league_id`+`season` so the SQLite loader can key
  them).
- **B2 — Full-set compute for demo slices (store-agnostic; heaviest).** New batch driver
  `application/data/corpus/compute_demo_slices.py`, modeled on `compute_spine.py` (idempotent, resumable,
  per-league isolation). Per `(league_id, season)` in dependency order: (1) scoring-keyed substrate once
  per `scoring_key`×`season` (`compute_adp_points_curve`, `compute_projection_consensus`,
  `compute_ros_player_band` — see `build_substrate.py`); (2) spine (reuse
  `compute_spine._compute_league`); (3) narrative/market (`compute_market_vor`, `compute_ros_league_view`,
  `compute_manager_features`); (4) AI (`ai/write_manager_dossiers`, `ai/write_ros_synthesis`). Validate
  with `check_spine`, `check_market_vor`, `check_manager_dossiers`, `check_ros_synthesis`.
- **B3 — Load all slices + catalog endpoint.** Extend the SQLite loader to ingest all demo slices with
  `league_id`+`season` columns. Add `GET /api/leagues` returning lineages → seasons →
  `{league_id, weeks_available, viewer_roster_id, panels}` (see contract below), grouped by
  `previous_league_id` lineage.
- **B4 — Parameterize the API.** Every read endpoint gains `league_id`+`season` (path
  `/api/leagues/{leagueId}/{season}/players?as_of_week=N` or query params). Server SQL filters on them.
- **B5 — Frontend selectors + identity.** Add `league`+`season` global state in `App.jsx` beside
  `asOfWeek`; turn `LeagueSwitcher` (`App.jsx:196`) into a real dropdown; add `SeasonSwitcher` (mirror
  `WeekSwitcher`). On league change → resolve seasons → default → reload → reset week (`/api/weeks`) → set
  viewer. `queries.js` API client passes `league_id`/`season` through. Per-slice `viewer_roster_id`
  replaces `MY_USERNAME`; extend `readiness.jsx` to gate panels flagged unavailable (`panels` map);
  remove cross-time POC copy (`PlayerCard.jsx:72`, `Players.jsx:70`, `TeamDetail.jsx:122`,
  `League.jsx:259`).
- **B6 — End-to-end verification** across every league × season × sample weeks.

---

## `/api/leagues` response contract (B3 deliverable)

```jsonc
{
  "leagues": [
    {
      "lineage_id": "lorp",
      "name": "League of Random People 2.0",
      "shape_key": "10t-1qb-redraft", "scoring_key": "ppr",
      "seasons": [
        { "season": 2025, "league_id": "1182101676608823296",
          "weeks_available": [1,2,3,4], "viewer_roster_id": 7,
          "panels": { "market": true,  "manager": true, "ros_synthesis": true } },
        { "season": 2024, "league_id": "1132400260048977920",
          "weeks_available": [1,"…",15], "viewer_roster_id": 7,
          "panels": { "market": false, "manager": true, "ros_synthesis": false } }
      ]
    }
    // …~10 lineages
  ]
}
```

---

## Risks / can't-fully-generalize (decide at execution)

- **`market_vor`** needs a market-value source (`leaguelogs/market_values.parquet`, keyed on
  `sleeperPlayerId` + a market season). The 2025 slice uses a **2026 cross-time** POC; historical seasons
  have no contemporaneous market. Options: anchor on `adp_preseason.parquet` (all seasons), or mark
  `market_vor` absent and gate the market/trade panels (`panels.market=false`).
- **`ros_synthesis`** is an AI news read, sparse, 2026-only; it does **not** generalize historically.
  Recommend gating it off (`panels.ros_synthesis=false`) rather than fabricating it.
- **AI reads** (`manager_dossiers`, `ros_synthesis`) cost API calls/time for ~10 slices — budget in B2.
- **SQL dialect port** (A3) is the largest single risk; the DuckDB-attached-SQLite intermediate (above)
  is the hedge.

---

## Critical files

**Create**
- `application/api/` — FastAPI app: `main.py` + route modules mirroring the loaders (A1/A3; params in B4).
- `application/data/serve/build_sqlite.py` — parquet → SQLite loader / new publish seam (A2; multi-slice
  in B3).
- `application/data/corpus/compute_demo_slices.py` — full-set batch driver (B2; models `compute_spine.py`).

**Modify — backend**
- `application/data/transforms/export_schedule.py` + `data_layer.py` — league-scope `schedule` (B1).
- `application/data/data_layer.py` — SQLite/serve helpers; `demo` cohort + `viewer_roster_id` on
  `leagues.parquet` (B0); ensure `league_id`+`season` on all derived reads.
- `application/data/transforms/compute_market_vor.py` (+ `check_market_vor.py`) — historical strategy, if
  chosen (B2).

**Modify — frontend**
- `application/frontend/src/queries.js` — rewrite loaders as API client; drop DuckDB SQL; `MY_USERNAME`
  (`:20`) → per-slice `viewer_roster_id` (A4/B5).
- **Delete** `application/frontend/src/db.js` (DuckDB-WASM) + remove the dependency (A4).
- `application/frontend/src/App.jsx` — league/season state; `LeagueSwitcher` dropdown (`:196`); new
  `SeasonSwitcher` (mirror `WeekSwitcher` `:214`); slice-switch orchestration; loading state (B5).
- `application/frontend/src/readiness.jsx` — gate panels by the `panels` map (B5).
- `PlayerCard.jsx`, `Players.jsx`, `TeamDetail.jsx`, `League.jsx` — remove cross-time POC copy (B5).
- `application/frontend/vite.config.*` + `.claude/launch.json` — dev proxy `/api/*`; run API + frontend
  together (A4).

---

## Verification

**Stage A parity (A5):** run API (uvicorn) + frontend via `preview_start` (worktree launch.json; run
`worktree-setup.sh` first). For each surface (players/teams/league/matchups + drilldowns) at a couple of
weeks, confirm the rendered data matches today's DuckDB-WASM output (spot-check a handful of numbers).
`read_network_requests` should show `/api/*` JSON (200s); `read_console_messages` clean; `db.js`/parquet
fetches gone.

**Stage B (B6):** hit `/api/leagues`; confirm selectors populate all ~10 lineages with correct season
spans. Click through **every league × each season × sample weeks**; per slice check `read_page` renders,
`read_network_requests`/`read_console_messages` for API errors, identity highlights the
`viewer_roster_id`, and absent-analytics slices **gate** market/ROS panels instead of breaking.
`screenshot` two contrasting slices (user's 15-week 2024 vs a 12-team SF corpus league) as proof.

---

## Session / commit sequencing

This is a **program of ~8–12 sessions** (3-commit cap each): fresh worktree → `worktree-setup.sh` → phase
→ update `STATUS.md` → `worktree-close.sh --merge`. Order: **Stage A first (A1→A5), each phase
independently shippable**, then Stage B (B0/B1/B2 store-agnostic and parallelizable → B3→B4→B5→B6). Do not
start Stage B's frontend selectors (B5) until the API is parameterized (B4). The backend content compute
(B2) can run in parallel with Stage A since it only produces derived parquet the loader later ingests.
