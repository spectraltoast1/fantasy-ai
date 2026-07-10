# 710 Audit — Fix Checklist

**Created:** 2026-07-10 · Backend-audit follow-ups to work off **before / alongside the frontend pivot.**

Seven cleanup items surfaced by the 2026-07-10 backend audit. Each is a standalone fix; none
blocks the frontend work. Ordered by the audit's own severity framing (structural → scaling →
spec-completeness → hygiene). Check them off as they land. **This doc is the backlog; the fixes
themselves are not done here.**

---

## Structural

- [ ] **No package structure; `sys.path.insert` everywhere.** Transforms and `ai/` aren't
  importable modules — every script hand-hacks `sys.path` to reach `data_layer` / `_manager` /
  `config`, and one does it *lazily, mid-function*. This is the thing most likely to break on the
  server migration and the hardest to retrofit later. **Fix:** make `application/` a proper package
  (or add `pyproject.toml` + relative imports), removing ~40 lines of path juggling and the
  import-order fragility.
  *Where:* [application/data/transforms/](application/data/transforms/) (`*.py`),
  [application/ai/](application/ai/) (`*.py`), notably
  [application/data/fetchers/sleeper.py](application/data/fetchers/sleeper.py:585)
  (`_import_manager_helpers`).

## Scaling (bounded today)

- [ ] **Read-modify-write-whole-file append pattern.** Every incremental write reads the entire
  file, filters, concats, and rewrites — O(n²) over a backfill. Fine at current scale (18 weeks, 10
  managers); it's the ceiling on how far the parquet-file approach stretches. The eventual
  SQLite/warehouse layer is the real fix — don't hand-optimize the parquet writers, just know this
  is the migration trigger.
  *Where:* [application/data/data_layer.py](application/data/data_layer.py) —
  `write_join_nfl_sleeper_weekly`, `write_manager_activity`, `write_projections`,
  `write_leaguelogs_market_snapshot`.

## Spec completeness (vs. DECISION_READS)

- [ ] **§1 Quality axis is a TD-proxy, not the spec.** `quality_rate = xtd_g/opp_g` is built from
  nflfastR `td_prob` — narrower and TD-centric versus DECISION_READS §1's *empirical EV-weights per
  chance-type* (target depth / aDOT, field position, down & distance) re-derived under league
  scoring. It's a reasonable proxy, but not the read as specified. ("Routes run" is correctly
  deferred — the spec flags it as the hard one.)
  *Where:* [application/data/transforms/compute_player_signal.py](application/data/transforms/compute_player_signal.py).

- [ ] **§2 bull/bear has no preseason anchor.** DECISION_READS §2 says bull/bear are anchored to
  realistic **preseason limits** (draft capital / ADP ceiling & floor); the shipped band is purely
  `centre ± z·σ` off the forward projection — no preseason anchor. (Separately, the §2 **AI narrative
  + 1–10 roll-up** is deferred to Phase 6 by design.)
  *Where:* [application/data/transforms/compute_ros_outcome_shape.py](application/data/transforms/compute_ros_outcome_shape.py).

## Config / deps / doc hygiene

- [ ] **`config.example.py` is out of sync.** Add the required `SLEEPER_LEAGUE_ID` — it's absent
  from the example, so a fresh copy `AttributeError`s in `league_resolver`. Drop the unused
  `LEAGUE_TYPES` / `EXCLUDED_LEAGUES` (consumed nowhere in the codebase) — or wire them up. (The
  `LEAGUE_TYPES` example dict also has three identical placeholder keys, so only the last survives.)
  *Where:* [application/config.example.py](application/config.example.py); consumer
  [application/shared/league_resolver.py](application/shared/league_resolver.py:21).

- [ ] **Prune `pandas` / `nfl_data_py` from requirements.** Both are unused (zero imports anywhere)
  and contradict non-negotiable #1 ("polars, never pandas"); `nfl_data_py` is the deprecated
  predecessor to `nflreadpy`.
  *Where:* [application/requirements.txt](application/requirements.txt).

- [ ] **Reconcile the bracket-backtest figure across the docs.** STATUS.md says "6/6 actual playoff
  teams"; TECHNICAL_ARCHITECTURE.md says "top-4 by odds = 3/4" — the same gate at the old (inferred
  6) vs. corrected (real 4-team) playoff cut. Pick the true number from
  `backtest_bracket_sim.py`'s actual output and make every doc agree.
  *Where:* [STATUS.md](project_management/LLM%20context/STATUS.md) (lines ~175, ~231, ~471),
  [TECHNICAL_ARCHITECTURE.md](project_management/LLM%20context/TECHNICAL_ARCHITECTURE.md) (line ~683
  still says 6/6; line ~310 already says 3/4). Source of truth:
  [application/data/transforms/backtest_bracket_sim.py](application/data/transforms/backtest_bracket_sim.py).
  *(Note: READ_BUILD_ORDER.md's copy of this line was corrected to 3/4 during its 2026-07-10
  refresh — STATUS + TECHNICAL_ARCHITECTURE are what remain.)*
