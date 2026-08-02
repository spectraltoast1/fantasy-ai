# Project 4 — Live 2026 AI Outlook (Bull / Bear / Situation)

**Created:** 2026-07-26 · **Updated:** 2026-07-31 — **the read is re-keyed from league-scoped to player-week global** (Will's call; see "The keying decision" below, and the rewritten S1) · **Status:** Not started · **Track:** Can-be-late (**best candidate to be late**) · **Depends on:** P1 (news collection), P2 (live season) · **Est:** 2–3 sessions

> **What this project does:** populate the per-player **bull / bear / situation** "AI outlook" grades from
> **live 2026 news**, and do it *honestly*. These grades render empty today (the old ones were a
> 2026-news-against-2025 POC, now retired). Will chose to have them live at launch — so this project ships
> the grades **and** the guardrails that keep them trustworthy. Design source: `../post-v1/ai-outlook-trust.md` — P4 ships its V1 slice; the full trust build (first-class divergence column, champion/challenger on the prompt) is the post-V1 remainder there.

---

## Context — the read is two things wearing one coat

`ai-outlook-trust.md` establishes the key insight, and it shapes the whole project:

- **Bull / bear have a deterministic core.** `ros_player_band` already produces `ros_bull` / `ros_bear` as
  real, calibrated numbers (`ros_center ± BULL_Z·ros_sigma`, anchored to preseason ADP). This part is
  backtestable and already in the measurement corpus.
- **Situation is irreducibly AI.** Role security, depth-chart moves, committee risk — from forward-only
  beat-writer RSS (`player_news_slice`). This is the part no number can produce, and the **least-verifiable
  output in the whole product** — there is no historical RSS to backtest it against, ever.

`ros_synthesis` is the Claude call that (a) rescales the band into 1–10 grades and (b) fuses the situation
news. The honesty implication: the more the **band** carries the load, the less trust rides on the model.

## The keying decision (Will, 2026-07-31) — compute the AI read **per player-week, not per league**

**This is the single biggest cost decision in P4, and it must be made before S1 writes a line of code.**

Today `write_ros_synthesis` is **league-scoped by design** — its own docstring says *"This writer is
league-scoped (its grades depend on league-relative anchor inputs)."* That means one AI call per rostered
player per league per week, so cost scales with **leagues × rosters × weeks**. At self-serve scale that is
the only line item in the whole product that grows with users (Fly compute does not — see
`sessions/v1/P5-Self_Serve/SESSION_P5_S0_REPORT.md`).

**Will's call: the player-level read is not league-specific and should not be computed per league.** He's
right, and the architecture already contains the pattern. Decompose what the synthesis fuses:

| input | actually league-specific? |
|---|---|
| `player_news_slice` (the news layer) | **No** — globally true for every league |
| `ros_player_band` (the band anchor) | **No** — already **scoring-keyed** substrate, computed once per scoring profile and stamped with a `league_id` only at COPY time |
| `ros_league_view` (the league-relative anchor) | **Yes** — this, and only this, is league-specific |

So two of the three inputs are already shareable, and one of them (`ros_player_band`) is *already shared* by
exactly the mechanism proposed here. `projection_consensus` works the same way. **This is not a new pattern
— it is an existing pattern that `ros_synthesis` was left out of.**

**The shape to build:**

1. **A global player-week AI read.** Top ~300 players by relevance, once per week, scoring-key scoped if the
   grades prove scoring-sensitive (the same scoping `projection_consensus` uses). Produces the news
   interpretation, *situation*, and the absolute bull/bear read. This is the only thing that costs tokens.
2. **A deterministic league-relative adjustment.** No AI. Positions the global read against a given league's
   context using `ros_league_view`, preserving the league-relative design rather than discarding it.

**What it saves.** Roster-wide-per-league is ~180 players × N leagues × 18 weeks. Player-week-global is
**~300 × 18 ≈ 5,400 calls per season, total, regardless of how many leagues connect.** The cost stops
scaling with users entirely — which converts R4 from a live risk into a fixed line item.

**Why now, and why it's free to decide.** `ros_synthesis` currently serves **0 rows** and is "empty by
design" in the loader — nothing has been built against the expensive shape yet, so this costs no rework
today and would cost a rebuild later. **Decide it here; S1 builds it this way from the start.**

**The one thing to verify in S1, not assume:** whether the grades are genuinely scoring-sensitive. If a
player's bull/bear reads the same in PPR and half-PPR, the read is fully global (one set). If it doesn't,
it's scoring-keyed (two sets) — still league-independent, still ~2× not ~N×. **Measure it; don't guess.**
Note the standing rule: a refactor that changes a number is a bug unless the change is bounded, explained,
and proven — so if this re-keying moves any grade, name exactly what may move and prove it.

## The honesty stance (non-negotiable — this is the R2 guardrail)

Will's north star is **confidence-honesty**, and the pilot plan says the AI half "can only earn trust
forward, live" and should be "most conservative about what it's allowed to say" until the Week-8 gate. So
this project is only "done" if it ships with:

- The grade **anchored to the deterministic band**, with a **first-class divergence column** (band-implied
  grade vs. AI grade) logged — systematic divergence is either a prompt bug or a real signal, both are
  leads.
- **Confidence shown, not hidden** — a low-confidence grade must visibly say so, and *situation* must be
  presented as a **different (lower) trust class** than the calibrated bull/bear number, not the same kind
  of clean 1–10.
- Grounding preserved — headlines trace to cited article ids (`check_ros_synthesis` already enforces this).

## Session map

| Session | Goal | Scope | Definition of done |
|---|---|---|---|
| **S1 — Player-week live run (re-keyed 2026-07-31)** | Grades populate for every connected league off ONE shared computation | Re-key the read **per player-week, not per league** (see "The keying decision"): a global top-~300 AI pass over live 2026 `player_news_slice` + the scoring-keyed band anchor, plus a **deterministic** league-relative adjustment via `ros_league_view`. Verify whether grades are scoring-sensitive (→ one set or two) rather than assuming. Wire the batch runtime | Bull/bear/situation grades render for a connected league off live news, computed **once globally** rather than per league; the call count is independent of how many leagues are connected, demonstrated |
| **S2 — Consistency + guardrails** | Reproducible and honest | `news_content_hash` cache (the seam already exists) + temperature 0 + `prompt_version`; add the **anchor-divergence** column; confidence gating; present situation as a distinct trust class in `PlayerCard.jsx` | Same inputs → same grade week to week; divergence logged; situation visibly lower-trust; low-confidence grades self-flag |
| **S3 — Cost cap + runtime** | Bounded and refreshable | Cost controls on the AI runtime (grades only re-compute when news/prompt changes — the cache does this); a refresh cadence tied to the news collector | AI cost is bounded and predictable as leagues grow; grades refresh when the news actually changes |

## Decisions to settle

- **How much may the AI move the band?** A hard clamp on `|grade − band-implied grade|`, or free-but-logged?
  (Recommend: start clamped/conservative for launch, loosen later once divergence data exists.)
- **Trust-class presentation** — how visibly to separate the calibrated bull/bear from the AI situation on
  the card (badge, wording, a separate section). A design call.
- **Champion/challenger on the prompt** (loop L5) — **defer to post-V1**; not worth the per-player cost yet.

## Risks / can't-generalize

- **R2 — shipping an un-validated confidence signal before the Week-8 gate.** The mitigation is the guardrails
  above, not avoidance. If they slip, gate the panel off ("no rest-of-season outlook yet") rather than show
  ungated grades — this is why the project is designated can-be-late.
- **Cost scales with invited leagues — SOLVED BY THE RE-KEYING, not by the cache.** The ~$85/season figure
  was ~10 slices and it grew with every connected league. Computing per player-week instead of per league
  makes the call count **independent of user count** (~5,400/season flat), which turns R4 from a scaling risk
  into a fixed line item. The `news_content_hash` cache + cost cap (S3) then trim that fixed number further.
  **The re-keying is the fix; the cache is the optimisation.** Do not rely on the cache alone.
- **Depends on P1 reliability** — a live news read is only as trustworthy as the daily news collection under
  it. Don't turn this on before P1's soak clears.
- **The situation half never gets a historical answer key** — be permanently conservative about what it
  asserts; the full trust build (champion/challenger, richer divergence analysis) is post-V1.

## Critical files

`ai/write_ros_synthesis.py` (**the league-scoping lives here — this is where the re-keying lands**) + the
`ai/client` runtime seam; `ros_synthesis` read path; `compute_ros_player_band.py` (the band anchor, and the
working example of scoring-keyed-shared substrate to copy); `compute_ros_league_view` (the one genuinely
league-relative input — becomes the deterministic adjustment); `serve/build_db.py` (`ros_synthesis` moves
from the 12 league-keyed datasets toward the scoring-keyed pattern used by `projection_consensus` /
`ros_player_band`); `player_news_slice` (news input, fed by P1); `frontend/src/PlayerCard.jsx` (trust-class
presentation).

## Definition of done (project)

Bull/bear/situation grades render for connected 2026 leagues off live news, are reproducible week to week,
are anchored to the calibrated band with divergence logged, and present situation as a visibly lower trust
class. **Ship the guardrails, not just the grades.** Late-plan: target early in-season; if launch is tight,
gate the panel honestly and turn it on once P1 is proven and the guardrails are in.
