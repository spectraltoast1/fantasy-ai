# Project Overview

> The "why" and "what" of this project. Constitution document — read this first when picking the project up after time away.

---

## Problem

Fantasy football decisions (start/sit, waivers, trades) currently require either hours of manual research across many sources, or off-the-shelf advisor tools that produce generic answers without my league context, my reasoning preferences, or transparent justification.

Manual research is time-expensive. Off-the-shelf tools are intellectually flat.

---

## What This Is

A personal AI fantasy football advisor that grounds its recommendations in a curated "strategy mind" — markdown rules synthesized from fantasy football YouTube creators I trust — applied against live data from multiple sources, with full transparency into the reasoning used.

Three predictable advisor outputs (start/sit, waivers, trades) handle most decisions. A fourth output (ad hoc prompt generator) packages a custom data plan and prompt for use in a separate Claude chat session.

A limited-interactive dashboard provides visibility into roster status, recent advisor outputs, and key data signals.

---

## Who It's For

Single user. One redraft fantasy league. Built for ownership and transparency, not commercialization.

This may eventually generalize, but multi-user / multi-league concerns are explicitly out of scope until the single-user version is proven.

---

## Why This Exists

Three reasons, ranked:

1. **Decision quality through curated reasoning.** Off-the-shelf tools optimize for consensus rankings. This system optimizes for *the reasoning patterns I personally find most defensible*, expressed as transferable rules rather than player-of-the-week takes.
2. **Ownership.** I want a tool that I built, that I understand, that I can extend, and that doesn't change underneath me when a vendor pivots.
3. **Practice with LLM-as-orchestrator architecture.** This is also a sandbox for working with the patterns: pre-filtered context, structured outputs, narrow API surfaces, multi-pass synthesis.

---

## V1 Success Criteria

V1 is "done" when ALL of these are objectively true:

1. **All four strategy MD files exist** — produced by the three-pass v2 pipeline, including data-dependency tags
2. **The data orchestrator is implemented** for every `available` token in the vocabulary; `gap` tokens have documented fallback behavior
3. **The three fixed advisors return structured output** for at least 5 historical test cases each, where retrospective correctness is checkable
4. **The ad hoc generator produces a working (data_plan, prompt) pair** that I can paste into a separate Claude session to get useful output
5. **The dashboard renders** roster status, last week's matchup result, recent advisor outputs (timestamped with input snapshot), and at least one data-driven chart
6. **API costs are tracked** and per-output-type cost is documented

V1 is **NOT** judged by:
- Whether the advice is correct (out-of-season, can't measure)
- Polish beyond the criteria above
- Edge case completeness

---

## V1 Non-Goals (Explicitly Out of Scope)

This list captures every tempting feature that could derail v1. Add to this list when new "wouldn't it be cool" ideas surface.

- Live in-season feedback loop (deferred V2)
- Multi-league / multi-user support
- Coverage-tendency reasoning requiring PFF data
- Monte Carlo simulations (lineup, playoff odds, trade impact)
- NWS forecast integration if v1 timeline is tight (decision pending)
- Real-time advice during live games
- Mobile app or hosted web service
- Auth, sharing, accounts
- Best ball, salary cap, or auction draft formats
- K and DEF as deeply analyzed positions (Vegas-driven streaming only)
- LLM-coached "season simulator" that plays the season
- Beating the prop bet market
- General-purpose chatbot UI outside the four output types

---

## Project Values

The things I care about, in priority order. Use these to break ties on architecture or scope decisions.

1. **Reasoning transparency over output polish.** The advisor must show its work. A clean justification beats a confident one-liner.
2. **Curation over consensus.** This system reflects creators I trust. It is not a meta-aggregator and should not pretend to be neutral.
3. **Cost discipline.** Predictable, narrow API calls. Pre-filtered context. The LLM is a reasoner, not a data parser.
4. **Single source of truth.** Each fact lives in exactly one document. Constitution docs (this, the roadmap, the architecture) hold current state. The journal records evolution.
5. **Sequential clarity over parallel ambition.** Build one slice end-to-end before perfecting any layer.

---

## Reading Order for New Sessions

1. This file (PROJECT_OVERVIEW.md)
2. PRODUCT_ROADMAP.md — for what's next
3. TECHNICAL_ARCHITECTURE.md — for how things work
4. The two most recent journal entries in `journal/` — for what just happened

The constitution docs change rarely. The journal changes every session.
