# Custom Scoring Support — Assessment & Plan

**Last reviewed:** 2026-07-16 · **Status:** Scope / design doc — **not yet started.**

> **Verdict:** Custom scoring is **engine-partial**. The delta engine scores any linear per-component
> weighting plus position-conditional reception bonuses (TE-premium), but **raises on first-down and
> threshold/milestone yardage bonuses** — which knocks out **~45% of real custom leagues**. The
> *measurement* problem (how do you tune a custom key at n=1?) is **already solved by design**: custom keys
> are a certification target, never a fit target. So the **only real growth lever is engine rule
> coverage.**
>
> **Origin:** produced 2026-07-16 from a code-grounded read of `transforms/_scoring.py`,
> `corpus/select.py`, and a re-run of the reject logic over `corpus_discovery.parquet`. Companion to
> [`STANDARD_SCORING_SUPPORT.md`](./STANDARD_SCORING_SUPPORT.md) and
> [`DYNASTY_SUPPORT.md`](./DYNASTY_SUPPORT.md); the shared invariance thesis lives in the standard doc.

---

## Context

**Why:** Custom scoring is the *dominant* real-world profile — **1,765 of the discovered custom pool**
(after the Session 0.6 float32 correction; `LEAGUE_CORPUS.md:52-58`), the near-inverse of the product's
narrow shape. The engine's "any-league" ambition lives or dies on how much of that pool it can score.

**Corrected mental model.** "Custom scoring" is two very different problems the term hides:
1. **Can we *score* the league?** — a coverage question about the delta engine's rule set. This is where
   the 45% wall is.
2. **Can we *tune/certify* a custom key?** — a statistics question. It sounds hard (each custom key is a
   handful of leagues) but it is **already answered**: the tuned constants are scoring-invariant and fit on
   the matched stratum; a custom key never gets its own fit. See the shared thesis in
   [`STANDARD_SCORING_SUPPORT.md`](./STANDARD_SCORING_SUPPORT.md). So problem (2) is not a blocker — problem
   (1) is the whole job.

A third subtlety the term hides: **two engines score custom leagues, and they disagree about what's
supported** — the *projection* path (consensus/band → production_vor/market/true_rank/bracket) and the
*expected-points* path (§1 Quality). That asymmetry is the key to the plan.

---

## What the engine supports today (grounded)

**The delta engine — `recompute_custom_points(scoring, side)` (`_scoring.py:163-197`).** Instead of
rebuilding points from scratch (which would miss vendor-baked contributions by up to ~2 pts, `:16-24`), it
adds only the *delta* from standard per component:
`points_league = std_baseline + Σ_k (w_custom[k] − w_std[k])·component_k`.
- **Supported:** any `rec`/PPR value, 6-pt pass TD, any `pass/rush/rec` yardage or TD rate — the linear
  components in `_COMPONENT_COLS` (`:69-77`) — **plus** position-conditional per-reception bonuses (the
  TE-premium family `bonus_rec_qb/rb/wr/te`, gated on position; `_REC_BONUS_POS` `:82-87`, applied
  `:181-189`). Exact for a standard league by construction (all deltas 0).
- **Rejected — raises `NotImplementedError`, never silently mis-scores** (`_reject_unsupported`,
  `:142-160`): **first-down bonuses** (`pass_fd`/`rush_fd`/`rec_fd`, `_FIRST_DOWN_KEYS` `:91`) and
  **threshold/milestone bonuses** (`bonus_rush_yd_100`, `bonus_pass_yd_300`, …). The reason is precise: the
  Sleeper/RotoWire `projections` carry **no component** for these, so the projected *center* can't be scored
  the same way the actual is — the read "would be silently wrong."

**The asymmetry — the expected-points engine already goes further.** `expected_points_expr(scoring)`
(`:249-275`) is a from-scratch weighted sum over ff_opportunity component **expectations** (`_EXP_TERMS`,
`:228-243`), and ff_opportunity *does* expose first-down components (`pass/rush/rec_first_down_exp`,
`:240-242`). So the **§1 Quality read (`compute_player_signal`) already scores first-down custom leagues**;
only the projection-center reads reject them. Threshold bonuses are unsupported by *both* engines (a
threshold needs `P(yards ≥ T)`, a distribution neither the point projection nor the expected component
carries).

**Selection already runs the real engine.** `select.scoreability` (`select.py:53-63`) calls
`recompute_custom_points` at selection time and records `scoreable` + the rejecting keys; matched/gen
require `scoreable=True` (`select.py:330-334`). Custom keys share one `cust-<8-char hash>` so identically
scored leagues share a substrate file (`_keys.py:17-23`), and the gen stratum caps distinct custom keys at
`GEN_CUSTOM_KEY_CAP=12` (`_corpus.py:20`) to bound substrate cost.

## The gap (grounded, quantified)

- **802 of 1,765 discovered custom leagues (45.4%) are unscoreable** by the delta engine
  (`LEAGUE_CORPUS.md:54`; reproduced by running `_reject_unsupported` over every `scoring_settings_json` in
  `corpus_discovery.parquet`). Dominant rejecting keys (league counts):
  `bonus_rush_yd_200` (460), `bonus_rec_yd_200` (452), `bonus_pass_yd_400` (449), `rush_fd` (418),
  `rec_fd` (415), `bonus_rush_yd_100` (382), `bonus_pass_yd_300` (320), `pass_fd` (208).
- Two mechanically distinct sub-gaps:
  - **First-down bonuses** (~443 leagues involve an `_fd` key): **already scored by the Quality engine**,
    rejected only by the *projection* path. A bounded, offline-available fix.
  - **Threshold/milestone yardage bonuses** (~359 leagues threshold-only): needs a *distribution*, not a
    point — the genuinely hard class, unsupported by both engines.
- In the *selected* manifest only 4 of 312 are `scoreable=False` — because selection filters them out. The
  wall is in the wild pool, not the corpus.

---

## Plan (staged) — (a) close the rule-coverage gap, (b) settle the measurement stance

**Stage 1 — First-down for the projection path (bounded; offline-available).** Bridge the asymmetry:
extend the projection center to carry a first-down component so `_reject_unsupported` no longer needs to
reject `*_fd`. Two sources, in order of availability:
- **(1a)** Use the **ff_opportunity first-down expectations** already computed for §1 Quality as the
  projection center's fd term (the component exists — `_EXP_TERMS:240-242`; wire it into
  `compute_projection_consensus`'s baseline the way `expected_points_expr` already does). Offline, today.
- **(1b)** Or consume an in-season projection source that carries fd (ffanalytics/FantasyPros) — the code's
  own stated unlock (`_scoring.py:34,159`). In-season only.
Recommend (1a). Effect: recovers the ~443 first-down leagues for the full read spine (~+25pts of custom
coverage). Must stay gate-guarded — extend `_reject_unsupported` to *keep* rejecting only what's still
unscoreable.

**Stage 2 — Threshold/milestone bonuses (the hard class; scope as an experiment, not a default).**
`E[bonus] = bonus · P(yards ≥ threshold)` needs a per-player yardage **distribution**. Options to assess:
- **(2a)** Keep the explicit reject (honest; ~20% of custom stays unscoreable). Zero risk.
- **(2b)** A coarse approximation: model per-player yards `~ Normal(center, band σ)` from the consensus
  (the band already carries σ) and integrate the tail for `P(≥T)`. Non-trivial risk of silent mis-scoring,
  so it must be **backtest-gated** against real threshold-league outcomes before it can ship — the same
  "raise rather than silently mis-score" discipline `_reject_unsupported` enforces today.
Recommend documenting (2b) as an explicit, gated experiment; default to (2a) until it clears a gate.

**Stage 3 — Settle the measurement stance (custom keys are n=1).** Make the design explicit in the doc:
**certify, don't fit.** The scoring-invariant constants are fit on matched (`_corpus.py:23`,
`LEAGUE_CORPUS.md:44-46`); each custom key enters only as a **league-wise holdout** in the generalization
stratum (`never_tune=True`, `select.py:313`) — the honest test that the constants generalize to an unseen
*shape*. Per-key fitting needs a per-key corpus that will never exist at n=1, and pooling all custom keys to
fit would reintroduce the distribution shift the narrow-corpus decision exists to avoid. So the settled
stance is: **custom = code-supported (to the extent Stages 1-2 reach) + shared-constants + certified.**

---

## Risks / can't-generalize

- **Threshold bonuses may stay permanently unscoreable** without a distributional model; the Normal-tail
  approximation (2b) is the only offline path and it risks silent error — it is *only* acceptable behind a
  backtest gate.
- **First-down bridge fidelity.** ff_opportunity's expected first-downs are an *expectation*, not the
  vendor's projection — using them as the projection center for fd leagues introduces a small source
  mismatch between the projected center and the actual (scored via the same ff component); validate that
  residuals stay matched (the invariant `_scoring.py:26-28` protects).
- **Certification ≠ representativeness.** The gen stratum covers *code paths*, not the custom distribution
  (`_corpus.py:16-18`); a certified custom key means "the constants didn't break on this shape," not "we
  tuned for custom leagues."

---

## Critical files

**Modify:** `transforms/_scoring.py` (extend the projection path with a first-down term; the threshold
approximation if pursued; shrink `_reject_unsupported`'s reject set as coverage grows),
`transforms/compute_projection_consensus.py` (consume the new fd/threshold terms in the baseline),
`corpus/select.py` `scoreability` (auto-tracks the shrinking reject set — no change needed beyond re-run).
**Reference (reuse, don't rebuild):** `_scoring.expected_points_expr` / `_EXP_TERMS` (the fd component
already exists, `:228-275`), `_scoring._REC_BONUS_POS` (the position-gating pattern to mirror for any new
position-conditional term).

---

## Verification

- **Coverage delta:** re-run the `_reject_unsupported`-over-discovery census after Stage 1; the unscoreable
  rate should drop from 45.4% by the first-down share (~to ~20%). Assert the remaining rejects are
  threshold-only.
- **First-down correctness:** on a real first-down league, confirm `production_vor` now computes and
  `check_spine` is green; spot-check that a first-down-heavy player (high `rec_first_down_exp`) gains value
  vs the same league scored without fd.
- **No regression:** matched + is_mine spine stays byte-identical (the Stage-1 change must be additive and
  gated to non-fd leagues by delta==0), mirroring the 3d/3e "0/666 changed" discipline.
- **Threshold gate (if 2b):** the Normal-tail approximation must beat a naive "ignore the bonus" baseline
  on held-out threshold-league outcomes before it ships; otherwise it stays a reject.

---

## Session / commit sequencing

~2-4 sessions (3-commit cap each). Session 1 = first-down projection bridge + gate + coverage census.
Session 2 = re-harvest/compute the recovered first-down custom leagues + certify. Session 3 (optional,
gated) = the threshold-bonus experiment. Fresh worktree → `worktree-setup.sh` → work → update `STATUS.md`
→ `worktree-close.sh --merge`. Report, don't tune: no constant is re-fit for custom in any of these.
