# Project 6 — Launch Hardening + Instrumentation

**Created:** 2026-07-26 · **Status:** Not started · **Track:** Gate — partly must-have, partly can-be-late · **Depends on:** P2 (live path), P5 (real users) · **Est:** 3–5 sessions

> **What this project does:** make it safe to put real invited people on the product at Week 1, and make
> sure you can **learn** from the season. Two halves: the **instrumentation** the pilot plan requires
> *before* you onboard anyone (must-have), and the **ops polish** that can trail into the season
> (can-be-late). Design source: `context/appendices/pilot-2026.md` — P6 executes its V1 pre-launch slice; its season-long go/no-go gates (week-4 data-quality, week-8 engine gate) remain the reference for *when to widen access* beyond the initial invite cohort.

---

## Context — the pilot's own gates

`PILOT_2026.md` is explicit about the order of operations:

- **"Live path writes `served=true` rows for Cohort A… Do not onboard anyone"** before that. An
  un-instrumented week is unrecoverable — you can't reconstruct after the fact whether the tool saw a
  decision coming. So the instrumentation half is a **hard pre-onboarding gate**, not a nice-to-have.
- The best product metrics are **programmatic and zero user burden** — you already fetch Sleeper
  transactions, so **decision-touch** (did the tool flag the move the week before?) and
  **divergence + adjudication** (did they act against the read, and who was right?) come for free from data
  you already have. The only new front-end need is a **minimal usage log** (read-before-lineup-lock).
- The one thing you ask a human: **one question, once a week** — "Did this change a decision? Y/N + one
  line." More than that and they stop answering.

## Session map

| Session | Goal | Scope | Definition of done |
|---|---|---|---|
| **S1 — Served-decision instrumentation** *(must-have; before onboarding)* | The live path is measurable | Write **`served=true`** rows to the ledger on the live path; a **minimal usage log** (opened before lineup lock?); compute **decision-touch** + **divergence/adjudication** from Sleeper transactions; wire the weekly one-question prompt | `served=true` rows written for a live league; decision-touch + divergence computable from real data; the weekly question captured |
| **S2 — End-to-end verification on real shapes** *(must-have)* | It doesn't break on real leagues | Click through every onboarded league shape (team counts, 1QB/SF, ppr/half) × sample weeks; identity, panel gating, `read_network_requests`/`read_console_messages` clean | Green across every onboarded shape; screenshots of contrasting real leagues; no console/network errors |
| **S3 — Ops hardening** *(mostly can-be-late)* | Safe under real users | Error monitoring + basic alerting; **AI cost caps** (rides with P4); the `metadata.json` cache sidecar (if not already in P1); Fly **scale-to-zero cold-start** behavior acceptable on first hit; basic rate limiting on the connect endpoint | Errors are visible; AI + hosting costs are bounded; cold-start is acceptable; the connect path is rate-limited |

## Decisions to settle

- **What's the minimal-sufficient usage instrumentation?** Read-before-lock is the one the pilot names;
  resist adding more (instrumentation you don't analyze is cost without payoff).
- **Monitoring stack** — the lightest thing that surfaces errors + the weekly coverage/health check (can
  reuse P1's alerting).
- **Which of S3 blocks Week 1** — error visibility and cost caps probably yes; deeper alerting/perf can
  trail.

## Risks / notes

- **S1 is a gate, not a polish step** — if it isn't done, per the pilot you **don't onboard**. Do it before
  the cohort, not after.
- **Instrumenting after onboarding loses the first weeks permanently** — same "bank it or lose it" logic as
  the collectors.
- **Cost** — real users + live AI can move spend; the caps (S3, with P4) matter once more than a few leagues
  are on.
- **Don't over-instrument** — the pilot's discipline is *one* human question and a couple of automatic
  metrics; more kills response rates and adds noise.

## Critical files

The ledger write path (`served=true`); a minimal front-end usage log + its endpoint; a decision-touch /
divergence computation over Sleeper transactions; monitoring/alerting config; AI cost-cap config (shared
with P4); `data_layer` cache metadata; Fly app config (cold-start).

## Definition of done (project)

The live path writes `served=true` rows and the decision-touch/divergence scoreboard computes from real
data **before** the cohort is onboarded; the product is verified across every real onboarded league shape;
and errors + costs are monitored and bounded. **This is what lets you onboard at Week 1 with confidence and
actually learn whether the product helps — the whole point of running 2026 as a validation season.**
