# Project 4 — Live 2026 AI Outlook (Bull / Bear / Situation)

**Created:** 2026-07-26 · **Status:** Not started · **Track:** Can-be-late (**best candidate to be late**) · **Depends on:** P1 (news collection), P2 (live season) · **Est:** 2–3 sessions

> **What this project does:** populate the per-player **bull / bear / situation** "AI outlook" grades from
> **live 2026 news**, and do it *honestly*. These grades render empty today (the old ones were a
> 2026-news-against-2025 POC, now retired). Will chose to have them live at launch — so this project ships
> the grades **and** the guardrails that keep them trustworthy. Design source: `../post-v1/ai-outlook-trust.md` — P4 ships its V1 slice; the full trust build (first-class divergence column, champion/challenger on the prompt) is the post-V1 remainder there.

---

## Context — the read is two things wearing one coat

`BULL_BEAR_SITUATION_TRUST.md` establishes the key insight, and it shapes the whole project:

- **Bull / bear have a deterministic core.** `ros_player_band` already produces `ros_bull` / `ros_bear` as
  real, calibrated numbers (`ros_center ± BULL_Z·ros_sigma`, anchored to preseason ADP). This part is
  backtestable and already in the measurement corpus.
- **Situation is irreducibly AI.** Role security, depth-chart moves, committee risk — from forward-only
  beat-writer RSS (`player_news_slice`). This is the part no number can produce, and the **least-verifiable
  output in the whole product** — there is no historical RSS to backtest it against, ever.

`ros_synthesis` is the Claude call that (a) rescales the band into 1–10 grades and (b) fuses the situation
news. The honesty implication: the more the **band** carries the load, the less trust rides on the model.

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
| **S1 — Roster-wide live run** | Grades populate for connected 2026 leagues | Run `write_ros_synthesis` across rostered players consuming **live 2026** `player_news_slice`; wire the on-demand/batch runtime | Bull/bear/situation grades render for a connected league off live news |
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
- **Cost scales with invited leagues** — the ~$85/season figure was ~10 slices; self-serve grows it. The
  cache + cost cap (S3) is what keeps it flat-ish.
- **Depends on P1 reliability** — a live news read is only as trustworthy as the daily news collection under
  it. Don't turn this on before P1's soak clears.
- **The situation half never gets a historical answer key** — be permanently conservative about what it
  asserts; the full trust build (champion/challenger, richer divergence analysis) is post-V1.

## Critical files

`ai/write_ros_synthesis.py` + the `ai/client` runtime seam; `ros_synthesis` read path;
`compute_ros_player_band.py` (the band anchor); `player_news_slice` (news input, fed by P1);
`frontend/src/PlayerCard.jsx` (trust-class presentation).

## Definition of done (project)

Bull/bear/situation grades render for connected 2026 leagues off live news, are reproducible week to week,
are anchored to the calibrated band with divergence logged, and present situation as a visibly lower trust
class. **Ship the guardrails, not just the grades.** Late-plan: target early in-season; if launch is tight,
gate the panel honestly and turn it on once P1 is proven and the guardrails are in.
