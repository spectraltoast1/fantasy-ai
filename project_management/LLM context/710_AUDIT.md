# 710 Audit — Fix Checklist

**Created:** 2026-07-10 · Backend-audit follow-ups to work off **before / alongside the frontend pivot.**

Seven cleanup items surfaced by the 2026-07-10 backend audit. Each is a standalone fix; none
blocks the frontend work. Ordered by the audit's own severity framing (structural → scaling →
spec-completeness → hygiene). Check them off as they land.

> **Progress (2026-07-10 session):** ✅ **#1 (package structure), #5 (config.example),
> #6 (requirements), #7 (bracket figure) are DONE.** #2 (scaling) is a **no-op by design**
> (documented migration trigger — do not hand-optimize the parquet writers). ✅ **#4 (§2 preseason
> anchor) is DONE** — the audit's "blocked on data" verdict was **wrong**: the ADP source
> (`nflreadpy.load_ff_rankings`) was in a library we already depend on the whole time. #3
> (§1 quality axis) remains **deferred** — but its scope is now smaller than the audit assumed:
> `nflreadpy.load_ff_opportunity` already ships the empirical expected-points model, so #3 is a
> consume-and-re-score transform, not a fit-your-own-weights build. Investigation notes are inline below.

---

## Structural

- [x] **No package structure; `sys.path.insert` everywhere.** ✅ **DONE (2026-07-10).** Made
  `application/` a proper package: added `__init__.py` to the 6 dirs + a root `pyproject.toml`,
  converted every bare import to absolute package form (`from application.data import data_layer`
  …), and **deleted all 56 `sys.path.insert` lines across 31 files** (zero remain). Scripts now
  run as `python -m application.<pkg>.<module>` from the repo root; the lazy `_import_manager_helpers`
  is a top-level package import, and the launchd plist runs the fetcher via `-m` with
  `WorkingDirectory` = repo root. Behavior-preserving — all backtest gates pass with identical
  numbers.
  *Where:* [application/data/transforms/](application/data/transforms/) (`*.py`),
  [application/ai/](application/ai/) (`*.py`),
  [application/data/fetchers/sleeper.py](application/data/fetchers/sleeper.py)
  (`_import_manager_helpers`).

## Scaling (bounded today)

- [ ] **Read-modify-write-whole-file append pattern.** ⏸ **NO-OP by design (acknowledged
  2026-07-10).** The audit itself says not to hand-optimize the parquet writers; this is the
  **migration trigger** for the eventual SQLite/warehouse layer, not a fix. Left unchecked as a
  standing signal, intentionally not actioned. Every incremental write reads the entire
  file, filters, concats, and rewrites — O(n²) over a backfill. Fine at current scale (18 weeks, 10
  managers); it's the ceiling on how far the parquet-file approach stretches. The eventual
  SQLite/warehouse layer is the real fix — don't hand-optimize the parquet writers, just know this
  is the migration trigger.
  *Where:* [application/data/data_layer.py](application/data/data_layer.py) —
  `write_join_nfl_sleeper_weekly`, `write_manager_activity`, `write_projections`,
  `write_leaguelogs_market_snapshot`.

## Spec completeness (vs. DECISION_READS)

- [ ] **§1 Quality axis is a TD-proxy, not the spec.** ⏸ **DEFERRED (re-scoped 2026-07-10, session 2).**
  Still a net-new transform, but **smaller than first scoped** — we do **not** need to build a
  per-chance-type PBP-tag store or fit our own multi-season weights. `nflreadpy.load_ff_opportunity`
  (already a dependency; `player_id` = gsis_id, joins directly) ships ffverse's **empirical
  expected-points model** already fit on historical PBP: `total_fantasy_points_exp` plus
  scoring-agnostic component expectations (`rec_touchdown_exp`, `rec_yards_gained_exp`,
  `receptions_exp`, `rush_yards_exp`, …) we re-derive under league scoring via the existing `_scoring`
  engine, and `*_diff` (actual − expected) columns that are exactly the §1 point-correlation/luck
  companion. So #3 becomes a **consume-and-re-score** transform (+ a quality backtest — `quality_rate`
  isn't gated today), replacing the hand-rolled `quality_rate = xtd_g/opp_g` (nflfastR `td_prob`,
  TD-centric) with the full multi-component EV read DECISION_READS §1 specifies. The per-play
  `pbp_pass`/`pbp_rush` variants (yardline/down/air-yards + per-play `*_exp`) are there if we ever want
  our own weights — but we don't. ("Routes run" is correctly deferred — the spec flags it as the hard one.)
  *Where:* [application/data/transforms/compute_player_signal.py](application/data/transforms/compute_player_signal.py);
  source `nflreadpy.load_ff_opportunity` (fetch alongside [nfl_stats.py](application/data/fetchers/nfl_stats.py)).

- [x] **§2 bull/bear has no preseason anchor.** ✅ **DONE (2026-07-10, session 2).** The "blocked on
  data" verdict was wrong — the ADP source was in `nflreadpy` (already a dependency) all along.
  `nflreadpy.load_ff_rankings('all')` carries historical FantasyPros consensus rankings back to 2019
  (redraft-overall, `ecr`/`best`/`worst`, id-bridged FantasyPros→sleeper via `ff_playerids`), so a
  preseason anchor is both buildable and backtestable against the 2025 freeze. Shipped as
  **Option 2 (historical ADP→realized curve)**: a per-position `pos_ecr_rank → realized-points
  floor/center/ceiling` curve (P10/P50/P90, rolling-window + isotonic-smoothed) fit on 2020–2024
  (2025 held out = leak-free), then blended into bull/bear with a horizon-decaying weight
  `w_N = ANCHOR_W · (remaining/total)` — §2's prior→evidence dynamic made explicit. `ros_center`
  stays the borrowed projection (law 3); only the extremes are anchored; undrafted/uncovered players
  degrade to the pure-projection band. The `BULL_Z` re-sweep (jointly with `ANCHOR_W`) landed at
  (1.44, 0.25): the anchor lifts freeze coverage 0.744→0.817 and rebalances the projection's lopsided
  miss tails (0.195/0.061 → 0.091/0.091); gate exit 0. New `fetchers/adp.py` + `compute_adp_points_curve.py`
  + `adp_preseason` / `adp_points_curve` data-layer entities. (Separately, the §2 **AI narrative +
  1–10 roll-up** is deferred to Phase 6 by design.)
  *Where:* [application/data/transforms/compute_ros_outcome_shape.py](application/data/transforms/compute_ros_outcome_shape.py),
  [application/data/fetchers/adp.py](application/data/fetchers/adp.py),
  [application/data/transforms/compute_adp_points_curve.py](application/data/transforms/compute_adp_points_curve.py).

## Config / deps / doc hygiene

- [x] **`config.example.py` is out of sync.** ✅ **DONE (2026-07-10)** — added `SLEEPER_LEAGUE_ID`;
  removed the dead, duplicate-keyed `LEAGUE_TYPES` and dead `EXCLUDED_LEAGUES` (consumed nowhere).
  Add the required `SLEEPER_LEAGUE_ID` — it's absent
  from the example, so a fresh copy `AttributeError`s in `league_resolver`. Drop the unused
  `LEAGUE_TYPES` / `EXCLUDED_LEAGUES` (consumed nowhere in the codebase) — or wire them up. (The
  `LEAGUE_TYPES` example dict also has three identical placeholder keys, so only the last survives.)
  *Where:* [application/config.example.py](application/config.example.py); consumer
  [application/shared/league_resolver.py](application/shared/league_resolver.py:21).

- [x] **Prune `pandas` / `nfl_data_py` from requirements.** ✅ **DONE (2026-07-10)** — both removed
  from `requirements.txt` (verified zero imports repo-wide). Both are unused (zero imports anywhere)
  and contradict non-negotiable #1 ("polars, never pandas"); `nfl_data_py` is the deprecated
  predecessor to `nflreadpy`.
  *Where:* [application/requirements.txt](application/requirements.txt).

- [x] **Reconcile the bracket-backtest figure across the docs.** ✅ **DONE (2026-07-10)** — the true
  4-team-cut figure is **top-4 by odds = 3/4** (confirmed by running `backtest_bracket_sim.py`:
  "top-4 by playoff_odds → 3/4 correct"). Fixed the stale `top-6 / 6/6` lines in STATUS.md (x3) and
  TECHNICAL_ARCHITECTURE.md:683; the historical build-log entry keeps its as-built 6/6 qualified with
  the corrected figure in its supersede note. STATUS.md says "6/6 actual playoff
  teams"; TECHNICAL_ARCHITECTURE.md says "top-4 by odds = 3/4" — the same gate at the old (inferred
  6) vs. corrected (real 4-team) playoff cut. Pick the true number from
  `backtest_bracket_sim.py`'s actual output and make every doc agree.
  *Where:* [STATUS.md](project_management/LLM%20context/STATUS.md) (lines ~175, ~231, ~471),
  [TECHNICAL_ARCHITECTURE.md](project_management/LLM%20context/TECHNICAL_ARCHITECTURE.md) (line ~683
  still says 6/6; line ~310 already says 3/4). Source of truth:
  [application/data/transforms/backtest_bracket_sim.py](application/data/transforms/backtest_bracket_sim.py).
  *(Note: READ_BUILD_ORDER.md's copy of this line was corrected to 3/4 during its 2026-07-10
  refresh — STATUS + TECHNICAL_ARCHITECTURE are what remain.)*
