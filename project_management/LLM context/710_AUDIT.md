# 710 Audit — Fix Checklist

**Created:** 2026-07-10 · Backend-audit follow-ups to work off **before / alongside the frontend pivot.**

Seven cleanup items surfaced by the 2026-07-10 backend audit. Each is a standalone fix; none
blocks the frontend work. Ordered by the audit's own severity framing (structural → scaling →
spec-completeness → hygiene). Check them off as they land.

> **Progress (2026-07-10 session):** ✅ **#1 (package structure), #5 (config.example),
> #6 (requirements), #7 (bracket figure) are DONE.** #2 (scaling) is a **no-op by design**
> (documented migration trigger — do not hand-optimize the parquet writers). #3 and #4
> (spec completeness) are **deferred**: #3 is a net-new empirical-weighting transform (not a
> tweak), and #4 is **blocked on data** — no ADP / draft-capital source is fetched anywhere,
> so the preseason anchor isn't buildable until one lands. Investigation notes are inline below.

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

- [ ] **§1 Quality axis is a TD-proxy, not the spec.** ⏸ **DEFERRED (scoped 2026-07-10).** Not a
  tweak to `quality_rate` — the true spec is a **net-new empirical-weighting transform**: it needs a
  per-chance-type PBP-tag store (the fetcher currently collapses PBP to `xtd`/`redzone_touches` at
  fetch time and discards down/distance/yardline/air_yards), a multi-season historical PBP sample to
  fit the weights, and league-scoring re-derivation (the `_scoring` engine exists). `quality_rate`
  isn't gated today, so the rebuild should also add a quality backtest. Belongs with the read/modeling
  work, not this cleanup pass. `quality_rate = xtd_g/opp_g` is built from
  nflfastR `td_prob` — narrower and TD-centric versus DECISION_READS §1's *empirical EV-weights per
  chance-type* (target depth / aDOT, field position, down & distance) re-derived under league
  scoring. It's a reasonable proxy, but not the read as specified. ("Routes run" is correctly
  deferred — the spec flags it as the hard one.)
  *Where:* [application/data/transforms/compute_player_signal.py](application/data/transforms/compute_player_signal.py).

- [ ] **§2 bull/bear has no preseason anchor.** ⏸ **DEFERRED — BLOCKED ON DATA (scoped 2026-07-10).**
  The preseason anchor requires draft-capital / ADP, and **no such source is fetched or derivable at
  the freeze**: Sleeper's draft endpoints are uncalled, nflreadpy's ADP/rankings loaders are uncalled,
  and LeagueLogs market value is an in-season "now" snapshot (no 2025-preseason history) and is market
  value, not draft capital. Buildable only after a preseason ADP source lands; the calibration gate
  (`BULL_Z`) would then need a re-sweep. DECISION_READS §2 says bull/bear are anchored to
  realistic **preseason limits** (draft capital / ADP ceiling & floor); the shipped band is purely
  `centre ± z·σ` off the forward projection — no preseason anchor. (Separately, the §2 **AI narrative
  + 1–10 roll-up** is deferred to Phase 6 by design.)
  *Where:* [application/data/transforms/compute_ros_outcome_shape.py](application/data/transforms/compute_ros_outcome_shape.py).

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
