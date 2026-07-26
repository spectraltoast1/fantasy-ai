# Session 8 — Band Honesty: make the bull/bear range actually contain reality

**Hand this file to Claude Code as the session brief.**

**Type:** read-improvement — re-tune the ROS bull/bear band for honest coverage + swap its confidence signal to raw points, tuned **through the L4 harness** on the corpus objective · **Commits:** 3
**Reads first:** `CLAUDE.md` · `SESSION_6_L4_TUNER.md` (the harness + registry + guardrails) · `SESSION_7_DE_BIAS.md` + its re-score proposal (`proposals/2026-07-16-FORM_ANCHOR_W-rescore.md` — **why the band, not the center, is the lever**) · `SESSION_5_L3_SCORER.md` (the coverage + inverted-`ros_cv` findings)
**Blocks:** Session 9 (the cleanup pass) and the live-season track.
**Prior:** Session 7 — the center de-bias was a **null**: fixing the center does NOT recover band coverage, and the band was never really entangled with the center. The band under-covers on its own, and it is the primary optimism fix — promoted from "cleanup" to the headline.
**Changes numbers BY DESIGN — proposals Will promotes.** New band-dial values + the raw-points confidence signal are re-scored for evidence and **proposed**; the frozen corpus stays the baseline; nothing ships until Will promotes.

---

## Why this exists

The ROS bull/bear band — the "we think ~100, likely between 75 and 130" range — is the engine's least honest read: across the corpus it contains reality only **~55%** of the time when it claims **~80%**, and the miss is lopsided — **~43% of outcomes fall below the bear floor, ~0% above the bull ceiling.** Session 7 tested the standing theory that this was downstream of an optimistic center (fix the center, the band recovers) and got a clean **null** — de-biasing the center leaves coverage at ~0.57. So the band's dishonesty is its own: it is **too narrow, and symmetric when it should be skewed low.** Separately, Session 5 found the band's *confidence* signal is **inverted** — it uses `ros_cv`, a *percentage* spread, which labels high-projection stars "most confident" even though in raw points they are the least pinned down. This session fixes both: an honestly-wide, low-skewed band, and a confidence signal in raw points that actually sorts by realized error. It is the biggest single honesty gain left in the engine.

### Verified state (what aims this session)

- **Coverage ~0.55–0.59 vs the 0.80 target; asymmetric low miss-tail (~32–47% below-bear, ~0–6% above-bull)** — from Session 5 and the 6b/S7 corpus re-score. Symmetric widening alone is wasteful (it inflates the already-fine high side); the band needs **asymmetric tails** (a bigger bear than bull).
- **The 6b OOS width fit was right-censored** — `BULL_Z` pinned to its grid ceiling (1.96), so the true optimum is wider; the fits were also marginal 1-D (BULL_Z with ANCHOR_W fixed, and vice-versa).
- **The band's confidence is `ros_cv` (percentage) and is inverted** (Session 5). The fix is the raw-points spread (the σ in points).
- **The corpus band objective is ready** (6b `_corpus_test_points`, canonical answer key) and now grades against the **current** center (the de-bias is HELD at identity — no center change to wait for).

---

## The design decisions (all mine; flagged for Will's awareness)

**1. Give the ROS band asymmetric tails (the "low-skew").** Today the band is symmetric: center ± `BULL_Z`·σ. Introduce a downside skew so the **bear** reaches the busts without ballooning the bull — minimally, a separate bear-side width (`BEAR_Z`) or a skew multiplier, tuned jointly with `BULL_Z`. This is a decision-layer interval-shape change (design law 3 safe — it reshapes the interval, it does not build a projection). *(Recommendation: the smallest asymmetric form that clears coverage + tail-balance on the holdout; don't over-parameterize.)*

**2. Re-tune width + skew + anchor JOINTLY, on an extended grid, across the season.** Sweep `BULL_Z` / the new skew / `ANCHOR_W` **together** (they're coupled) through the Session-6 harness on the corpus objective — extend the `BULL_Z` grid upward past 1.96 (the 6b fit hit the ceiling), and grade **across the season's as-of weeks**, not just week 4 (retire 6b's interim `GRADE_WEEK`). Objective: coverage → ~0.80 **with balanced tails** (below-bear ≈ above-bull), on TRAIN 2020–23, certified on DEV 2024, proven on TEST 2025 + the generalization holdout.

**3. Swap the band's confidence signal `ros_cv` → raw-points σ.** Replace the percentage confidence with the raw-points spread, so a wider raw interval correctly reads as *less* confident. Re-score confidence-honesty (is realized error monotone in the new signal?) — this is the law-2 fix for the band.

**4. Propose, don't promote.** New dial values + the confidence-signal swap are **proposals** with re-score evidence; Will promotes. The frozen corpus stays the baseline; the re-score is a shadow measurement (std instr 8). *(Recommendation: propose-only — this changes a shipped, user-visible range and its confidence label; it deserves your review.)*

---

## Commit 1 — The asymmetric band + the joint, across-season re-tune

- Add the downside-skew parameter(s) to `compute_ros_player_band` (decision 1), registry dials, **defaulting to today's symmetric behavior** (prove the default recomputes the frozen band value-identical — std instr 2).
- Sweep `BULL_Z` × skew × `ANCHOR_W` jointly through the harness on the extended grid, across-season, graded on the **canonical** answer key; certify on DEV, seal TEST + generalization.

## Commit 2 — The raw-points confidence swap + confidence-honesty re-score

- Compute the band's confidence from the raw-points σ (decision 3); keep the `ros_cv` value available as an audit column, not the primary signal.
- Re-score confidence-honesty on the corpus: realized error must be monotone in the new signal (the inverted-`ros_cv` finding flips honest). Report the before/after.

## Commit 3 — The win re-score + the proposal + gate + docs (+ scope Session 9 is already done)

- **Re-score the win** (shadow): coverage ~0.55 → ~0.80, tails balanced, confidence-honesty positive — the three numbers that define band honesty. Frozen corpus untouched.
- **Proposals** for the new dial values + the confidence swap, gated by the four guardrails.
- **`check_band_honesty`** (or extend `check_tuner`): the symmetric-default identity bites; coverage/tail-balance/confidence-monotonicity are asserted on the holdout; determinism value-identical.
- **Docs** (STATUS / TECH_ARCH / IMPROVEMENT_LOOP). **Scope the silent-reads confidence work as the next read-improvement.**

---

## Acceptance gates

1. **Symmetric default is identity** — with skew off and dials at current values, the band recomputes value-identical to the frozen spine.
2. **Honest coverage on the holdout** — the joint fit reaches ~0.80 coverage with balanced tails on DEV 2024 and TEST 2025, on the extended grid, across-season, canonical basis.
3. **Confidence is honest** — realized error is monotone in the raw-points signal (the inverted-`ros_cv` result flips); reported before/after.
4. **Propose, don't promote** — new values + the swap are proposals with re-score evidence; the frozen corpus is untouched; nothing shipped.
5. **Determinism + seam** — twice-run value-identical; `queries.js` / views untouched (the shipped band doesn't move until promotion).

---

## Out of scope

- **Confidence signals for the silent reads (`production_vor` + the others that state no confidence)** — the next read-improvement; its own session, not this one.
- **The Session 9 cleanup pass** (the leaky-naive re-score, the raw-PPR→canonical grade switch, code cleanups) — scoped separately.
- **Promoting the band changes**, the live-season track, the AI reads. Later / human-promoted.

---

## Definition of done

- The ROS band has honest, asymmetric tails and a raw-points confidence signal; the symmetric default recomputes the frozen band value-identical.
- The joint, across-season, extended-grid fit reaches ~0.80 coverage with balanced tails and honest confidence, proven on unseen seasons — **proposed**, not promoted.
- The win re-score reports coverage + tail-balance + confidence-honesty; the frozen corpus is intact.
- `check_band_honesty` green with teeth; seam held; Session 9 + the silent-reads work scoped.

---

> ## Standing instructions
> 1. **A suspiciously clean value is a bug until proven otherwise.** *(A width that pins to the new grid ceiling again → extend it and interrogate; a coverage that snaps to exactly 0.80 → check it's not overfit to the fit window.)*
> 2. **A refactor that changes a number is a bug** — prove equivalence. *(The symmetric-default band must recompute the frozen spine value-identical.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.** *(Band shape + confidence are decision-layer; no view edits, no shipped move until promotion.)*
> 4. **Report, don't promote — and don't overreach.** *(New dials + the confidence swap are proposals with holdout evidence.)*
> 5. **Deleting/duplicating a series must not move a live number.** *(Keep `ros_cv` as an audit column; don't silently drop it.)*
> 6. **A plausible explanation is not a diagnosis.** *(Show the coverage + tail-balance recovering on unseen seasons — the mechanism — not just on the fit window.)*
> 7. **"The artifact exists" and "the consumer uses it" are two different gates.** *(A raw-points confidence column ≠ the band reports it — gate that the shipped confidence is the new signal.)*
> 8. **Persist the substrate; never re-derive from a moving source.** *(The re-score is additive + provenanced; the frozen corpus is the baseline.)*
