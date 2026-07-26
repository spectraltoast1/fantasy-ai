# Session 6 — The Tuner (L4): the first thing that re-fits a constant — honestly

**Hand this file to Claude Code as the session brief.**

**Type:** L4 tuner — constant registry + one sweep harness + the split discipline + the proposal artifact · **Commits:** 3
**Reads first:** `CLAUDE.md` · `IMPROVEMENT_LOOP.md` **§L4** (the registry / split / proposal spec is quoted there) · `PM_SESSION_STARTUP.md` (the pre-registered predictions the tuner tests) · `SESSION_5_L3_SCORER.md` (the scorecard this reads; the findings that aim it)
**Blocks:** Session 7 — the de-bias read-improvement (it will be tuned *through* this harness).
**Prior:** Session 5 (the scorer — `engine_scorecard`, the first measurement: projection optimism, band under-coverage, the inverted band confidence, §1's thin margin; merged to main).
**Reads the FROZEN scorecard + resolutions + the reads' backtests** — it re-fits constants on a disciplined split and **writes proposals**. It does **not** merge a constant, change a read, or promote anything.

---

## Why this exists

The scorer measured; now something has to be able to *improve* a number — but only in a way that can't fool itself. The tuner is the machinery that re-fits a constant **on data it then proves itself against on data it never saw.** It is the piece the whole "corpus-first" bet was for: for the first time the engine's constants can be retuned **out-of-sample, offline, before a single live week.**

**Two things make this session load-bearing beyond its own output:** it is the durable machinery *every* future fix runs through (the de-bias, the band-widening, every seasonal re-tune), and it is the first place the **autonomy contract** becomes real — **the loop auto-tunes and proposes; it never promotes.** Every constant change leaves here as a reviewed proposal with train-vs-holdout evidence, and *you* merge it in a normal worktree session.

**Build the machinery; don't chase the findings yet.** The scorer handed us a clear diagnosis (projection optimism, and a band whose problems are all downstream of that optimistic center). The temptation is to point the tuner straight at the band and start widening/skewing. **Resist it** — and the tuner's first real job is to *explain why*: nearly every band constant is entangled with the not-yet-fixed center, so tuning them now would compensate for a bias we're about to remove. The honest first run tunes the one clean knob, **holds** the rest with a named reason, and proposes the de-bias as the top lead. The machinery's opening act is to hand back the right order.

### The split discipline (this is the whole point — it is what makes re-fitting honest)

- **Season-wise:** fit on **TRAIN 2020–2023**, tune on **DEV 2024**, and do not touch **TEST 2025** until the very end. A constant that only helps on the data it was fit to is overfit and must not ship.
- **League-wise:** fit on the matched tuning cohort, **hold out the 48 `never_tune` generalization leagues** — a genuinely unseen *shape* (superflex, division, custom) is the only honest test of an any-league constant.

Both are available offline, now. **Report, don't overreach — the guardrails below are the law.**

### Verified state (from the L5… L3 scorecard, 2026-07-16 — what aims the tuner)

- **Projection optimism is real and stable** (`production_vor` loses to "carry recent form" every season; band covers ~0.55 vs 0.80). This is a **center** problem — *not* fixable by the band constants, and the reason the band constants are held this session.
- **The measurement reads hold out-of-sample** (§5 solid, §6 modest, §1 thin-but-positive, playoff Brier 0.11–0.14). Don't touch what's working.
- **Pre-registered predictions to test:** `SKEW_GAIN` suspected **overfit** (test toward 0); `BULL_Z`/`ANCHOR_W` the **open worry** (do they hold OOS?); `BAND_Z` expected to generalize; §1's `OPP_HALF_LIFE_WK` is the one clean, center-independent knob to actually tune this session.
- **The constants exist as a checked-in snapshot** (4a's `constants_snapshot.py`) — this session promotes it to a real tunable registry and, in doing so, resolves the recorded `BULL_Z` drift (snapshot `1.44` vs STATUS's narrated `1.645`) by making the registry the single source of truth.

---

## The design decisions (all mine; flagged for Will's awareness)

**1. Constant registry — promote the 4a snapshot to `transforms/_constants.py`.** Each tunable declared once: `Tunable(name, module, current, grid, gate, objective, fitted_on, last_tuned, scope)`. This is the config seam TECHNICAL_ARCHITECTURE already flagged as coming; it kills the drift class of bug outright (the modules import from the registry, so STATUS-vs-code disagreement becomes impossible). **The registry is the single source of truth; the `BULL_Z` drift is resolved here by declaring the real value, not by re-tuning it blind.**

**2. One sweep harness — replace the five ad-hoc `--sweep` flags.** A single driver that, given a `Tunable`, sweeps its grid, fits on TRAIN, certifies on DEV, and (only at the end, once) reports TEST — and runs the *same* re-fit for any constant. No bespoke per-constant tuning path.

**3. The split is enforced structurally, not by good intentions.** The harness must make it *impossible* to read TEST during fitting (e.g., TEST is a withheld partition the fit code cannot see). Prove it bites: a fit that peeks at 2025 fails a gate.

**4. The proposal artifact — `proposals/{date}-{constant}.md` + a machine-readable row.** `constant · current → proposed · TRAIN metric · HELDOUT metric · Δ on every other gate · effect size · inputs_ok over the fit window · RECOMMEND / HOLD`. The tuner **writes** this; it never edits a transform. **Auto-tune, human promotes.**

**5. The four guardrails — a proposal is RECOMMEND only if all four hold** (else HOLD, with the reason): (a) the **holdout** improves — not the train metric; (b) **no other gate regresses** beyond tolerance — constants are coupled (`BAND_Z` → VOR → true-rank → bracket-odds), so the sweep must re-run the sibling gates and check them; (c) `inputs_ok` over the whole fit window; (d) the effect exceeds a **minimum** — don't churn constants for noise.

**6. The disciplined first run — tune §1, HOLD the band, propose the de-bias.** Sweep `OPP_HALF_LIFE_WK` (§1) and RECOMMEND if it clears the guardrails on holdout (the clean proof the harness works). Sweep `BAND_Z`/`BULL_Z`/`ANCHOR_W`/`SKEW_GAIN` too — but **HOLD every one** with the named reason: *"entangled with the optimistic center (L3); a change now compensates for a bias Session 7 removes — revisit post-de-bias."* Confirm the entanglement rather than assert it (e.g., show `SKEW_GAIN`'s apparent benefit tracks the center bias). The session's headline proposal is **"de-bias the center first"** — the tuner's first act is to sequence its own work correctly.

---

## Commit 1 — The constant registry + the split-aware sweep harness (prove the split bites)

- **`transforms/_constants.py`** — promote every constant from the 4a snapshot to a `Tunable` (name/module/current/grid/gate/objective/fitted_on/last_tuned/scope); repoint the modules to import from it (equivalence: the imported value == the current in-code value, so **no live number moves** — standing instr 2). Resolve the `BULL_Z` drift by declaring the real `1.44` and noting it in the registry.
- **The sweep harness** — one driver that sweeps a `Tunable`'s grid, fitting on **TRAIN 2020–2023**, certifying on **DEV 2024**, TEST 2025 **withheld** (structurally unreadable during fit), plus the **league-wise holdout** (generalization cohort withheld from fit). 
- **Prove the split bites:** a fit that reads TEST, or that certifies on TRAIN instead of the holdout, **fails a gate**. A harness that can silently peek is not honest.

> **Seam holds — no `queries.js` / view edits, and no transform edits** (the tuner writes proposals, it doesn't touch reads). Standing instr 3.

## Commit 2 — The first sweep + the proposal artifact + guardrails

- **`proposals/{date}-{constant}.md` + machine-readable row** per decision 4, gated by the four guardrails (decision 5) — including **re-running the sibling gates** to catch coupled regressions.
- **Run it (decision 6):** sweep `OPP_HALF_LIFE_WK` → RECOMMEND or HOLD on the guardrails; sweep the four band constants → **HOLD each** with the entanglement reason; emit the **"de-bias the center first"** lead as the top-ranked proposal. Report train-vs-holdout for each, and the pre-registered-prediction check (is `SKEW_GAIN` overfit? do `BULL_Z`/`ANCHOR_W` hold OOS? — report even though held).
- **Report, don't promote / don't overreach.** Every output is a proposal with evidence. Change no transform, merge no constant. If a sweep suggests a tempting band change, the guardrail + the entanglement HOLD is the discipline — surface it, don't ship it.

## Commit 3 — The tuner gate + docs (+ scope Session 7)

- **`check_tuner`** gate: every proposal carries its full evidence row (train + holdout + sibling-Δ + effect size + inputs_ok + RECOMMEND/HOLD); a proposal that improves only TRAIN, or regresses a coupled gate, or falls under the effect-size floor is **rejected/HELD** — prove each bites (a train-only "win," a coupled regression, a noise-sized effect each force HOLD; a peeking fit fails). Determinism value-identical on a re-run.
- **Docs:** `STATUS.md` (the tuner exists; the registry; the `BULL_Z` drift resolved; the first-run proposals — §1 tuned, band held, de-bias recommended), `TECHNICAL_ARCHITECTURE.md` (the constant registry + the split harness + auto-tune/human-promotes), `IMPROVEMENT_LOOP.md` (L4 built). **Scope Session 7 (de-bias) in the closedown.**

---

## Acceptance gates

1. **Registry is the source of truth** — modules import from `_constants.py`; the imported values equal the pre-change in-code values (**no live number moves**); the `BULL_Z` drift is resolved by declaration.
2. **The split is structural + proven** — TEST 2025 and the generalization cohort are unreadable during fit; a peeking fit fails a gate.
3. **The harness is general** — one driver re-fits any `Tunable`; no bespoke per-constant path survives.
4. **Proposals carry full evidence + the four guardrails bite** — train-only wins, coupled regressions, sub-threshold effects, and peeking fits are each rejected/HELD (prove each).
5. **First run is disciplined** — §1 tuned on holdout; all four band constants **HELD** with the entanglement reason; **de-bias proposed as the top lead**; pre-registered predictions reported.
6. **Auto-tune, human promotes** — no transform edited, no constant merged, nothing promoted. The tuner only writes proposals.
7. **Determinism + seam** — twice-run value-identical; `queries.js` / views / reads untouched.

---

## Out of scope

- **Session 7 — the de-bias read-improvement (scope it in the closedown; DO NOT start it).** Add the recent-form shrinkage dial to the projection center (a decision-layer blend — the engine already anchors toward ADP; this adds a second anchor toward recent form, which the scorer showed is *beating* the projection), tune it **through this harness** on the split, and stand up the **delta-tracking** that will later drive a seasonal auto-update of the dial. Re-score to measure the win across the three optimism symptoms.
- **Session 8 — band honesty (after the de-bias):** re-tune the band width for real coverage (now the constants are untangled from the corrected center — expect `SKEW_GAIN` toward 0) **and** swap the band's confidence signal from the percentage measure (`ros_cv`) to the raw-points spread. Not this session.
- **Promoting any constant.** The human promotes, in a normal worktree session, after reviewing the proposals.
- **The Proposer (L6), AI eval (L5), the live path / `data_health`.** Later track.
- **Re-fitting on the test set, or any read / substrate / scorecard change.** Frozen inputs (verify value-identical if read). The tuner re-fits constants *on the split*, and proposes — nothing more.

---

## Definition of done

- **`transforms/_constants.py`** is the single source of truth (modules import it; **no live number moved**; `BULL_Z` drift resolved).
- **One split-aware sweep harness** re-fits any `Tunable` on TRAIN, certifies on DEV/holdout, withholds TEST **structurally** (peeking fails a gate) — plus the league-wise generalization holdout.
- **Proposals** carry train-vs-holdout + coupled-gate deltas + effect size + `inputs_ok` + RECOMMEND/HOLD, gated by the four guardrails (each proven to bite).
- **First run:** §1 tuned; the four band constants **HELD** (entanglement reason); **de-bias proposed as the top lead**; pre-registered predictions reported.
- **Auto-tune, human promotes** — nothing merged/promoted; `check_tuner` **green with teeth**; seam held.
- **Session 7 (de-bias) scoped in the closedown — not started.**

---

> ## Standing instructions
> 1. **A suspiciously clean value is a bug until proven otherwise.** *(A constant whose holdout metric improves *too* cleanly, or a sweep that recommends a big change on thin evidence — interrogate it; the whole session exists to not fool itself.)*
> 2. **A refactor that changes a number is a bug** — prove equivalence. *(Promoting constants into the registry must leave every live number identical — the import equals the old in-code value.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.** *(The tuner writes proposals; it edits no read and no view.)*
> 4. **Report, don't promote — and don't overreach.** *(Auto-tune, human promotes. Every output is a proposal. The band constants are HELD, not shipped, however tempting the sweep looks — the entanglement with the center is the reason.)*
> 5. **Deleting dead code must not move a live number.** *(Retiring the five ad-hoc `--sweep` flags into the one harness must not change what they computed.)*
> 6. **A plausible explanation is not a diagnosis** — name the mechanism, or write UNKNOWN and escalate. *(A held band constant: show the entanglement with the center, don't just assert it.)*
> 7. **"The artifact exists" and "the consumer uses it" are two different gates.** *(A registry on disk ≠ the modules import it. Gate that the live read actually reads the registry value.)*
> 8. **Persist the substrate; never re-derive from a moving source.** *(The tuner re-fits against the frozen scorecard + resolutions; determinism is value-equality on a re-run; proposals are provenanced, never merged silently.)*
