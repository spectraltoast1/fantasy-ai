# V1 · P2 · Session S3 — Retire the cross-time market honestly — REPORT

**Shipped:** 2026-07-30 · **Branch:** `claude/p2-s3-action-plan-3fe8c8` · **Commits:** 3 · **Status:** DONE —
market half shipped + redeployed; **band half cut on a finding and re-scoped as S3b.** **Next:** P2/S3b
(surface the honest band), then S4. Brief: `SESSION_P2_S3_SURFACE_HONEST_BAND.md`.

## Headline

The demo no longer shows a cross-time number as if it were a live trade call. The gate is **the read's own
`is_cross_time`**, not a hardcoded season — so a live 2026 league turns the panels back on by itself.

**And the session's other output is a finding: the brief's band half rested on a false premise.** Surfacing
the honest band is not a rebuild — it is net-new plumbing. Cut, scoped, and captured as S3b (below) on Will's
call rather than reinterpreted into something smaller.

## The finding — the honest band has no wire to the screen

The brief's Part 1 was "rebuild the stale 2020–2025 band + reload → the app renders the honest band."
Exploration found that would have changed **nothing a user sees**:

- The 8c dials — `CENTER_SHRINK=0.8`, `BULL_Z=0.524`, `BEAR_Z=2.5`, `ANCHOR_W=0` — all govern the
  **ROS-horizon** band in `ros_player_band` / `production_vor._ros_values`. `ros_player_band` is **not in
  `build_db.DATASETS`**, has no Postgres table, and is selected by **zero** endpoints. The one table that
  carries band columns (`ros_synthesis`) is empty in prod, `panels_ros=false` on all 31 slices.
- What the UI calls a band — MatchupDetail "Score Range · 25–75" — is `projection_consensus.p25/p50/p75`,
  governed by `BAND_Z=0.55` + `SKEW_GAIN=1.5`. Both were **deliberately held** through 8c. Not stale: out of
  scope for the honest-engine ship.
- Matchup μ / `proj` is `Σ center_ppr` read straight from `projection_consensus` by `projections.py`,
  **bypassing `_ros_values`** — so `CENTER_SHRINK` never touches any projected-points figure in the UI.
- The front end does **no** band math (verified: no z, no sigma, no shrink anywhere in `frontend/src`). The
  "front-end renders the older band" line in STATUS was a data statement, and an incomplete one.

**Will's call:** cut the band half entirely (an invisible rebuild only earns its keep bundled with the wire),
and do **not** apply `CENTER_SHRINK` to the weekly serve path — that is an unmeasured engine change, not a
display fix, so it stays a tuner question under propose-only.

## What shipped

**1 · The gate is the read's own honesty** (`api/reads._market_panel`, commit `cc6b255`).
`panels.market` = the manifest's structural flag **AND** `NOT is_cross_time`, sourced from one grouped query
over `market_vor`. `demo_manifest.panels_market` stays **structural** on purpose — `build_db._ref()` picks its
`--emit` schema-reference league via `is_mine & panels_market` and `compute_demo_slices` existence-checks it,
so flipping the column would have broken the loader, not just the UI. A slice with the flag but no rows gates
off; NULL provenance counts as cross-time (unknown never gates *on*).

**2 · The gate script stopped assuming one time-world** (`check_market_vor.py`, same commit). Verdict 5 used
to hard-fail unless **every** row was cross-time — it would have gone red the day the read went live. It now
asserts the invariant that holds in both worlds: `is_cross_time == (market_season != season)` per row, plus
one time-world per slice (a half-fused frame is exactly the silent fusion the column exists to prevent).
`--expect` pins the mode; `--prove-bites` shows the predicates catch a flipped flag, a half-fused frame and a
mis-pinned mode — **and that a same-season frame passes as `contemporaneous`.** That last one is the
contemporaneous-ready proof, and it needed no 2026 league (there is none to compute against —
`_active_league(2026)` raises).

**3 · All four market surfaces gate, not one** (commit `3b39a4e`). Only League→Positional Talent honoured
`panels.market`. Players' MKT column, team detail's PROD/MKT toggle and the player card's market sparkline +
BUY/SELL lean rendered regardless — and `TeamDetail` was *already being handed* `panels` and silently
dropping it (never destructured). `readiness.jsx` gained the exported `PanelOff`, a shared `MarketOff` +
`MARKET_OFF_NOTE` (one home for the copy, four surfaces), and `marketOn(panels)`. This also activated
`Gate`'s catalog path, which was dead code — no call site had ever passed `panel`/`panels`.

On the player card the market sparkline and the trade lean **gate together**: they are the same
Production−Market gap wearing two coats, and a BUY/SELL call off a cross-time gap would be the least honest
thing on the card.

## Verified

- `check_market_vor --prove-bites`: every new predicate bites; the same-season frame passes as
  contemporaneous. Verdicts 2/3/4 and the rest of 5 green.
- `/api/leagues`: the is_mine 2025 slice went **`market: true` → `false`**; 0 of 31 slices market-on. The
  manifest column is **still `true`** — confirmed by direct query, so the honesty AND did the work.
- Browser, local then **prod after `fly deploy`**: League→Positional Talent, Players (MKT column and legend
  gone, sort falls back to PROD), player card (market trend + lean replaced by the note), team detail
  (`.td-toggle` = `["PROD VOR"]`). Console clean, all `/api` 200s.
- **Parity:** Matchups' "Score Range · 25–75" and every non-market surface unchanged; switching to another
  league renders normally. No data change and no reload, so the store is untouched by construction.

**Also changed (deliberately): the other 30 slices.** They previously rendered an MKT column of em-dashes and
a market sparkline with no series. An empty column is still a claim — the surface is now absent.

## Two open things this surfaced (both logged in STATUS)

- **`check_market_vor`'s recompute-match verdict is RED, pre-existing.** `market_vor` has **no cadence** —
  nothing recomputes it, yet `load_league` re-publishes it on every scoped reload. It trails the raw series by
  13 days *and* is priced against `as_of_week` 4 while S2 advanced the league to 5. The gate now prints both
  causes instead of a bare "height mismatch". Not fixed here: refreshing numbers behind a panel we are
  switching off would have added a derived-store write to a session that otherwise touches no data.
- **`concurrently` (a declared devDependency) was missing** from the shared `node_modules`, so `dev:full`
  couldn't start. Fixed with `npm install` from the lockfile in main.

## Handoff to S3b

Rebuild 2020–2025 under the honest constants, load `ros_player_band` into Postgres scoring-keyed (the
`projection_consensus` pattern), select it in `load_player_card`, and render a deterministic
**"Rest-of-season range"** (bear/center/bull + `ros_cv`). It **adds** a surface — it does not fill the player
card's existing empty state, which is the AI `ros_synthesis` read (P4), a different object. Fix the
`CENTER_SHRINK` store drift in the same session: `production_vor.ros_value` is exactly `0.8 ×` the same-week
`ros_center`, and every weekly refresh re-creates it.
