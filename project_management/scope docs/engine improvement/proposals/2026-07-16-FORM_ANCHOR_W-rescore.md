# Re-score — `FORM_ANCHOR_W` (the S7 de-bias), shadow measurement

**Companion to** `2026-07-16-FORM_ANCHOR_W.md` (the tuner proposal: **HOLD**, λ*=0.1, DEV effect 0.20 < 0.5 floor).
**Shadow only** — recomputed in memory at frozen band dials against the corpus **canonical** answer key;
the frozen `predictions` / `resolutions` / `engine_scorecard` are untouched (std instr 8). Regenerate with
`python3 -m application.data.corpus.rescore_debias --seasons 2023 2024 2025`.

## What this measures

Session 6 held every band dial on the thesis that the band under-covers **because the centre is
optimistic** — widening the band was compensating for an over-high centre (entanglement). This session's
test (std instr 6): de-bias the centre (λ), and ask whether band coverage recovers toward 0.80 **at the
FROZEN `BULL_Z=1.44` / `ANCHOR_W=0.25`** — i.e. does fixing the centre, and only the centre, restore
coverage without re-widening? If yes, the centre was the cause. Graded over the shipped `in_calibrated_pool`
at week 4, per scoring_key (mean across keys), for each λ.

## The three optimism symptoms across λ (mean over half + ppr)

| season | λ | centre-MAE | coverage | below-bear (low miss-tail) | above-bull |
|---|---|---|---|---|---|
| **2025** (TEST) | 0.00 | 26.39 | **0.571** | 0.427 | 0.002 |
| | 0.10 | 25.74 | 0.572 | 0.426 | 0.002 |
| | 0.25 | 25.59 | 0.557 | 0.433 | 0.010 |
| | 0.50 | 27.41 | 0.533 | 0.428 | 0.039 |
| | 1.00 | 36.59 | 0.494 | 0.452 | 0.053 |
| **2024** (DEV) | 0.00 | 21.95 | 0.661 | 0.324 | 0.015 |
| | 0.10 | 21.74 | 0.669 | 0.314 | 0.016 |
| | 1.00 | 35.21 | 0.507 | 0.426 | 0.066 |
| **2023** (TRAIN) | 0.00 | 27.50 | 0.526 | 0.467 | 0.007 |
| | 0.10 | 27.44 | 0.508 | 0.485 | 0.007 |
| | 1.00 | 40.47 | 0.431 | 0.539 | 0.031 |

## The findings (report, don't overreach)

1. **The de-bias does NOT recover coverage at the frozen dials — the headline is a null.** Across all three
   seasons, coverage at λ=0 (~0.53–0.66, mean ~0.59, matching the brief's cited ~0.55) does **not** climb
   toward 0.80 as λ rises; it is flat at best (a +0.008 blip at λ=0.1 in 2024) and **declines** for λ ≥ 0.25.
   The **low miss-tail (below-bear) barely moves** at small λ and *grows* at large λ. **This does not confirm
   the Session-6 entanglement thesis:** fixing the centre alone does not restore coverage.

2. **The mechanism — the under-coverage is a band-WIDTH problem, not centre height.** The miss is hugely
   asymmetric: ~32–47% of realised falls **below** the bear, ~0–6% above the bull. The band's whole range
   sits too high *and* is too narrow to reach the busts. A recent-form de-bias can't fix it because recent
   form (weeks 1–4) does not predict the *later* busts — it lowers some centres but not the ones that crater,
   so the bear tail is unmoved. The lever is band **width** (a wider, low-skewed band): **Session 8's
   `BULL_Z` re-tune**, not the centre. The entanglement S6 assumed is weaker than believed.

3. **The honest, leak-safe de-bias barely improves centre-MAE** (λ*=0.1: DEV 21.95→21.74, 0.20 < the 0.5
   floor). The scorer's "production_vor loses to carry-recent-form every season" relied on the naive's
   **hindsight realized-forward-week count** (`recent_ppg × n_fwd`), which a shipped, leak-safe projection
   cannot use — it only has the projected remaining-week count. On the honest basis, recent form does not
   beat the borrowed centre. λ=1 (pure form) is far *worse* (MAE ~35–40) — the interior shallow optimum near
   λ≈0.1 is real, not λ=1 (std instr 1 satisfied).

4. **Basis (the raw-PPR-vs-canonical lead, resolved).** Graded against **canonical** per-key realized points
   (`player_weekly_pts_canonical`), never raw `fantasy_points_ppr`. Confirmed still-open: the shipped
   `backtest_production_vor.run()` / `_actual_ros` and `backtest_ros_player_band._actual_weekly` /
   `compute_player_signal` read raw `fantasy_points_ppr` — a fixed-PPR basis that mis-scores non-PPR corpus
   keys by up to ~7 pts/wk. The S7 objective + this re-score use canonical; switching the shipped is_mine
   grades to canonical is a follow-on (they only see ppr today, so no live number moves).

## Recommendation

**HOLD — ship `FORM_ANCHOR_W = 0.0` (identity).** Do not promote λ*. The de-bias, done honestly, neither
clears the effect floor on centre-MAE nor recovers band coverage. **The optimism symptoms are a band-width
problem; the lever is Session 8's `BULL_Z` re-tune** (widen + low-skew the band), now measurable on this
same corpus objective. The mechanism ships at identity and the substrate (the dial + the re-score) is in
place for Will to re-open if a different centre signal (a systematic downward shrink, not recent form) is
worth trying.
