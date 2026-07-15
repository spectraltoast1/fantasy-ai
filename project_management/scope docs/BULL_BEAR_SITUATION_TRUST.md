# Bull / Bear / Situation — Making the §2 Read Trustworthy

**Status:** design note — a **SEPARATE, FUTURE project.** NOT part of the corpus improvement-loop sessions
(3a/3b/3c → ledger → scorer → tuner). It overlaps the loop's **L5 (AI eval)** track and the live pilot, but
is scoped on its own and should be picked up as its own initiative.
**Created:** 2026-07-15
**Entities in play:** `ros_player_band` (deterministic substrate) · `ros_synthesis` (the AI grades) ·
`ros_league_view` (league-relative anchor) · `player_news_slice` (the news input).
**See also:** `engine improvement/IMPROVEMENT_LOOP.md` (L5) · `DECISION_READS.md` (§2).

---

## The problem

The §2 "ROS Outcome Shape" read — the per-player **bull / bear / situation** grades on the player card — is
"an AI read disguised as a number." What the user sees as three clean 1–10 numbers is `ros_synthesis`, a
per-player Claude call. The goal is to make this read **as consistent and trustworthy as possible.** The
premise worth testing: *"there's no way to deliver that without an AI prompt."*

The conclusion of this note: that premise is **only true for part of the read**, and even that part can be
made consistent and honest-about-its-limits.

---

## The key insight — it's two reads wearing one coat

**Bull/bear has a deterministic core. Situation is the irreducibly-AI part.**

- **`ros_player_band` (deterministic, scoring-scoped, already frozen).** `ros_bull` / `ros_bear` =
  `ros_center ± BULL_Z·ros_sigma`, floored at 0 and blended toward the preseason ADP anchor. This is a **real
  number** — backtestable, already calibrated (balanced miss tails ~0.091 below-bear / ~0.091 above-bull),
  and tunable (`BULL_Z`, `ANCHOR_W`). No AI required.
- **`ros_synthesis` (AI).** A Claude call that (a) **rescales** the band into the 1–10 grades and (b) **fuses
  situation news** (`player_news_slice`) to produce `bull_grade` / `bear_grade` / `situation_grade` +
  `confidence`.

So **bull and bear are fundamentally a distribution question** the band already answers as a number. **Situation
is a news question** — role security, depth-chart moves, injuries, committee risk — that can't be derived from
projections at all, and needs forward-only beat-writer RSS. That is where the AI is irreplaceable; a
keyword-rules "situation score" would be *less* trustworthy, not more.

---

## What is trustworthy-able WITHOUT AI (the band)

The bull/bear band is deterministic, calibratable, and **already in the measurement corpus** (the frozen
scoring-scoped substrate, graded via `BULL_Z` / `BAND_Z`). The corpus/tuner certifies its ceiling/floor
**offline, before kickoff.** The design move is to make the band **carry maximum load** — the more the number
does on its own, the less the read leans on the model.

## What is irreducibly AI (situation + the news-nudge)

Situation, and the news adjustment to bull/bear, depend on `player_news_slice`, which is forward-only RSS —
**un-backtestable offline** (there is no historical beat-writer feed to grade against). This is the one part
of the whole engine the corpus can *never* certify.

---

## Consistency is solvable even with a model in the loop

An AI read can be made **reproducible** — same inputs, same number — without removing the AI:

- **Cache the grade on `(player, news_content_hash, prompt_version, anchor)`.** The `news_content_hash` seam
  **already exists** in `write_ros_synthesis` (its comment calls it "the seam for the future on-demand cache
  — not yet a trigger"). Wire it: the grade only changes when the news or the prompt actually changes.
- **Temperature 0** + **structured output** (the grades are already typed parquet columns, not parsed prose).
- **Version the prompt** (`prompt_version`, already specified in the loop) so a grade change is always
  attributable to a news change or a prompt change — never drift.

Result: week-to-week consistency, which is most of what "trustworthy" means day to day.

---

## Trustworthy = anchored + confidence-honest + grounded (not AI-free)

Three moves, each of which the loop already gestures at:

1. **Anchor the grade to the band, and log divergence.** The grade should be a **bounded adjustment** on the
   deterministic band, not a free invention. Log every case where the AI grade diverges from its band anchor
   (IMPROVEMENT_LOOP Track 3). Systematic divergence is *either* a prompt bug *or* a sign the band is missing
   something real — both are leads. **Divergence isn't a first-class column today; adding it is the
   highest-value first step.**
2. **Confidence-honesty (design law 2).** The read may speak only when its confidence is *earned* — high-
   confidence grades must show **lower realized error** than low-confidence ones, and the read must be
   **suppressible** when they don't. The flags exist (`confidence` / `has_news` / `has_ros_anchor`); the
   scorer measuring error-stratified-by-confidence does not yet.
3. **Grounding.** Headlines must trace to cited article ids — `check_ros_synthesis` already enforces this;
   keep it.

---

## The asymmetry that should shape expectations

- **The band** is certifiable **offline, before kickoff**, on the corpus.
- **The situation/AI half** can only earn trust **forward, live in 2026** — no historical RSS. It is the
  **least-verifiable output in the engine**, which is exactly why the design should be **most conservative**
  about what it is allowed to assert.

This is not a flaw to engineer away; it's a property to respect. Note that the corpus architecture **already
splits the read along this fault line** — the band stays in the measurement corpus, `ros_synthesis` is
descoped to the live/L5 track. This note is the reasoning behind that split, written down.

---

## What the corpus CAN do for this read (even without grading the AI)

**Measure the band's standalone load.** How well does the *deterministic band alone* sort realized ROS
outcomes across the corpus? If it sorts well, the AI is a **low-risk garnish** with bounded failure. If the
band is weak and the grade is doing the real work, **that is where trust risk concentrates.** This is
answerable offline, and it reframes the whole question from *"can I trust the AI read"* into *"how much am I
even leaning on the AI versus the number underneath it"* — which is something you can put a number on before
you ever rely on the model live.

---

## Scope boundary (explicit)

- **Not** part of Sessions 3a/3b/3c or the ledger/scorer/tuner. Those correctly **descope `ros_synthesis`**
  (forward-only) and keep only the deterministic band in the measurement corpus.
- This is a **separate project**, most naturally run alongside the loop's **L5 (AI eval)** track and the live
  pilot, since the situation half can only be graded forward.

## Sketch of the work when it's picked up

- Wire the `news_content_hash` cache + temperature 0 + `prompt_version`.
- Add a first-class **anchor-divergence** column (band-implied grade vs AI grade).
- Wire the **confidence-honesty** scorer slice for the grades (error stratified by `confidence`; suppress when
  non-monotone).
- Presentation: make the **situation** grade visibly signal its confidence and be suppressible — don't let it
  masquerade as the same kind of number as the calibrated band.

## Open questions

- How much should the AI be allowed to move the band — a hard clamp on `|grade − band-implied grade|`, or free
  with divergence logged?
- Should bull/bear (a calibrated number) and situation (a confidence-flagged AI read) be presented as
  **visibly different trust classes** on the card?
- Is champion/challenger on the prompt (loop L5) worth the cost for a per-player read?
