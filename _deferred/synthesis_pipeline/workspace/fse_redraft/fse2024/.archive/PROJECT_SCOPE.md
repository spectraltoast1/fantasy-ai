# Project Scope — Fantasy Football AI Advisor

**Status:** Draft (V1 scope, finalized 2026-05-08)
**Owner:** Will Daniel
**Mirror:** [Product connector — TBD which tool]

---

## Problem Statement

Fantasy football decision-making (start/sit, waivers, trades) currently relies on either:
1. **Hours of manual research** across multiple sources (rankings, projections, news, matchups, market values)
2. **Off-the-shelf advisor tools** that return generic answers without using my specific league context, my reasoning preferences, or transparent justification

Neither option is satisfying. Manual research is time-expensive; off-the-shelf tools are intellectually flat.

**This project builds an advisor I own end-to-end** — one whose reasoning is grounded in strategy patterns I've explicitly curated from creators I trust, applied against live data, with full transparency into why each recommendation was made.

---

## Who This Is For

**Primary user:** me. Single user. One redraft fantasy league.

**Not for:** other people, multiple leagues, public consumption, monetization. The architecture happens to be generalizable, but v1 is single-user.

---

## V1 Goals

1. **A working strategy mind** — synthesized markdown files capturing reasoning patterns from curated YouTube transcripts, tagged with applicability and data dependencies.
2. **Three predictable advisor outputs** — start/sit, waivers, trades. Each returns a structured recommendation with stated rationale and the rules invoked.
3. **One open-ended advisor output** — ad hoc prompt generator that returns (data plan, prompt) for paste into a separate Claude session.
4. **A limited-interactive dashboard** — visualizations of my team's status, recent advisor outputs, and key data signals.
5. **Cost discipline** — predictable API costs through narrow, pre-filtered API calls.

---

## V1 Non-Goals (Explicitly Out of Scope)

These are things I might want eventually but will NOT build in V1:

- **Live feedback loop.** Logging recommendations vs. outcomes and using them to improve the strategy mind. Deferred to V2 because we're currently out-of-season — no live signal exists.
- **Multi-league support.** Roster/league context is single-user only.
- **Coverage-tendency reasoning** (man/zone splits). Requires PFF data which is not in the free stack. Rules referencing it will be tagged `[paywalled]` and either skipped or proxied.
- **Monte Carlo simulations.** Lineup MC, playoff odds MC, trade impact MC — all interesting V2/V3 features. Premature for V1.
- **NWS weather forecast integration** — flagged but TBD on whether v1 includes it. Decision: TBD before Pass 1 runs against FSE redraft batch.
- **Real-time live game feedback during games.** Advisor is pre-game / between-week only.
- **Mobile app or hosted web service.** Local dashboard only. No Vercel, no AWS.
- **A user account system, auth, sharing features.** Single-user local tool.
- **Best ball, salary cap, or auction draft formats.** Standard redraft only.
- **K and DEF as deeply analyzed positions.** Streaming logic from Vegas + spread; no specialized data layer for K/DEF.
- **Drafting an LLM-coached "season simulator"** that plays an entire season for me. Tempting but not v1.
- **Trying to beat the market on actual NFL prop bets.** This is a fantasy advisor, not a betting tool.
- **A general-purpose chatbot interface.** The 4 output types are the surface area. No free-form conversation outside those.

This list will likely grow as decisions get made. Adding to it is a sign of healthy scope discipline.

---

## V1 Success Criteria

V1 is "done" when ALL of these are true:

1. **All four strategy MD files exist** with v2 prompt quality (rule quality forms A–D, applicability tags, data dependency tags), produced by the three-pass pipeline.
2. **The data orchestrator is implemented** for all `available` tokens in the vocabulary. Mocks acceptable for `gap` tokens, with explicit fallback behavior documented.
3. **The three fixed advisor types each return structured output** for at least 5 test cases against historical data. Test cases come from prior seasons where the right answer is knowable in retrospect.
4. **The ad hoc generator produces a (data_plan, prompt) pair** that I can successfully paste into a Claude session and get a useful answer.
5. **The dashboard renders** at least: current team roster status, last week's matchup result, recent advisor outputs (timestamped with input snapshot), and one data-driven chart that I find genuinely useful (TBD which one).
6. **API costs are tracked** and per-output-type cost is documented. Cost discipline is itself a v1 deliverable.

V1 is **NOT** judged by:
- Whether the advice was correct (we can't measure correctness yet — out of season)
- Whether the output looks "polished" beyond the success criteria above
- Whether every edge case is handled

---

## Phasing

### Phase 1 — Strategy Mind (current phase)
**Status:** in progress
**Deliverable:** Four strategy MD files (flock_dynasty, flock_redraft, fse_dynasty, fse_redraft) produced by the three-pass v2 pipeline.

Sub-phases:
- 1a. Lock data token vocabulary against actual planned Python fetcher names ← NEXT
- 1b. Run Pass 1 on FSE redraft batch (largest, last remaining)
- 1c. Optionally re-run Pass 1 on prior 3 batches with v2 prompts
- 1d. Run Pass 2 (3x at temp 0.3–0.5) + merge for each batch
- 1e. Run Pass 3 against each merged file

### Phase 2 — Data Orchestrator
**Deliverable:** Python fetchers for every `available` token; mocks/fallbacks for gaps.

### Phase 3 — Advisor APIs
**Deliverable:** Four output types implemented end-to-end with logging.

### Phase 4 — Dashboard
**Deliverable:** Streamlit + Altair limited-interactive dashboard.

### Phase 5 — V1 Validation
**Deliverable:** Run advisor against historical test cases. Document cost-per-call. Confirm success criteria.

---

## Key Risks

1. **Strategy mind quality is the leverage point.** If the synthesis pipeline produces flat or generic output, every downstream advisor is mediocre. This is why we're investing heavily in v2 prompt quality before bulk execution.

2. **Out-of-season validation is necessarily synthetic.** We can't truly test advisor quality until next season. Mitigation: test against historical decisions where we know the outcome retrospectively.

3. **API cost surprises.** The three-pass pipeline plus merge runs across 4 batches at Opus rates is ~$70-100. Runtime cost is TBD. Mitigation: track costs per call from day one.

4. **Token vocabulary churn.** If fetchers get renamed mid-build, Pass 3 outputs become invalid. Mitigation: lock vocabulary BEFORE Pass 3 runs.

5. **Scope creep via "wouldn't it be cool if..."** This is the enthusiastic-builder failure mode. The non-goals list above is the primary defense. Update it whenever a new tempting feature shows up.

6. **Single-LLM-session context loss.** The journal is the mitigation. Keep it updated.

---

## Dependencies

### Data sources (see data_sources.txt for details)
- LeagueLogs (free) — market values
- Sleeper (free) — roster/league/projections
- nfl_data_py (free) — production stats, NGS
- The Odds API (free + paid budget) — Vegas lines and props
- FantasyPros (paid plan) — projections + news
- NFL official (free) — practice and inactives
- NWS (free, TBD integration) — weather forecast
- datawithbliss (free, one-time extract) — stadium locations only

### LLM dependencies
- Claude API (Anthropic SDK)
- Sonnet for extraction and tagging
- Opus for synthesis and merge

### Code dependencies
- Python 3.11+
- httpx, nfl_data_py, anthropic, streamlit, altair, plotly, duckdb (when needed)

---

## Open Questions to Resolve Before Phase 2

- [ ] Should NWS forecast integration land in v1 or v2?
- [ ] Should we re-extract the earlier 3 batches with v2 prompts, or accept v1 quality?
- [ ] What specific historical test cases will we validate v1 against?
- [ ] Which Product connector are we mirroring this scope into?
- [ ] What's the budget tolerance for the Pass 2 + merge step on Opus across 4 batches (~$70-100)?

---

## Definition of "Done" for This Document

This document is "done" enough when:
1. The non-goals list captures every tempting-but-out-of-scope feature I can think of
2. Success criteria are objectively checkable (no soft language)
3. Phases are sized so I can complete each in 1–3 sessions
4. Open questions have a clear path to resolution

It is NOT meant to be exhaustive. It's meant to be **conviction-tested**. If reading this back makes me think "wait, why am I doing this?" — that's a signal to refine, not abandon.
