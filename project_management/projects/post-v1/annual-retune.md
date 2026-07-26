# The Annual Re-Tune — Turn the Calibration Exercise into a Yearly Script

**Last reviewed:** 2026-07-18 · **Status:** Scope / design doc — **not yet started.** The offline/annual instance of the improvement-loop's **L6 Proposer** (`engine improvement/IMPROVEMENT_LOOP.md`).

> **Verdict:** The week-long calibration exercise (Sessions 4–8c) was almost entirely a *build*, not a *tune* — the corpus, the ledger, the scorer, the tuning harness, the dial registry, and every dial mechanism are permanent machinery. The **annual re-tune is a re-run, not a re-build**: ingest the newly-resolved season, roll the walk-forward split forward one year, re-score, sweep every registered dial through the existing harness, and emit a **proposal digest with options**. Wired into one orchestrated command, what took a week collapses to an afternoon that ends exactly where a human should pick up — a ranked "here's what the data wants, and here are your options" report. The only parts that stay human are the two that *are* judgment: **promoting** the proposals you accept, and **interpreting surprises**. This doc scopes the orchestration driver + the digest generator; both sit on top of code that already exists.

> **Origin:** produced 2026-07-18 from a review of Sessions 1–8c and the modules they left behind (`corpus/harvest.py`, `compute_spine.py`, the `backfill_*`/`compute_resolutions` ledger, `compute_engine_scorecard.py` + `trust_report.py`, `corpus/tuner.py`, and the `transforms/_constants.py` dial registry).

---

## What recurs vs. what was one-time

The exercise felt enormous because the machine was being invented while it ran. Separate the two and the recurring part is small:

**One-time — the machine (built; never repeat):**
- Corpus keying, harvest, and the frozen substrate (Sessions 0–3e).
- The ledger schema — `predictions ⋈ outcomes → resolutions` (4a/4b).
- The scorer + Trust Report (5).
- The tuning harness + split discipline + guardrails + the dial registry (6/6b).
- Every dial *mechanism* — the recent-form anchor, the asymmetric band, `CENTER_SHRINK`, delta-tracking (7/8/8b/8c).

**Recurs — the operation (run every offseason, once season N resolves):**
1. **Ingest season N** — harvest the new league-seasons, compute the 5-read spine, backfill `predictions`/`outcomes`/`resolutions` for N.
2. **Re-score** — run the scorer → updated `engine_scorecard` + Trust Report.
3. **Roll the split forward** — the recency-windowed walk-forward advances one year (N joins the fit window; N−1 becomes the dev season; **N is the fresh, never-seen test** — no manual editing).
4. **Sweep every registered dial** through the harness on the rolled split → per-dial proposals with train/holdout evidence + the four guardrails.
5. **Assemble the digest** — the ranked "recommendation with options" report (below).
6. **Human promotes** the proposals worth shipping.

Steps 1–5 are what this doc automates. Step 6 is, and should stay, yours.

---

## The pipeline (one driver wiring existing modules)

`python3 -m application.data.corpus.annual_retune --season N` runs, in order:

| Stage | Reuses | Note |
|---|---|---|
| **Ingest** | `harvest` · `compute_spine` · `backfill_predictions`/`backfill_outcomes` · `compute_resolutions` | idempotent, provenance-stamped; re-run appends the new season, never overwrites prior years |
| **Score** | `compute_engine_scorecard` · `trust_report` | a new `constants_hash`/`code_version` population — the frozen prior years stay the baseline |
| **Split** | new: a `walk_forward(season)` helper | recency window → (TRAIN, DEV, TEST) + the league-wise generalization holdout, derived, not hand-set |
| **Tune** | `corpus/tuner.py` over `transforms/_constants.py` | sweeps **every dial in the registry** — so coverage grows automatically as dials migrate in under the dial/pin rule |
| **Digest** | new: `annual_digest.py` (the L6 Proposer) | assembles the proposals + the options narration → one report |

Nothing in stages 1–4 is new engineering — it is orchestration over modules that already carry their own gates. The two genuinely new pieces are the `walk_forward` split helper and the digest generator.

---

## The deliverable — the proposal digest *with options*

This is the thing that took a week of back-and-forth to produce by hand; the digest reproduces it in a fixed shape. Two layers, matching L6's design (**the data ranks; AI narrates; the human decides**):

**Layer 1 — the deterministic proposals** (straight from the harness, no AI): per dial, `current → proposed`, TRAIN vs HELDOUT metric, Δ on every coupled gate, effect size, `inputs_ok`, and **RECOMMEND / HOLD** against the four guardrails. Ranked by leverage. This is fully mechanical and reproducible.

**Layer 2 — the options narration** (AI, grounded in Layer 1, never deciding): for each RECOMMEND that carries a real choice, a plain-English "**here's what promoting this does, here are your options, here's the trade-off**" — exactly the framing you worked through this year (honest-and-lower vs market-matching; 0.7 vs 0.8; promote-the-pair vs hold). AI only narrates forks the numbers already surfaced; it proposes nothing the data didn't rank.

**Plus a Surprises section** — the most valuable half-page. Any pre-registered prediction that *broke* (the S7 de-bias null, the center-shrink finding, a dial that flips sign year-over-year) gets flagged loudly, because a surprise is where the learning — and the human judgment — lives. The digest can *detect and present* a surprise; it cannot decide what it means.

The digest ends with a **promote checklist**: the accepted proposals, the exact `_constants.py` diff, and the equivalence to prove (what may move, what must not) — so promotion is a short, reviewed worktree session.

---

## What automates, and what stays human (the honest line)

The pipeline gets you to the *recommendation with options* — the point you reached this week after days of work. It does **not** make the calls that follow, and shouldn't:

- **Promotion stays human** (the autonomy contract — the loop proposes, you merge). Non-negotiable: a self-promoting annual dial is the loop changing shipped behavior unattended.
- **Interpreting surprises stays human.** When a pre-registered prediction breaks, the digest flags it; *what to do* (re-sequence the roadmap, try a different lever, change product positioning) is judgment. This year that judgment was the whole game — the de-bias null redirected everything, and honest-and-lower vs market-matching was a product call no script can make.

So the realistic promise is not "push a button, ship a tuned engine." It is "**push a button, get the exact briefing packet you spent a week assembling** — then spend an afternoon deciding and a short session promoting."

---

## Build plan (a future session or two — not urgent)

1. **`walk_forward(season)` + the driver** — the recency-window split helper (encodes the fit-window policy we settled on) and the `annual_retune` orchestrator over the existing stages. Prove the split still can't peek (the S6 structural guarantee holds as the window rolls).
2. **`annual_digest.py` (L6 Proposer, offline)** — Layer 1 assembly from the proposal artifacts + the AI options narration + the Surprises detector (diff this year's dial fits / verdicts against last year's) + the promote checklist.
3. **A dry-run gate** — run the pipeline on the *existing* corpus with the split rolled back one year and confirm it reproduces this year's proposals (a regression test that the automation matches the hand-run).

**Dependencies / notes:** the digest's coverage equals the registry's coverage, so migrating the remaining dials in (dial/pin rule, on first tune) widens the annual sweep over time. The live-path L1 `data_health` (the pilot track) makes the "was the input clean?" attribution in the digest real; until then the digest assumes clean inputs and says so.

---

## Out of scope

- The **live/in-season** instance of L6 (the weekly digest) — related, but a different cadence and a different input (`served=true` + data_health); its own track in `PILOT_2026.md`.
- **Automating promotion** — deliberately excluded; the human-in-the-loop is the design, not a gap.
- **Re-building any stage** — this is orchestration + a digest over existing, gated modules.
