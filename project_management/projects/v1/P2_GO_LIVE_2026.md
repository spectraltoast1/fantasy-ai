# Project 2 — Go Live on the 2026 Season

**Created:** 2026-07-26 · **Status:** Not started · **Track:** Critical spine — **the long pole** · **Depends on:** P0 (keyed reads), P1 (collection) · **Est:** 4–6 sessions

> **What this project does:** un-freeze the app from its 2025-Week-4 replay and make it run on **live 2026
> data**. Two big pieces — **build the 2026 preseason substrate** (so the engine has something to reason
> from) and **wire an in-season weekly refresh** (so the data advances week by week) — plus surfacing the
> **honest projection band** and converting the **market read from cross-time POC to a live read**. When
> this is done, a connected 2026 league shows correct current-week reality and everything it shows is true.

---

## Context — what "frozen" means today, and what has to change

- The entire served dataset is a **snapshot of the 2025 season replayed to Week 4.** The `as_of_week` seam
  exists and "widens as weeks append," so the *analytics* extend forward automatically — but nothing
  *drives* a weekly refresh, and there's **no 2026 substrate at all.**
- Loads today are a full **DROP+CREATE** reload (`build_db.py --load`). There is **no incremental, per-league,
  in-season update path** — that's the single biggest thing to build here, and the riskiest change.
- **Good news the docs establish:** the engine's tuned constants are **season-invariant** (fit on
  2020–2025 residual shape, certified out-of-sample). So 2026 is a **substrate *build*, not a re-tune** —
  this is the manual, one-season version of what `annual-retune.md` (in `../post-v1/`) later automates — and note they are *not* the same job: annual-retune re-tunes constants *after* a season resolves; P2 builds the 2026 substrate *forward* to predict. Half-PPR is
  already engine-ready; the work is running the existing builders for the new season.

## The mental model (so the sessions don't sprawl)

Two independent tracks that meet at the loader:
1. **Substrate (offline, once):** run the existing `build_substrate` chain for **2026** on ppr + half. This
   is deterministic and can run the day 2026 preseason projections/ADP exist.
2. **Live cadence (the new machinery):** a weekly job that pulls each connected league's current Sleeper
   state + nflreadpy stats, runs the spine transforms, and **incrementally loads** the new week — advancing
   `as_of_week` — without a full DROP+CREATE.

## Session map

| Session | Goal | Scope | Definition of done |
|---|---|---|---|
| **S1 — Build the 2026 preseason substrate** | Give the engine a 2026 basis (ppr + half) | Fetch 2026 preseason ADP; run `build_substrate` for 2026 → `adp_points_curve`, `projection_consensus`, `ros_player_band` for ppr + half; gate with the existing `backtest_*` checks | `derived/scoring/{ppr,half}/` has 2026 consensus + band; gates green; a 2026 player resolves a sane band |
| **S2 — Weekly refresh pipeline (the core)** | Data advances week by week, per league | Orchestrate fetch (Sleeper rosters/matchups/transactions, `nfl_stats` weekly, Sleeper projections) → `join_nfl_sleeper_weekly` → spine transforms → **incremental load**, advancing `as_of_week`; make it idempotent + re-runnable per league | Running the weekly job for a league moves it to the current week with correct rosters/standings/matchups; re-running is a no-op; **not** a full DROP+CREATE |
| **S3 — Surface honest engine + live market** | What the user sees is true | Verify the front-end renders the **honest 8c band** for 2026 (automatic once substrate is built under current constants — confirm the display path); re-point `compute_market_vor` to **contemporaneous 2026** values (2026 rosters × 2026 market) and drop `is_cross_time` | 2026 band renders honest; `market_vor` computes non-cross-time for a live league *(display of the market panel is gated per the build-order designation — the plumbing lives here)* |
| **S4 — Preseason / early-season readiness** | Weeks 0–3 degrade gracefully | Verify the `readiness.jsx` regimes (structural / point-in-time / trend + a "too early" fallback) handle a league with 0–3 weeks of 2026 data; decide how **week 0 (preseason, no games)** renders | An empty/early 2026 league shows sensible "too early" states rather than broken or overconfident panels |

## Decisions to settle (surface to Will on the fork)

- **Incremental-load strategy** — upsert new rows vs. a scoped per-league reload of just that league's
  slice. (Recommend per-league scoped reload keyed on `league_id` — simplest safe unit; avoids upsert
  complexity while staying incremental at the league grain.)
- **Refresh trigger + cadence** — CI weekly (Tue/Wed after stat corrections settle) vs. on-demand. Reuse the
  P1 hosted scheduler.
- **2026 data availability/lag** — confirm nflreadpy and Sleeper serve 2026 weekly data on the cadence you
  need before relying on it; have a fallback if a source lags.
- **SF shape in the substrate** — confirm the substrate build covers the superflex roster shape (scoring is
  unchanged; the shape affects VOR/optimal-lineup, not the scoring-scoped band).

## Risks / can't-generalize

- **The DROP+CREATE → incremental change is the single riskiest change in the whole V1** — it touches the
  production loader. Apply a parity guard: an incremental load of a league must match a full reload of that
  league byte-for-byte on already-loaded weeks.
- **No actuals in preseason** — week 0 has projections but no realized points; several reads are "too early"
  by design. Don't fabricate signal; lean on the readiness gates.
- **Source lag** — stat corrections land over a few days; pick a refresh time that trades freshness for
  stability.
- **Market read still needs P1 reliable** — a live trade lean is only as good as the daily collection under
  it.

## Critical files

`transforms/build_substrate.py`, `compute_projection_consensus.py`, `compute_ros_player_band.py`,
`fetchers/adp.py` (2026 board), `join_nfl_sleeper_weekly.py`, `corpus/compute_spine.py` (per-league spine),
**`data/serve/build_db.py`** (the incremental-load change), `compute_market_vor.py`,
`frontend/src/readiness.jsx`, and the new weekly-refresh orchestrator.

## Definition of done (project)

A connected 2026 league shows correct current-week rosters, standings, matchups, honest projection bands,
and a live (non-POC) market read; the weekly refresh advances it cleanly and idempotently; and early-season
thinness degrades gracefully. **This is what makes the product "useful to the 2026 season" rather than a
replay — everything downstream (waiver, AI outlook, self-serve) assumes it.**
