# The 2026 Pilot — Test Plan

**Created:** 2026-07-12 · **Rewritten:** 2026-07-12 — *the corpus changed what this is for*
**Current as of: 2026-08-03** — cohorts A+B collapsed into one word-of-mouth cohort held by a shared access
code; the week-4 gate survives as a **checklist, not a boundary** (see *Cohorts*). **Status:** current.

> **Why this stamp exists.** This doc's cohort plan was reasoned from as authoritative *after* Will's intent
> had changed, and a P5 session brief was written from the stale reading — costing a session. Per
> `CODING_BIBLE` §7, an appendix past the last project boundary is **stale by default**: confirm its claims
> before acting on them, and **re-stamp this date** when you do.
**Companions:** [`engine-corpus.md`](./engine-corpus.md) · [`engine-improvement-loop.md`](./engine-improvement-loop.md) · [`_deprecated/audits/712_BACKEND_AUDIT.md`](../_deprecated/audits/712_BACKEND_AUDIT.md)

---

## What changed, and why this doc got much smaller

The first draft of this plan was built on a premise the **league corpus retires**:

> ~~"Leagues, not users, are the binding constraint. Recruit 6–8 leagues for statistical power."~~

Statistical power is now a **backfill** problem, not a **recruitment** problem. Ten harvested
league-seasons give you ~500 team-seasons and ~3,750 matchups **offline, before kickoff, with nobody's
help.** Recruiting live leagues to get *n* would be paying in support burden for something you can
simply download.

**So the pilot is no longer a data-gathering exercise.** Its purpose collapses to exactly the four
things the corpus **cannot** produce — and nothing else.

---

## The pilot's entire remaining job

| The corpus **cannot** give you | Because | The pilot must |
|---|---|---|
| **1. News-anchored §2** (`ros_synthesis` grades) | `team_news_raw` is **forward-only RSS** — you cannot retrieve 2021 beat-writer feeds. The AI half of §2 is **un-backtestable, forever.** | Grade the grades **forward**, live, all season. |
| **2. Market VOR / `trade_gap` (§4)** | LeagueLogs snapshots start **2026-05-31**. Un-backdatable (STATUS already says so). | Run it live and finally get a real answer key. |
| **3. Live collector reliability** | 65% coverage is a *host* problem, not a data problem. | Prove ≥95% off-laptop, under real conditions. |
| **4. Served-decision behaviour** | decision-touch, divergence, who-was-right. | Needs actual humans making actual moves. |

Everything else — §1, §3, §4-production, §5, §6, §7 — is **already graded and retuned offline** by the
time week 1 starts.

**⇒ The pilot needs the smallest cohort that exercises those four. That's 2–3 leagues and ~5 people.**
Not 6–8 leagues and 15.

---

## The frame that still holds

**2026 is the validation season, not the growth season** — but now for a *narrower* claim.

The corpus will have already retuned `BAND_Z`, `SKEW_GAIN`, `BULL_Z`, `ANCHOR_W`, `OPP_HALF_LIFE_WK`
out-of-sample across seasons *and* leagues (audit S2.1). So the quantitative reads walk into 2026 with
**earned** constants for the first time.

What 2026 tests is what only 2026 *can* test: **does the engine hold up when it's live, when the news is
real, when the market is moving, and when a human is about to act on it?**

Expect regressions anyway. Pre-commit to reading them as measurements, not bugs — that reflex doesn't get
easier with a corpus.

---

## Cohorts

> **REVISED 2026-08-03 (Will).** Cohorts A and B are **collapsed into one cohort**: word-of-mouth friends,
> onboarding at the draft. The staged A→B ramp is gone; what holds Cohort C back is now a **shared access
> code**, not a calendar. The original A/B text is preserved below as *why the staging existed*, because one
> thing it carried is still load-bearing — see *The week-4 checklist* — but **it is no longer the plan.**

### The one cohort — Will's league + word-of-mouth friends · **~10–15 leagues** · onboard at draft (late Aug)

Will qualifies **one** league of his own; friends extend it to roughly 10–15 leagues total. Discovery is
word of mouth — Will is not driving unknown people to the site. **Provisioning is self-serve**: signup is
open, and completing it requires a **shared access code** Will hands out however he's already talking to the
person. He never does per-user work. Forwarding the code is explicitly fine — a friend passing it to a
league-mate *is* word of mouth. A leak is answered by rotating the code, not by cleanup.

> Still true, and still worth doing: get **more than one scoring key** into that first wave (PPR + half).
> Not for statistical power — the corpus has that — but because it is the only way to prove the live
> `scoring_key` path before anyone trusts a number. **This is not idle caution: P5/S0 found
> `weekly_refresh._resolve_scoring_key` silently falling back to the *owner's* key for any league not yet in
> the catalog** — i.e. every user league. That is the exact collision the week-4 gate was written to catch.

> Note the inversion the original plan drew, which survives intact: **the corpus wants leagues; the pilot
> wants *decisions*.** A second manager in a league Will already runs is worth more to the pilot than a whole
> new league — and costs almost nothing.

### The week-4 checklist — the gate survives, the boundary does not

Cohort A existed so data-quality bugs surfaced on Will's own leagues *before* anyone else saw a number.
Collapsing A into B means friends see the product during exactly those weeks. **That is a deliberate trade,
not an oversight** — they're friends, expectations are calibrated by that, and S4a's honesty work already
withholds what a thin sample can't support (no clinch magic number, no trend direction, no posture map under
three weeks). *(The posture **chip** is no longer a thin-sample question: P5/S2e withheld `posture` outright,
at every sample size, because the metric is inverted — see STATUS.)*

**But the value of that gate was never the boundary — it was the list.** So it stays, as a checklist Will
runs at week 4 regardless of who is looking:

- [ ] **No scoring-key collision** — every connected league resolves its *own* key, not the owner's.
- [ ] **No anchor-fusion bug** — the prior-season anchor is flagged, never silently fused.
- [ ] **Collector health ≥95%**.
- [ ] **Every connected league resolving** — no silent partial slices.

### Cohort C — strangers · **still held back** · now held by the access code
**Gate:** unchanged — the week-8 engine gate. Shipping an uncalibrated confidence signal to a stranger is a
law-2 violation with a real person on the other end. **What changed is only the mechanism:** the code is what
keeps a stranger who finds the URL from getting in. *Do not publish the code publicly, and do not market.*

*(Consent: your stance is that public Sleeper data is fair game, and for the corpus that's a coherent
position — you're reading completed public seasons and nobody is being served anything. It gets less
abstract when a stranger is **using** the product and their leaguemates are being **profiled by name** in
§7. Worth revisiting at Cohort C, not before.)*

---

## What to measure

### Family 1 — Engine · *the live-only half*

Most of the engine table from the first draft has **moved to the corpus**, where it's answered offline.
What's left is what only live data can settle:

| Metric | Read | Status | 2026 target |
|---|---|---|---|
| **Confidence honesty** — mean \|error\| **monotone** across confidence tiers | §2 AI grades, §4 market | **never measurable before** | **monotone by week 8** |
| Do `bull` / `bear` / `situation` grades predict realized ROS ceiling / floor / stability? | §2 AI | never measured | rank-correlation > 0 and rising |
| Grounding: headline→article traceability, prose-leak rate | §2 AI | checked, never *trended* | no drift across prompt versions |
| `trade_gap` signal: does Market ≫ Production actually precede a sell-high? | §4 | un-backtestable | **first honest read ever** |
| Collector health | infra | **65%** | **≥95% of days complete** |
| *(all quantitative reads)* | §1/§3/§5/§6 | **retuned OOS on the corpus** | **hold their corpus-certified numbers live** ← the real test of the corpus |

That last row is quietly the most important: **does a constant tuned on 2021–2025 leagues still work in
2026?** If yes, the corpus method is validated and you can trust it every year. If no, you've learned
something enormous.

### Family 2 — Product · *programmatic, zero user burden*

You already fetch Sleeper transactions, so the best product metrics cost nothing and require asking
nobody anything:

- **Decision touch** — % of a user's actual adds/drops/trades/lineup changes the tool had flagged the week
  before. *Did it see the decision coming?*
- **Divergence + adjudication** — how often the user acted **against** the read… **and who turned out to be
  right.** Fully automatic, and it's the honest scoreboard for a consultation product. It is also the
  fastest way to find where the engine is *confidently wrong*.
- **Read-before-lock** — did they open it before lineup lock? (The only new front-end instrumentation
  needed: a minimal usage log.)

> **No target for decision-touch in year 1.** You have no baseline. A threshold without one is theatre.
> Measure it to *establish* the baseline; set targets in 2027.

### Family 3 — Trust · *the only thing you ask a human for*

**One question. Once a week.**

> *"Did this change a decision this week? Y / N — and one line on why."*

Add a second question and they stop answering the first.

---

## Go / no-go gates

| When | Gate | Fail → |
|---|---|---|
| **Pre-kickoff** | Corpus retune complete; all quantitative reads certified **out-of-sample**; ledger schema live. | You are shipping unearned constants. Don't. |
| **Pre-kickoff** | Live path writes `served=true` rows for Cohort A. Collectors off-laptop. | **Do not onboard anyone.** An un-instrumented week is unrecoverable. |
| **Week 4** | Data quality: no scoring-key collision, no anchor-fusion bug, health ≥95%, every connected league resolving. | Fix before trusting any downstream number. **(Revised 2026-08-03: a checklist Will runs, not a cohort boundary — the A/B collapse removed the boundary, not the list.)** |
| **Week 8** | **THE ENGINE GATE.** §2 AI confidence honesty monotone **and** the corpus-tuned quantitative reads holding their certified numbers live. | **Do not open Cohort C. Do not market.** The gate exists to be obeyed. |
| **Week 12** | Decision-touch baseline established; divergence-adjudication has readable *n*. | Re-scope the surface, not the engine. |
| **Season end** | Fold 2026 into the corpus. Retune on 6–7 seasons. | This is now an *annual* ritual, not a one-off. |

---

## Timeline (today: 2026-07-12 · drafts: late Aug · kickoff: Sept)

| Window | Track A — offline (the value) | Track B — live |
|---|---|---|
| **Jul 12 – Jul 26** | L0 keying · **corpus harvester** · probe 2020 projections | — |
| **Jul 26 – Aug 16** | Ledger schema (backfilled) · **scorer** · **retune all constants OOS** | — |
| **Mid–late Aug** | *Fix what the corpus broke* (superflex / division / custom scoring **will** break something) | Move collectors off-laptop |
| **Late Aug (draft)** | corpus frozen for the season | Onboard **the one cohort** — Will's league + word-of-mouth friends (~10–15 leagues, mixed scoring), self-serve behind the access code. Verify `served=true` rows. |
| **Weeks 1–4** | — | Live path bedding in. **Week-4 data-quality checklist** (above). |
| **Weeks 4–8** | — | L5 AI eval + champion/challenger on §2. *(No cohort step here any more — everyone is already in.)* |
| **Weeks 8–18** | — | L6 proposer. Cohort C **only if** the week-8 gate passed — i.e. don't publish the code or market. |
| **Post-season** | Fold 2026 in · retune on 6–7 seasons | — |

**The recruiting window (late Aug, draft season) still matters — but it matters much less now.** You need
a handful of people, not a handful of leagues. If you miss it, the corpus still carries the year.

---

## Risks that survived the reframe

1. **You will read the first honest regression as a bug.** The corpus makes this *more* likely, not less —
   because now you'll have retuned constants and a real expectation, and 2026 will still surprise you.
2. **Support burden is the hidden cost — and the corpus is what lets you avoid it.** ~5 people × 18 weeks
   is manageable. 15 people is not. Take the win.
3. **§2's AI half never gets a historical answer key. Ever.** It is structurally the least-validated read
   in the product and it is also the most *visible* one (prose grades, headlines, confidence). Be
   correspondingly conservative about what it's allowed to say until it has earned a season.
4. **Cost is not a risk.** ~$85/season, flat across leagues. Champion/challenger doubles it to ~$170. Don't
   let it shape a single decision.

---

## The pilot in one line

> The corpus answers *"are the engines right?"* **before** the season.
> The pilot answers only what a season can: *"are they right when it's live, the news is real, and someone
> is about to act on it?"* — with **2–3 leagues and ~5 people**, not fifteen.
