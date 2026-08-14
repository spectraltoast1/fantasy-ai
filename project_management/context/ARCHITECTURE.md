# ARCHITECTURE

**What this is:** the current technical design of fantasy-ai — the system **as it is today**. History lives
in `sessions/` and `_deprecated/`; deep mechanism rationale lives in `context/appendices/`. The rules for
*changing* code are in `CODING_BIBLE.md`.
**Updated:** 2026-08-10

---

## Stack

- **Backend** — a FastAPI **read** API (`application/api/`: `routes.py` · `reads.py` · `calcs.py` ·
  `projections.py`) over **Supabase-hosted Postgres** (`DATABASE_URL`).
- **Frontend** — React + Vite SPA (`application/frontend/`): Players, Teams, League, Matchups, Manager
  Dossier.
- **Auth** — **Supabase Auth**, magic link, invite-only (P5/S1). The API verifies the caller's access token
  (ES256) against the project's published JWKS; the SPA holds only the **publishable** key.
- **Hosting — two Fly.io apps, `iad`, deliberately separate.** `fantasy-ai-api` serves the built SPA at
  `/` and `/api` on the **same origin** (no CORS) from a multi-stage image; scale-to-zero. Live at
  https://surplusff.com/ (also `fantasy-ai-api.fly.dev`).
  **`fantasy-ai-worker` (P5/S3)** runs the pipeline off-laptop: 1 GB `shared-cpu-1x` + a **1 GB volume**
  mounted at `application/data/snapshots`, its own `Dockerfile.worker` (the pipeline deps, not the API's)
  and no `http_service` — a job box, driven by `fly ssh console` until S4's queue. Separate because
  entangling the API's scale-to-zero with a multi-minute job is the failure the ADR forbids. A Fly volume
  attaches to exactly one machine and is host-pinned, so the worker is a **stateful singleton, not a
  pool** — intended for an invited cohort; the recorded exit is the Supabase bucket backend.
  → *see appendix: store-boundary.*
- **The store boundary (P5/S3)** — **one writer: the authoring laptop; every other machine reads.**
  `STORE_ROLE=worker` makes `data_layer` refuse the 16 laptop-owned writers (an allow-list, so anything
  unclassified refuses by default) and makes the shared ROS band **verify** rather than rebuild. It is
  set on the Fly worker and the GitHub Actions runner. This is why the worker's volume can be treated as
  a disposable cache: it can never author anything the laptop owns. → *see appendix: store-boundary.*
- **Data / compute** — **polars only** (no pandas); numpy for the Monte-Carlo simulation; nflreadpy for NFL
  stats; `math.erf` for the normal CDF.
- **Analytics** — GA4 (`G-J1F0BE5ZW4`): the gtag tag in the SPA's single `index.html`, with
  `src/analytics.js` the only module that touches `window.gtag` (views call `pageView`/`track`).
  Write-only telemetry — **not** a data seam, and every call no-ops when the tag is blocked.
  *Installed 2026-08-10.* → *see appendix: analytics.*

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
- **Load** — `application/data/serve/build_db.py` loads the derived parquet into Postgres. Two paths: a
  whole-DB **DROP+CREATE `--load`** (the full rebuild + the parity oracle's baseline), and a **per-league
  scoped reload** (`load_league` / `--reload-league`) — delete + re-COPY one league in a single transaction,
  others + the `league_catalog` untouched, proven byte-parity-identical to the full load
  (`serve/check_scoped_reload.py`). The scoped path is the in-season incremental unit.
- **In-season refresh (P2/S2)** — `serve/weekly_refresh.py` advances one league to the current week:
  fetch (Sleeper current state + weekly nfl_stats + projections) → `join_nfl_sleeper_weekly` → rebuild the
  scoring-keyed `ros_player_band` (P2/S3b — so it advances *with* `production_vor` instead of drifting behind
  it; skipped below `FIRST_HONEST_BAND_SEASON`) → recompute the spine → `build_db.load_league`.
  Idempotent; live (`--live`, from Sleeper `/state/nfl`) or replay (`--week`).
  The serve seam (`reads._as_of_slice` → `max(as_of_week)` per league) then surfaces the new week with no app
  change. Cadence: `.github/workflows/weekly_refresh.yml` (needs a `DATABASE_URL` repo secret to activate).

## The store (Postgres)

**14 tables + the `league_catalog`** (renamed from `demo_manifest` in S2d), all 15 carrying RLS emitted
by `--emit`, every row keyed `league_id` / `season` and indexed on its filter
columns: `season` (player×week), `teams`, `lineup_slots`, `league_settings`, `player_signal`,
`production_vor`, `market_vor`, `ros_synthesis`, `bracket_odds`, `positional_depth`, `manager_dossiers`,
`projection_consensus`, `ros_player_band`, `schedule`. The last two are **scoring-keyed** — NFL-global
substrate shared by every league on the same profile, stamped with each slice's `league_id` at COPY. The
engine-improvement **ledger** (predictions / outcomes / resolutions / scorecard) is deliberately **not** in
the served store — it's the tuning/validation spine. → *see appendix: store-schema, engine-improvement-loop.*

**Plus three app-side tables, outside all of that on purpose (P5/S1, S1b, S2a).** `serve/schema.sql` is
*generated* by `--emit` and applied by `--load`, which DROPs every table it names — so `app_users`,
`signup_attempts` and `user_leagues` live in hand-written `api/auth_schema.sql` instead, and
`init_auth_schema.py --verify` asserts they stay absent from the generated DDL, that the FKs to
`auth.users` really carry `ON DELETE CASCADE`, and that no grant outlives its account. (A fourth,
`nfl_state_cache`, was retired in S2c with the Sleeper call it cached.) → *see appendix: auth.*

**The honest-band boundary.** `ros_player_band` is served only from `build_db.FIRST_HONEST_BAND_SEASON`
(2026) onward. Below it the band belongs to the **frozen corpus** — built at pre-8c `CENTER_SHRINK=1.0` and
the artifact the immutable L2 ledger was derived from — so those files are never loaded and never rebuilt
(`_honest_band_path` returns a deliberately-absent path; the weekly refresh guards on the same constant).
The table therefore holds 0 rows until a 2026 league is onboarded. Lowering that constant is a corpus
re-backfill — the annual pipeline's job.

## Read endpoints

`/health` · `/health/db` · `/api/weeks` · `/api/league-meta` · `/api/players` · `/api/players/{id}` ·
`/api/standings` · `/api/teams/{id}` · `/api/managers/{id}` · `/api/league` · `/api/positional-talent` ·
`/api/matchups` · `/api/matchups/{id}` · `/api/leagues` (catalog) · `/api/me` (identity) ·
`POST /api/signup`. **Read-only apart from those two** — there is no data write/ingest surface.
Every read takes an optional `?league_id=`(+`?season=`+`?viewer_roster_id=`)
via the `slice_params` dependency, **defaulting to `DEMO_LEAGUE_ID`** as of P5/S2a — previously it fell
through `MY_USERNAME` to whichever league the owner's Sleeper credentials named, which made an anonymous
visitor land on Will's real league by accident of name resolution rather than by decision. Same league today;
the point is that it is now the *configured public* one. As of **P5/S2b that dependency also authorizes**:
it takes `auth.optional_user` and applies the visibility predicate, so every read inherits it from one place
and none repeats it. The loaders no longer default a missing `league_id` to anything — they raise, because a
silent default inside a function whose authorization happens elsewhere is how the hole reopens.

**Two non-read endpoints.** `/api/me` takes the `auth.current_user` dependency and returns the verified
caller (401 on a missing/forged/expired token, 503 when the JWKS can't be reached — denied either way, but
an outage stays distinguishable from a bad credential). **`POST /api/signup`** is the one *unauthenticated
write*: it validates the access code, creates the account and sends a magic link, rate-limited by IP and
email against `public.signup_attempts`. **`/api/leagues` takes `auth.optional_user`** (P5/S2a) — no
`Authorization` header is *anonymous*, a present-but-invalid token is *401*, an unreachable verifier is
*503*; degrading a bad token to anonymous would make a broken verifier, a botched key rotation and a forged
token all look like an ordinary visit. The eleven per-panel reads are deliberately still **open**; scoping
them is P5/S2b.

**Two gates, two questions.** `readiness.jsx` answers *"is there enough data yet"* (`Gate` + the `BANDS`
ladder, keyed to **`weeksOfData`** — weeks with real RESULTS as of the viewed week, from `/api/weeks`'s
`played`; loaded-but-unplayed weeks don't count, which is what preseason looks like). `marketOn` /
`MarketOff` / `PanelOff` answer *"is this read meaningful for this league"* — catalog gating, per-element
because it hides a column or half a toggle. `Gate` no longer carries a catalog arm; no call site ever used it.

**Panel gating.** `/api/leagues` carries a per-slice `panels` map the SPA gates on (`readiness.jsx`:
`Gate`/`PanelOff`/`marketOn`). `manager` and `ros_synthesis` mirror `league_catalog` directly. **`market` does
not**: it is the manifest's *structural* flag (does this slice have a `market_vor` read at all — kept
structural because `build_db._ref()` selects its schema-reference league by it) **AND the read's own
`is_cross_time`** (`reads._market_panel`). A cross-time read prices today's market against a past season's
rosters, so all four market surfaces gate off rather than render a POC as a live call; a contemporaneous
league flips the flag and the panels return with no code change.

## Scoring

`scoring_key` ∈ {`ppr`, `half`, `std`, `cust-…`} **classifies the reception tier only** — two same-key
leagues can still score ~10% of player-weeks differently (bonuses / INT / first-down points). *Realized*
points arrive pre-scored from Sleeper (`sleeper_points`); the *projected* center is scored at the consumption
layer by the dispatcher (`transforms/_scoring.py`), so one set of projections serves any league.
Scoring-scoped substrate (`projection_consensus`, `ros_player_band`) is shared per key. A **forward
(preseason) season** with no actuals yet sources its positional residual prior from residuals **pooled over
prior seasons** (`compute_projection_consensus._pooled_residuals`) — every player takes the `<2-residual`
fallback, so the band is the honest, wide, position-typical prior until games sharpen it; gated by
`check_forward_substrate`. → *see appendix: scoring-mechanism.*

## Multi-league / multi-user (current state)

- **Multi-league** — live: the store is fully keyed, every read is parameterized on `league_id`(+`season`),
  and the SPA has **league + week** selectors (the league one from `/api/leagues`). The 31 corpus slices all
  remain in the database as engineering fixtures; since S2a the **public catalog** is one league. **The
  catalog payload is FLAT since S2e** — one entry per visible (league, season), season on the row. The
  lineage→seasons tree existed only to feed a **season selector, which is gone**: prior seasons are corpus,
  not product. It loses nothing, because `visible` already admits at most one season per lineage (a lineage
  is one league across years; the owned term requires `season == current`, the demo term names one
  `league_id`). `season` is still carried on every request — inert, never a SQL filter.
- **Ownership + visibility — live (P5/S2a).** Visibility is one predicate, in one function
  (`reads.visible`): `visible(league) = (league_id == DEMO_LEAGUE_ID) OR (owned by caller AND season ==
  current)`. Ownership is `public.user_leagues` (`user_id` × `league_id`, cascading off `auth.users`), written
  today by `scripts/users.py --grant` and by S4's connect flow later. **`DEMO_LEAGUE_ID` is config, not a
  table** — one public league makes a table pure overhead, and repointing the demo at the anonymized clone
  stays one line — and S2d used it: it now points at **`DEMO-2025`, a generated clone**, not at Will's
  real league. **"Current season" is derived locally** (`settings.current_season`, S2c): the calendar
  year, or the year before it until **August 1** — a boundary that deliberately *leads* Sleeper's own flip,
  because flipping early drops last season's league from a catalog slightly sooner than necessary while
  flipping late hides a league somebody has just connected. It is pure, total and does no I/O, so nothing
  on a read path can be slow or fail; `CURRENT_SEASON` is the documented manual lever, process-env-only.
  Sleeper is an **assertion, not a dependency** — `check_ownership` asks `/v1/state/nfl` once and fails
  loudly on disagreement. `/health` publishes the resolved season *and its source*, so an override left set
  cannot hide. The demo is the deliberate season-independent exception, which is why the demo term is
  evaluated first and separately — as a global `season = current` filter the demo would vanish and read as
  an auth bug.
  The catalog orders **a caller's own leagues first, the demo last** — the SPA lands on `leagues[0]`, so that
  ordering *is* the landing rule.
- **Viewer identity** — `viewer_roster_id` (per league, from the catalog) is the "you" seam; a request with no
  `viewer_roster_id` falls back to `MY_USERNAME`'s roster. The `MY_USERNAME` Fly secret stays as that
  resolver **and only that** — it is no longer how the default *league* is chosen. Moving viewer identity from
  a league property to a user × league property is still P5/S2b.
- **Auth — live, identity only (P5/S1 + S1b).** Supabase Auth, **magic link**, **self-serve signup behind a
  shared access code**. Platform signup is OFF, so there is no public path to account creation except
  `POST /api/signup`, which validates the code **server-side** and then does the admin create + send itself —
  zero per-user work, and un-bypassable, because the SPA's publishable key is public by design and anything
  checked in the client can be called around. The code is required on **every** request from everyone, which
  makes *no valid code → no email ever sent* a property rather than a policy. `auth.current_user` verifies
  the access token (ES256) against the project's JWKS; the SPA attaches the bearer token in one place
  (`queries.js`); a `public.app_users` row is written on first authenticated call. Keys are Supabase's
  current **publishable/secret** pair — and the secret key now lives in the deployed environment, since the
  API performs admin calls. **Custom SMTP is a hard dependency**: the built-in sender refuses any address
  that isn't a project team member. → *see appendix: auth.*
- **Per-user isolation — closed, discovery and access (S2a + S2b).** The catalog is scoped, so you cannot
  *find* another user's league; and **all eleven per-panel reads inherit the predicate**, so knowing a
  `league_id` is no longer enough to *read* one. One seam: `routes.slice_params` (the FastAPI adapter) over
  `reads.authorize_slice` (pure, injectable, so the isolation matrix runs from fixtures). Existence + season
  come from `teams`, **not** the catalog — catalog membership used to double as the authorization
  boundary, which held only while the manifest happened to contain exactly the demo set.
  **An unowned league is byte-identical to a nonexistent one** (same status, body and headers; the 404 detail
  is a constant that interpolates nothing) because a 403 — or any response that varies — confirms existence,
  and Sleeper ids are guessable. A misconfigured demo or a league with two seasons raises **503** instead, so
  a deploy failure is never dressed as a caller problem. `viewer_roster_id` is validated against the league,
  strictly *after* the visibility decision, or it would answer "is roster N in league X" for invisible
  leagues. `/api` responses carry `Vary: Authorization` + `Cache-Control: private, no-store`, since the same
  URL now answers differently per caller. The app still connects as one owner-role Postgres connection that
  bypasses RLS, so RLS stays defense-in-depth, not authz; isolation is API-layer by decision.
  → `projects/v1/` (P5).

## Scope & rules

Skill positions only (QB / RB / WR / TE); DST and K are out. V1 target is redraft, PPR/half, 1QB or
superflex. The design laws and engineering principles that govern all code live in **`CODING_BIBLE.md`**.
