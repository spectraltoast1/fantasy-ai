# Project Overview

> The "why" and "what" of this project. Constitution document — read this first when picking the project up after time away.

---

## Problem

Fantasy football decisions (start/sit, waivers, trades) currently require either hours of manual research across many sources, or off-the-shelf advisor tools that produce generic answers without my league context, my reasoning preferences, or transparent justification.

Manual research is time-expensive. Off-the-shelf tools are intellectually flat.

---

## What This Is

A personal AI fantasy football advisor and analytics dashboard, organized as two halves of one product:

1. **An AI advisor** that grounds its recommendations in a curated strategy document — synthesized from a structured interview with the user about their fantasy football beliefs — applied against live data fetched from multiple sources, with full transparency into the reasoning used.
2. **An analytics dashboard** that does its own work independent of the AI: market value trends, projected scoring trajectories, advisor output history, waiver-target rankings, roster construction views.

The two halves share a common data layer (cached fetches + time-series snapshots + advisor output log). The dashboard is a peer product to the AI, not a viewer for it.

---

## Who It's For

Single user. Built for ownership and transparency, not commercialization. The user runs multiple Sleeper leagues across redraft / dynasty / salary cap formats; the v1 focus is the redraft league.

This may eventually generalize, but multi-user concerns are explicitly out of scope until the single-user version is proven.

---

## Why This Exists

Three reasons, ranked:

1. **Decision quality through curated reasoning.** Off-the-shelf tools optimize for consensus rankings. This system optimizes for *the reasoning patterns I personally find most defensible*, expressed as transferable rules in a strategy document I author.
2. **Ownership.** I want a tool that I built, that I understand, that I can extend, and that doesn't change underneath me when a vendor pivots.
3. **Practice with LLM-as-orchestrator architecture and applied data work.** This is also a sandbox for working with the patterns: pre-filtered context, structured outputs, narrow API surfaces, time-series persistence, and lightweight analytics.

---

## V1 Success Criteria

V1 is "done" when ALL of these are objectively true:

1. **`application/strategy/strategy_redraft.md` exists**, produced via a structured Claude-driven interview covering every position, decision type, and applicable league format
2. **The data fetchers run on schedule**, persist current-state caches, and write time-series snapshots for the data that supports the dashboard's trend views
3. **The advisor loads the strategy doc** and uses it in every API call (no more raw context-dump pattern); it logs every call to `application/data/advisor_log/` with timestamp + input snapshot + question + response
4. **At least one specialized advisor type works end-to-end** — start/sit is the v1 minimum. Waiver, trade, and ad hoc generator may follow but are not v1 gates.
5. **The dashboard renders** at least the following panels: roster status, last week's matchup result, market value trend chart for roster players, recent advisor outputs, one analytical view (e.g., waiver-target ranking by market value rank, roster bye-week stack)
6. **API costs are tracked** and per-output-type cost is documented

V1 is **NOT** judged by:
- Whether the advice is correct (out-of-season, can't measure end-to-end)
- Polish beyond the criteria above
- Edge case completeness

**Target ship:** by NFL kickoff (early September 2026).

---

## V1 Non-Goals (Explicitly Out of Scope)

This list captures every tempting feature that could derail v1. Add to this list when new "wouldn't it be cool" ideas surface.

- **Transcript synthesis pipeline.** Deferred to v2; preserved in `_deferred/synthesis_pipeline/`. The strategy doc for v1 is interview-authored, not synthesized.
- **Token vocabulary contract.** Lives with the synthesis pipeline; not load-bearing for v1.
- Live in-season feedback loop (deferred V2)
- Multi-user support
- Coverage-tendency reasoning requiring PFF data
- Monte Carlo simulations (lineup, playoff odds, trade impact)
- NWS forecast integration if v1 timeline is tight (decision pending)
- Real-time advice during live games
- Mobile app or hosted web service
- Auth, sharing, accounts
- Best ball, auction draft formats
- K and DEF as deeply analyzed positions (Vegas-driven streaming only; K is included in fetched data for completeness but receives weak-confidence advice)
- LLM-coached "season simulator" that plays the season
- Beating the prop bet market
- General-purpose chatbot UI outside the defined output types

---

## Project Values

The things I care about, in priority order. Use these to break ties on architecture or scope decisions.

1. **Reasoning transparency over output polish.** The advisor must show its work. A clean justification beats a confident one-liner.
2. **Curation over consensus.** This system reflects my views (informed by creators I trust). It is not a meta-aggregator and should not pretend to be neutral.
3. **Cost discipline.** Predictable, narrow API calls. Pre-filtered context. The LLM is a reasoner, not a data parser.
4. **Single source of truth.** Each fact lives in exactly one document. Constitution docs (this, the roadmap, the architecture) hold current state. The journal records evolution.
5. **Sequential clarity over parallel ambition.** Build one slice end-to-end before perfecting any layer.
6. **The dashboard is a peer product.** It is not "a UI for the AI" — it is an analytics tool in its own right that happens to share a data layer with the AI.

---

## Reading Order for New Sessions

1. `STATUS.md` (project root) — current state in one paragraph
2. This file (`PROJECT_OVERVIEW.md`)
3. `PRODUCT_ROADMAP.md` — for what's next
4. `TECHNICAL_ARCHITECTURE.md` — for how things work
5. The two most recent journal entries in `journal/` — for what just happened

The constitution docs change rarely. The journal changes every session.

If a future session is tempted to revive transcript synthesis or the token vocabulary contract: read `_deferred/synthesis_pipeline/README.md` first. That work is paused on purpose.
