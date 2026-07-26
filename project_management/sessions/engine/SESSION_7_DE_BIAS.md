# Session 7 — The De-bias (read-improvement): a second anchor toward recent form

**Hand this file to Claude Code as the session brief.**

**Type:** read-improvement — a decision-layer *second anchor* that de-biases the projection center, tuned **through the L4 harness** on the split · **Commits:** 3
**Reads first:** `CLAUDE.md` · `IMPROVEMENT_LOOP.md` **§L4** + **design law 3** (borrow the substrate, build the *layer* — a recent-form blend IS the layer, so it is allowed) · `SESSION_6_L4_TUNER.md` (the harness + registry this tunes through; the dial/pin rule) · `SESSION_5_L3_SCORER.md` (the scorecard this re-scores; the optimism finding that aims it)
**Blocks:** Session 8 — band honesty (re-tune the band once the center is fixed; expect `SKEW_GAIN`→0; swap the band's confidence off `ros_cv`).
**Prior:** Session 6 + 6b (the tuner + the corpus-wide band objective). The rank-1 lead out of Session 6 was **"de-bias the center first."** This is that session.
**Changes numbers BY DESIGN — but ships the mechanism at identity.** The blend defaults to `FORM_ANCHOR_W=0` (no-op; the current engine, value-identical). The de-bias itself is a **proposal** (`FORM_ANCHOR_W=λ*`) with re-score evidence that **Will promotes.** Auto-tune, human promotes.

---

## Why this exists

Session 5 found the root cause of most of what's wrong: **the projection center runs optimistic.** `production_vor` loses to "carry recent form forward" *every season* (negative skill) while still ranking well, and the band under-covers (~0.55 vs 0.80). Two reads, one story — the projections the engine *borrows* run high. Session 6 confirmed the entanglement empirically (the band's OOS fit wants to widen dramatically, exactly what compensating for an over-high center looks like) and correctly **held** every band dial, because tuning them now just bakes in a correction for a bias this session removes.

The fix is **not** a new projection engine (design law 3 forbids it). The engine already anchors the center toward one prior — the **preseason ADP anchor** (`ANCHOR_W`, in the band). This session adds a **second anchor**, toward **recent form** — the very signal the scorer proved *beats* the borrowed projection. It is a convex blend of two series the substrate already carries; the decision layer, not a model. One new dial (`FORM_ANCHOR_W`), tuned through the Session-6 harness on the same split, proposed with a re-score that measures the win across the three optimism symptoms.

### Verified state (what aims this session)

- **The center is `projection_consensus.center_ppr`, and both downstream reads borrow it through one shared aggregator** (`compute_production_vor._ros_values`; the band imports the same function). So a single decision-layer blend in that aggregator de-biases **both** `production_vor` and the band at once — which is the point, since the band's under-coverage is downstream of the same center.
- **The recent-form signal already has a canonical definition:** the scorer's declared `production_vor` naive `recent_ppg_forward` — *"mean(pts | wk ≤ as_of) × #realized forward weeks."* It uses only past weeks (leak-safe at the as-of), and it is the exact thing that beats the center. Anchor toward it.
- **The corpus band objective is corpus-wide as of 6b** (`_corpus_test_points`, canonical answer key, `GRADE_WEEK=4` interim). This session **re-uses it** to measure whether de-biasing the center recovers band coverage **at the frozen band dials** — the cleanest possible confirmation of the entanglement thesis.
- **Grade against canonical per-scoring-key realized points** (`player_weekly_pts_canonical`), never raw `nfl_stats.fantasy_points_ppr` — 6b showed the raw PPR column over-credits receptions for non-PPR leagues by up to ~7 pts/wk. **Flagged lead to resolve in passing:** `backtest_production_vor` and `compute_player_signal` still read the raw column as truth; confirm whether that is an intended fixed-PPR basis or a latent mis-scoring for non-PPR corpus leagues, and use canonical for this session's objective regardless.

---

## The design decisions (all mine; flagged for Will's awareness)

**1. The second anchor — a decision-layer blend in the shared ROS-center aggregator.** `debiased_ros_center = (1 − λ)·borrowed_ros_center + λ·recent_form_ros`, where `λ = FORM_ANCHOR_W`, `recent_form_ros = mean(pts | wk ≤ N) × #remaining weeks` (the `recent_ppg_forward` proxy). Placed in `_ros_values` so `production_vor` **and** the band inherit it identically. Design law 3: it is a convex blend of two existing series, not a projection model. **`λ=0` reproduces today's engine value-identically** (the equivalence proof).

**2. `FORM_ANCHOR_W` is a new registry dial (the 6th), born in the registry.** Per the Session-6 dial/pin rule, a tunable lives in `_constants.py`; this one is introduced there directly. `Tunable(name="FORM_ANCHOR_W", module="production_vor", current=0.0, grid=(0.0, 0.1, …, 1.0), gate="backtest_production_vor", objective="MAE(debiased ROS center, realized ROS canonical)", scope="scoring", coupled_gates=("backtest_ros_player_band","backtest_true_rank"), fitted_on="", last_tuned="")`. `current=0.0` so the shipped engine does not move until Will promotes.

**3. Tune λ through the Session-6 harness, on the split.** Fit on TRAIN 2020–23, certify on DEV 2024, prove on TEST 2025 + the generalization holdout — the same SplitReader discipline. Objective: minimise the de-biased center's MAE against **canonical** realized ROS points. The optimum is expected **interior** (0 < λ* < 1): pure recent form (λ=1) trades the projection's signal for form's noise, so the honest fit blends. **A suspiciously clean λ=1 is a bug until proven otherwise** (std instr 1).

**4. Ship the mechanism (λ=0), propose the value (λ*).** The autonomy contract holds: this session **proposes** `FORM_ANCHOR_W=λ*` with train-vs-holdout evidence + the re-score, and Will promotes it in a normal worktree session. The shipped engine ships at identity. *(Recommendation: propose-only. The alternative — promote λ* in-session — violates auto-tune/human-promotes and skips your review of the biggest behavioral change the engine has ever made.)*

**5. Re-score to measure the win — as a SHADOW measurement, never overwriting the frozen corpus.** At λ*, re-derive `production_vor` + the band, re-grade against the corpus answer key, and report the scorecard delta across **the three optimism symptoms**: (a) `production_vor` skill vs `recent_ppg_forward` (negative → ≥0 / center MAE down, OOS); (b) **band coverage at the frozen `BULL_Z=1.44`/`ANCHOR_W=0.25`** (~0.55 → ~0.80 *without re-widening* — the entanglement confirmed, and the residual sizes Session 8's band work); (c) the low miss-tail / PIT-at-0 mass (realized no longer falls below an over-high center → the bear tail stops breaking low). The frozen `predictions`/`resolutions`/`engine_scorecard` stay the baseline (std instr 8) — the re-score is an additive, provenanced measurement artifact, not an overwrite.

**6. Stand up seasonal delta-tracking.** Persist the predicted-vs-realized center gap per `(season, scoring_key)` — the systematic optimism magnitude each season. This is the substrate for a **seasonal** auto-update of `FORM_ANCHOR_W` (recompute the dial each time a season resolves), the honest version of Will's adaptive-coefficient idea: the optimism is a **slow, structural** bias (same direction every season, size wobbles), so a season-cadence re-fit — **not** a twitchy week-to-week one chasing fantasy's near-random noise. Track only this session; the auto-update loop itself is later, and stays propose-and-Will-promotes (a live self-adjusting dial is the loop changing shipped behavior unattended).

---

## Commit 1 — The second anchor + the `FORM_ANCHOR_W` dial (prove λ=0 is identity)

- **The blend** in `compute_production_vor._ros_values` (the shared aggregator): `(1−λ)·borrowed + λ·recent_form_ros`, `λ` read from the registry, `recent_form_ros` from realized pts through the as-of (leak-safe). Both `production_vor` and the band inherit it.
- **`FORM_ANCHOR_W` in `_constants.py`** per decision 2 (`current=0.0`).
- **Prove λ=0 is a strict no-op:** with `FORM_ANCHOR_W=0`, `production_vor` and the band recompute **value-identical** to the frozen corpus spine (std instr 2 — a refactor that moves a number is a bug). The blend is a generalization whose default IS today's engine.

> **Seam holds — no `queries.js` / view edits.** The blend is a decision-layer step inside the reads; nothing the front end reads changes (and the shipped value doesn't move — λ=0). Std instr 3.

## Commit 2 — Tune λ through the harness + the proposal + the re-score

- **Sweep `FORM_ANCHOR_W`** through the Session-6 harness on the split (decision 3), grading against **canonical** realized ROS points; re-run the coupled gates (band coverage, true-rank). Resolve the raw-PPR-vs-canonical question named in Verified state and report it.
- **The proposal** `proposals/{date}-FORM_ANCHOR_W.md`: `current 0.0 → proposed λ*`, TRAIN + HELDOUT MAE, Δ on every coupled gate, effect size, `inputs_ok`, RECOMMEND — gated by the four guardrails (holdout improves, no coupled regression, `inputs_ok`, effect > floor).
- **The re-score (decision 5)** at λ*, shadow-only: the scorecard delta across the three optimism symptoms, with the **band-coverage-at-frozen-dials** number as the headline (does fixing the center recover coverage without touching `BULL_Z`?). Report, do not promote; do not overwrite the frozen ledger/scorecard.

## Commit 3 — Delta-tracking + the gate + docs (+ scope Session 8)

- **Delta-tracking** (decision 6): persist `(season, scoring_key, predicted_center, realized, gap)` through `data_layer`, append-only, provenanced — the seasonal-auto-update substrate.
- **`check_debias` gate** (or extend `check_tuner`): the **λ=0 identity** bites (a non-zero λ that claims "no change" fails); the blend is a decision-layer op, not a projection engine (design law 3 — prove it consumes only existing series); the re-score does **not** mutate the frozen corpus; delta-tracking persists + is idempotent; determinism value-identical on a re-run. Prove each bites.
- **Docs:** `STATUS.md` (the second anchor; λ proposed not promoted; the re-score win; delta-tracking), `TECHNICAL_ARCHITECTURE.md` (the decision-layer second anchor + the seasonal-update substrate), `IMPROVEMENT_LOOP.md` (the de-bias read-improvement, tuned through L4). **Scope Session 8 (band honesty) in the closedown.**

---

## Acceptance gates

1. **λ=0 is identity** — `production_vor` + band recompute value-identical to the frozen corpus spine with `FORM_ANCHOR_W=0` (no live number moves; the mechanism ships at today's behavior).
2. **The blend is decision-layer, not a projection engine** — it consumes only existing series (borrowed center + realized recent form); design law 3 holds, proven.
3. **λ tuned honestly on the split** — fit TRAIN 2020–23, certify DEV 2024, TEST 2025 + generalization sealed; graded against **canonical** per-key points; the interior-optimum expectation checked (λ=1 interrogated, not accepted clean).
4. **The win is measured, not asserted** — the re-score reports the three optimism symptoms OOS, headlined by **band coverage at the frozen band dials** recovering toward 0.80; the frozen ledger/scorecard are untouched (shadow measurement).
5. **Auto-tune, human promotes** — `FORM_ANCHOR_W` ships at 0.0; λ* is a proposal with full evidence; nothing promoted, no band dial touched.
6. **Delta-tracking stands up** — persisted, provenanced, idempotent; the seasonal-update substrate exists (the loop itself is later).
7. **Determinism + seam** — twice-run value-identical; `queries.js` / views / the band dials untouched; the raw-PPR-vs-canonical lead reported.

---

## Out of scope

- **Session 8 — band honesty (scope it in the closedown; DO NOT start it).** Now the center is de-biased: re-tune the band width for real coverage on the corpus objective — **and this is where the Session-6/6b carry-forwards land: extend the `BULL_Z` grid upward (its 6b OOS fit was right-censored at the 1.96 ceiling), sweep `BULL_Z × ANCHOR_W` jointly (6b's were marginal 1-D fits), and make the coupled-regression guardrail real (it came back `null`/unverified in 6b).** Expect `SKEW_GAIN`→0 once the center no longer needs compensating. Swap the band's confidence signal off the percentage `ros_cv` onto the raw-points spread. Also un-freeze the band objective from `GRADE_WEEK=4` to **grade across the season's as-of weeks** (6b's week-4 was interim). Not this session.
- **Promoting `FORM_ANCHOR_W`** — the human promotes, after reviewing the proposal + re-score.
- **Re-backfilling the frozen corpus on the de-biased engine** — the frozen `predictions`/`resolutions`/`scorecard` are the baseline; a full re-backfill (if wanted) is a promotion-time follow-on, not this session.
- **The seasonal auto-update loop, the live path, the Proposer (L6).** Later track.

---

## Definition of done

- **The second anchor** ships in the shared ROS-center aggregator; `FORM_ANCHOR_W` is a registry dial at `0.0`; **λ=0 recomputes the frozen spine value-identical.**
- **λ* is tuned on the split** against canonical points, proposed with train-vs-holdout evidence + the four guardrails; the raw-PPR-vs-canonical question reported.
- **The re-score** measures the win across the three optimism symptoms OOS — band coverage recovering at the frozen band dials the headline — as a shadow measurement that leaves the frozen corpus intact.
- **Delta-tracking** persists the seasonal center gap.
- **Auto-tune, human promotes** — nothing promoted; `check_debias` green with teeth; seam held.
- **Session 8 (band honesty) scoped in the closedown — not started.**

---

> ## Standing instructions
> 1. **A suspiciously clean value is a bug until proven otherwise.** *(A λ that pins to 1.0, or a re-score win that looks too large — interrogate it; the whole point is a bias correction that generalizes, not one that overfits the fit window.)*
> 2. **A refactor that changes a number is a bug** — prove equivalence. *(λ=0 must recompute the frozen `production_vor` + band value-identical; the mechanism ships at today's behavior.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.** *(The de-bias is a decision-layer step inside the reads; no view changes, and the shipped value doesn't move until Will promotes.)*
> 4. **Report, don't promote — and don't overreach.** *(Auto-tune, human promotes. λ* is a proposal. Do not touch the band dials — that is Session 8, after this lands.)*
> 5. **Deleting/duplicating a series must not move a live number.** *(The recent-form input reuses the scorer's `recent_ppg_forward` definition — reuse it, don't re-derive a second copy that could drift.)*
> 6. **A plausible explanation is not a diagnosis** — name the mechanism, or write UNKNOWN and escalate. *(The re-score win must show band coverage recovering AT THE FROZEN DIALS — that is the mechanism proving the center was the cause, not an assertion.)*
> 7. **"The artifact exists" and "the consumer uses it" are two different gates.** *(A `FORM_ANCHOR_W` in the registry ≠ the aggregator blends by it — gate that both reads actually consume the de-biased center.)*
> 8. **Persist the substrate; never re-derive from a moving source.** *(The re-score is an additive, provenanced measurement; the frozen corpus stays the baseline. Determinism is value-equality on a re-run.)*
