# Session 5 — The Scorer (L3): the first thing in the project that judges

**Hand this file to Claude Code as the session brief.**

**Type:** L3 scorer — `compute_engine_scorecard.py` over `resolutions` + the Trust Report · **Commits:** 3
**Reads first:** `CLAUDE.md` · `IMPROVEMENT_LOOP.md` **§L3** (the four metric families are quoted there) · `PM_SESSION_STARTUP.md` (the **pre-registered predictions** — hold the engine to them) · `SESSION_4A_LEDGER_PREDICTIONS.md` + `SESSION_4B_LEDGER_OUTCOMES_RESOLUTIONS.md` (the ledger this scores; the `confidence` / primitive columns it consumes)
**Blocks:** Session 6 — the Tuner (L4), the first thing that re-fits a constant.
**Prior:** Session 4a/4b (the L2 ledger runs end-to-end — `predictions ⋈ outcomes → resolutions`, 2,893,834 resolved-or-named claims across the 270 spined league-seasons, merged to main at `a588432`).
**Reads the FROZEN `resolutions` (+ the reads' declared baselines)** — it aggregates and judges. It does **not** fetch, recompute a read, re-select, change a constant, or re-fit anything.

---

## Why this exists

Every session so far has built the machinery to *measure*. **This is the session that finally takes the measurement.** The scorer turns 2.89M graded primitives into a per-read verdict: does the engine beat its baseline, is it calibrated, and — the headline — **is its own stated confidence honest?** IMPROVEMENT_LOOP's words: *"the first real measurement the project has ever taken."*

**The scorer is the first thing allowed to judge — but it judges distributions, never single claims.** This is where Law 1 ("grade process, not outcome") becomes concrete: a single PIT of 0.97 is nothing; a *distribution* of PIT piled at 0 is a finding. The scorer emits traffic lights and an honest per-read line. It does **not** re-fit a constant (that is the Tuner, Session 6, on the proper TRAIN/DEV/TEST split) and it does **not** package a suppression or promotion proposal (that is the Proposer, L6). **Measure and report; tune nothing, promote nothing.**

**Measurement is not fitting — so the scorer scores everything.** Unlike the Tuner, the scorer has no leakage risk: it fits no parameter, so it may aggregate across *all* seasons and slices. But it **must be sliceable by season** so the out-of-sample story (does a read that looks good on 2021–2023 hold on 2025?) is visible to the human and to the Tuner that comes next. The scorer surfaces the OOS picture; the Tuner is the one bound by the split.

### Verified state (checked against the live store 2026-07-16 — grounding)

- **`resolutions` is complete and 1:1 with the claims** — 2,893,834 rows, every claim resolved (2,431,607) or **named-unresolved** (462,227, each with a reason). Primitives valid: `pit`∈[0,1], `brier`∈[0,1], `in_band`∈{0,1}; `pit` non-null **only** for interval + probability; `direction_hit`/`rank_error` populated for their families.
- **Confidence-honesty is measurable for 5 of the 9 claim families** — the ones 4a stamped with a canonical `confidence` + `confidence_label`: `ros_player_band` (`ros_cv`), `player_signal` point (`regression_risk`), `true_rank` (`spectrum_pos`), `positional_depth` (`spectrum_pos`), `bracket_odds` probability (`playoff_odds`). The **4 without** (`production_vor`, `bracket_odds` wins/seed, `player_signal` direction) carry the 4a "no native confidence" flag — law-2 is **unmeasurable** for them until a confidence signal is defined. **Report that gap; do not fabricate a confidence.**
- **A first-look finding already sits in the primitives, waiting to be formalized:** `ros_player_band` PIT is piled low (median 0.09, ~40% below 0.05) and `production_vor` median `error` is **+28.6** — two independent primitives telling the same story, **projection optimism**. The scorer's job is to formalize this (is the band's calibration failing? does the point read still beat its baseline?), **not** to fix it.
- **The naive baselines exist informally** — `backtest_player_signal` declares `naive = recent_ppg`; `backtest_bracket_sim` declares the `0.25` coin-flip Brier baseline. L3 promotes these to a **declared registry field** so `skill` computes uniformly.

---

## The design decisions (recommendations on the judgment calls — all mine to make; flagged for Will's awareness)

**1. Naive-baseline registry — promote the informal baselines to a declared field.** Each measurement read declares its naive baseline so `skill = 1 − MAE_engine / MAE_naive` computes the same way everywhere: `player_signal` → `recent_ppg` (already in `resolutions`' reach via the claim's `recent_ppg`); `bracket_odds` probability → `0.25` coin-flip Brier; `true_rank` → a random/seed-order permutation baseline; `production_vor` → `recent_ppg`-equivalent prior value; `positional_depth` → the pool-mean. Put them in a small declared map (sibling of the Session-4a constants snapshot, same "checked-in + gated" discipline) — **not** a re-implementation of each backtest. Where a read has no honest baseline, **flag it**, don't invent one.

**2. The four metric families, per `(read × slice × week)` from `resolutions`.**
   - **Skill** — MAE/RMSE vs the declared baseline; `skill = 1 − MAE_engine/MAE_naive`. *A read that stops beating its baseline out-of-sample is a red flag the Trust Report must surface* (the Tuner/Proposer act on it).
   - **Calibration** — PIT-uniformity (KS statistic) + coverage at nominal levels for the distribution reads (band interval, playoff-odds probability); Brier + a reliability curve for the probability read. Point/ordinal/direction have no PIT → calibrate them on coverage / rank-consistency, not PIT.
   - **Confidence-honesty (law 2 — the headline).** For each of the **5 confidence-bearing families**: stratify `abs_error` (or the family's native primitive) by `confidence` tier and test **monotonicity** — do high-confidence claims actually have lower realized error? **Declare each signal's polarity** (`ros_cv` ↑ = *less* confident; `regression_risk` ↑ = *less* reliable; `playoff_odds` → extreme = *more* confident, 0.5 = least; `spectrum_pos` is a proxy whose honesty is itself the question). A non-monotone read is **laundering noise as caution** — flag it red. This is the single most important number the session produces.
   - **Discrimination** — Spearman(claim, truth): does the *ranking* carry independent of the level.
   **Output entity:** `derived/engine_scorecard_{season}` (per `read × slice × week`), append-only, provenance-stamped (`code_version` + the ledger's `constants_hash` it scored) so a re-score under new constants is a distinguishable population — the L2 discipline, reused.

**3. Slices:** `league · position · week · confidence tier · signal_tier · inputs_ok · cohort (matched vs generalization) · season`. The **cohort** slice is the honest generalization test (does a read hold on the 48 `never_tune` leagues?); the **season** slice is the OOS story; the **`inputs_ok`** slice is the L1 quarantine (score the `inputs_ok=false` weeks *separately*, never blend them into a model verdict — that is the entire point of the flag).

**4. Confidence-honesty for `production_vor` — the VOR foundation — is unmeasurable, and that's a reported finding, not a hole to fill.** The most load-bearing read states no confidence, so law-2 can't grade it. **Recommendation: report the gap as a ranked read-improvement lead** ("`production_vor` ships with no confidence signal → its caution can't be validated → define one"), and do **not** derive a proxy (borrowing the band's `cv` would grade the read against confidence it never actually stated — the anti-law-2 move we've held the line on since 4a). Surfacing the gap *is* the deliverable.

**5. The scorer judges; it does not recommend a change.** It emits: a **traffic light** per `read × {skill, calibration, confidence-honesty}`, and the **"what we'd honestly tell a user"** line per read (which is also the copy the front end should eventually use). A red confidence-honesty light is a *flag*. The formal **suppression recommendation** (stop shipping this read) is the Proposer's (L6), and the **re-fit** is the Tuner's (L4). Session 5 stops at the honest verdict.

**6. Hold the engine to the pre-registered predictions** (from `PM_SESSION_STARTUP.md`): §1 signal / §5 true-rank / §6 depth should **hold** (measurement reads — *if they collapse, that's the alarm*); §3 `BAND_Z` should generalize; §2 `BULL_Z`/`ANCHOR_W` are the **open worry**; §3 `SKEW_GAIN` is **fragile**; §5 Brier degrades but stays **under 0.25**. The scorecard is where these get tested. **A surprise against a pre-registered prediction is exactly where the learning is — surface it loudly.**

---

## Commit 1 — The baseline registry + the scorecard core (skill · calibration · discrimination × slices)

- **The declared naive-baseline map** (decision 1) + a gate that cross-checks it (the checked-in-and-gated discipline from 4a's constants snapshot).
- **`compute_engine_scorecard.py`** reads `resolutions` (resolved rows only; `inputs_ok=false` and unresolved as their own quarantined slices) and computes **skill, calibration, discrimination** per `(read × slice × week)` → `derived/engine_scorecard_{season}` (append-only, provenance-stamped). Deterministic + value-identical on a re-run (`_frame_eq`, the ledger discipline).
- **Report, don't tune.** Print the per-read skill/calibration/discrimination as the first cross-corpus look; surface anything that violates a pre-registered prediction (esp. the band's low-PIT / `production_vor` optimism already visible in the primitives). Change no constant.
- **Budget** the aggregation cost + report; confirm ≈0 incremental re-score.

> **Seam holds — no `queries.js` / view edits** (standing instr 3). The scorecard is a new derived entity; the front end doesn't read it yet (the "what we'd tell a user" line is *copy for later*, not a wiring change).

## Commit 2 — Confidence-honesty (the headline) + the pre-registered check + the markdown Trust Report

- **The confidence-honesty metric** (decision 2, family 3) for the 5 confidence-bearing families, with **declared per-signal polarity**, tested for monotonicity of error across confidence tiers. **Prove the gate bites:** a deliberately anti-sorted confidence (high confidence ⇒ high error) must fail the monotonicity check.
- **Report the 4 unmeasurable families** (`production_vor`, `bracket_odds` wins/seed, `player_signal` direction) as law-2 gaps (decision 4) — named, ranked as read-improvement leads, **not fabricated**.
- **The markdown Trust Report** — per read: the traffic lights (`skill`/`calibration`/`confidence-honesty`), the **"what we'd honestly tell a user"** line, the **pre-registered-prediction check** (hold/surprise per read), and the **cohort + season OOS slices**. This is the must-have human-readable deliverable. *(Week-over-week "what moved, data vs model" attribution is a live/L6 concern — it needs an accumulating ledger + live L1 — so scope it as a placeholder here, not a build.)*

## Commit 3 — The self-contained HTML dashboard + the scorecard gate + docs (+ scope L4)

- **The Trust Report dashboard** — a self-contained HTML view over the scorecard (reuse the DuckDB-WASM / `build-dashboard` idiom already in the stack): traffic-light grid per `read × metric`, the confidence-honesty reliability view, the cohort/season slices. *(If the dashboard proves heavy, it may spill to a fast-follow "5b" — the **markdown** Trust Report in C2 is the must-have; say so in the closedown rather than cramming.)*
- **`check_scorecard`** gate (mirror `check_resolutions`), asserting: every `(read × slice)` scored or explicitly-skipped-with-reason; skill/calibration/discrimination in valid ranges; the confidence-honesty monotonicity check present for all 5 families and flagged-absent for the 4; the baseline registry cross-check bites; determinism value-identical; **Law 1 — the scorer judges only distributions, never emits a single-claim verdict** (assert no per-claim pass/fail leaks into the scorecard). Prove each bites.
- **Docs:** `STATUS.md` (the first measurement — per-read verdicts, the confidence-honesty headline, the pre-registered hits/surprises, the projection-optimism finding), `TECHNICAL_ARCHITECTURE.md` (the scorecard entity + the scorer's judge-distributions-not-claims boundary), `IMPROVEMENT_LOOP.md` (L3 built). **Scope Session 6 — the Tuner (L4) — in the closedown** (see *Out of scope*).

---

## Acceptance gates

1. **Baseline registry declared + gated** — each read's naive baseline is a checked-in field; the cross-check **bites** on a wrong baseline; no baseline fabricated where none is honest.
2. **Scorecard complete** — skill / calibration / discrimination computed per `(read × slice × week)` across the 270 league-seasons; `inputs_ok=false` and unresolved are **separate quarantined slices**, never blended into a model verdict.
3. **Confidence-honesty measured + gap reported** — monotonicity tested for the 5 confidence-bearing families with declared polarity; the 4 without are **named law-2 gaps**, not fabricated; the anti-sorted prove-bite fails.
4. **Pre-registered predictions checked** — each read scored against its pre-registered expectation; hits and **surprises surfaced loudly**.
5. **Law 1 structural** — the scorer judges **distributions**; no single-claim verdict exists in the scorecard; prove-bite fires.
6. **Report, don't tune / don't promote** — no constant changed, no read re-fit, no suppression/promotion proposal packaged (those are L4/L6). The scorer stops at the honest verdict + the user-facing line.
7. **Determinism + provenance** — twice-score value-identical; the scorecard is provenance-stamped (`code_version` + the scored ledger's `constants_hash`).
8. **Trust Report delivered** — markdown (must-have) with traffic lights + the honest per-read line + the OOS/cohort slices; the HTML dashboard (this session or a named 5b). **Seam held.**

---

## Out of scope

- **Session 6 — the Tuner (L4) (scope it in the closedown; DO NOT start it).** The constant registry (`transforms/_constants.py` — promote the 4a snapshot), the `--sweep` harness generalized, and the **split discipline** the scorer deliberately doesn't enforce: **fit on TRAIN 2020–2023 · dev 2024 · TEST 2025** (season-wise) **and** fit on leagues A–M · **holdout the generalization cohort** (league-wise). Re-tune all five constants (`BAND_Z`, `SKEW_GAIN`, `BULL_Z`, `ANCHOR_W`, `OPP_HALF_LIFE_WK`) **out-of-sample**, write `proposals/{date}-{constant}.md` with train-vs-holdout evidence + the four guardrails, and — **the contract — auto-tune, human promotes.** The scorer hands the Tuner its targets (the worst confidence-honesty / skill slices); the Tuner is the first thing that re-fits, and only on the proper split. *(The band's low-PIT / projection-optimism finding is a Tuner lead, not a Session-5 fix.)*
- **The Proposer (L6) — suppression / promotion recommendations, the weekly digest.** Session 5 flags a law-2 breach; L6 packages the recommendation to stop shipping.
- **Any constant change, read recompute, re-fit, or re-selection.** The reads, substrate, and ledger are frozen (verify value-identical if read).
- **The live path / `data_health` entity / AI-read eval (L5).** Live concerns; the scorer consumes the offline `inputs_ok` slice as-is.
- **Wiring the "what we'd tell a user" line into the front end.** It is *copy produced for later*; no `queries.js`/view change here.

---

## Definition of done

- A **declared, gated naive-baseline registry**; `compute_engine_scorecard.py` producing `engine_scorecard_{season}` (skill · calibration · confidence-honesty · discrimination) per `(read × slice × week)`, provenance-stamped, deterministic.
- **Confidence-honesty measured** for the 5 confidence-bearing families (declared polarity, monotonicity, prove-bite) and the 4 gaps **reported, not fabricated**; `production_vor`'s missing-confidence surfaced as a ranked read-improvement lead.
- The **pre-registered predictions tested**, hits + surprises surfaced; the projection-optimism finding formalized (measured, not fixed).
- **Law 1 holds** — distributions judged, no single-claim verdict; **report, don't tune** — no constant/read/proposal touched.
- `check_scorecard` **green with teeth**; the **markdown Trust Report** delivered (HTML dashboard this session or a named 5b); seam held.
- **Session 6 (the Tuner, L4) scoped in the closedown — not started.**

---

> ## Standing instructions
> 1. **A suspiciously clean value is a bug until proven otherwise.** *(A read that scores perfectly calibrated — PIT flat, skill high — on the first try, especially on the TEST season, is suspicious, not triumphant. Interrogate it.)*
> 2. **A refactor that changes a number is a bug** — prove equivalence. *(The scorer reads frozen `resolutions`; re-scoring must be value-identical.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.** *(The scorecard is a new derived entity; the "what we'd tell a user" line is copy for later, not a wiring change.)*
> 4. **Report, don't tune — and don't promote.** *(The scorer measures + flags. It changes no constant (L4), packages no suppression/promotion (L6). A law-2 breach is a finding, not a fix. This is the central discipline of the session.)*
> 5. **Deleting dead code must not move a live number.**
> 6. **A plausible explanation is not a diagnosis** — name the mechanism, or write UNKNOWN and escalate. *(A read that fails confidence-honesty: name whether the signal is mis-polarized, too coarse, or genuinely noise — don't hand-wave "confidence is bad.")*
> 7. **"The artifact exists" and "the consumer uses it" are two different gates.** *(A `confidence` column present ≠ it sorts by realized error. Gate the honesty, not the column.)*
> 8. **Persist the substrate; never re-derive from a moving source.** *(The scorer reads the frozen ledger; determinism is value-equality on a re-run; the scorecard is provenanced by `code_version`/`constants_hash`, never file bytes.)*
