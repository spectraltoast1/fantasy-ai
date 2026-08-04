# ARCHITECTURE

**What this is:** the current technical design of fantasy-ai — the system **as it is today**. History lives
in `sessions/` and `_deprecated/`; deep mechanism rationale lives in `context/appendices/`. The rules for
*changing* code are in `CODING_BIBLE.md`.
**Updated:** 2026-07-31

---

## Stack

- **Backend** — a FastAPI **read** API (`application/api/`: `routes.py` · `reads.py` · `calcs.py` ·
  `projections.py`) over **Supabase-hosted Postgres** (`DATABASE_URL`).
- **Frontend** — React + Vite SPA (`application/frontend/`): Players, Teams, League, Matchups, Manager
  Dossier.
- **Auth** — **Supabase Auth**, magic link, invite-only (P5/S1). The API verifies the caller's access token
  (ES256) against the project's published JWKS; the SPA holds only the **publishable** key.
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
- **Load** — `application/data/serve/build_db.py` loads the derived parquet into Postgres. Two paths: a
  whole-DB **DROP+CREATE `--load`** (the full rebuild + the parity oracle's baseline), and a **per-league
  scoped reload** (`load_league` / `--reload-league`) — delete + re-COPY one league in a single transaction,
  others + the `demo_manifest` catalog untouched, proven byte-parity-identical to the full load
  (`serve/check_scoped_reload.py`). The scoped path is the in-season incremental unit.
- **In-season refresh (P2/S2)** — `serve/weekly_refresh.py` advances one league to the current week:
  fetch (Sleeper current state + weekly nfl_stats + projections) → `join_nfl_sleeper_weekly` → rebuild the
  scoring-keyed `ros_player_band` (P2/S3b — so it advances *with* `production_vor` instead of drifting behind
  it; skipped below `FIRST_HONEST_BAND_SEASON`) → recompute the spine → `build_db.load_league`.
  Idempotent; live (`--live`, from Sleeper `/state/nfl`) or replay (`--week`).
  The serve seam (`reads._as_of_slice` → `max(as_of_week)` per league) then surfaces the new week with no app
  change. Cadence: `.github/workflows/weekly_refresh.yml` (needs a `DATABASE_URL` repo secret to activate).

## The store (Postgres)

**14 tables + a `demo_manifest` catalog**, every row keyed `league_id` / `season` and indexed on its filter
columns: `season` (player×week), `teams`, `lineup_slots`, `league_settings`, `player_signal`,
`production_vor`, `market_vor`, `ros_synthesis`, `bracket_odds`, `positional_depth`, `manager_dossiers`,
`projection_consensus`, `ros_player_band`, `schedule`. The last two are **scoring-keyed** — NFL-global
substrate shared by every league on the same profile, stamped with each slice's `league_id` at COPY. The
engine-improvement **ledger** (predictions / outcomes / resolutions / scorecard) is deliberately **not** in
the served store — it's the tuning/validation spine. → *see appendix: store-schema, engine-improvement-loop.*

**Plus two auth tables, outside all of that on purpose (P5/S1, S1b).** `serve/schema.sql` is *generated* by
`--emit` and applied by `--load`, which DROPs every table it names — so `app_users` and `signup_attempts`
live in hand-written `api/auth_schema.sql` instead, and `init_auth_schema.py --verify` asserts they stay
absent from the generated DDL. → *see appendix: auth.*

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
via the `slice_params` dependency, defaulting to the owner's league (a 404 guards an unknown `league_id`);
`/api/leagues` is the one unscoped catalog read.

**Two non-read endpoints.** `/api/me` takes the `auth.current_user` dependency and returns the verified
caller (401 on a missing/forged/expired token, 503 when the JWKS can't be reached — denied either way, but
an outage stays distinguishable from a bad credential). **`POST /api/signup`** is the one *unauthenticated
write*: it validates the access code, creates the account and sends a magic link, rate-limited by IP and
email against `public.signup_attempts`. Every read is deliberately still **open**: authentication without
per-user scoping is a half-gate, so closing and scoping the reads is one change with one proof, and that is
P5/S2.

**Two gates, two questions.** `readiness.jsx` answers *"is there enough data yet"* (`Gate` + the `BANDS`
ladder, keyed to **`weeksOfData`** — weeks with real RESULTS as of the viewed week, from `/api/weeks`'s
`played`; loaded-but-unplayed weeks don't count, which is what preseason looks like). `marketOn` /
`MarketOff` / `PanelOff` answer *"is this read meaningful for this league"* — catalog gating, per-element
because it hides a column or half a toggle. `Gate` no longer carries a catalog arm; no call site ever used it.

**Panel gating.** `/api/leagues` carries a per-slice `panels` map the SPA gates on (`readiness.jsx`:
`Gate`/`PanelOff`/`marketOn`). `manager` and `ros_synthesis` mirror `demo_manifest` directly. **`market` does
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
  and the SPA has league + season selectors (from `/api/leagues`) that switch across the 12 demo lineages.
- **Viewer identity** — `viewer_roster_id` (per league, from the catalog) is the "you" seam; a request with no
  `viewer_roster_id` falls back to `MY_USERNAME`'s roster (the default). The `MY_USERNAME` Fly secret stays as
  that default resolver.
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
- **Per-user isolation — NOT yet.** Every read except `/api/me` is still open, and the app still connects as
  one owner-role Postgres connection that bypasses RLS. RLS is deny-by-default on every public table and the
  unused Data API is disabled — defense-in-depth, not authz. Scoping each read to its owner is **P5/S2**, in
  the API layer, not an RLS-policy build. → `projects/v1/` (P5).

## Scope & rules

Skill positions only (QB / RB / WR / TE); DST and K are out. V1 target is redraft, PPR/half, 1QB or
superflex. The design laws and engineering principles that govern all code live in **`CODING_BIBLE.md`**.
