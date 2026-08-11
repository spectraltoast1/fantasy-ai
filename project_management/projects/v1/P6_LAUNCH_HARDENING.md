# Project 6 — Launch Hardening + Instrumentation

**Created:** 2026-07-26 · **Status:** Not started · **Track:** Gate — partly must-have, partly can-be-late · **Depends on:** P2 (live path), P5 (real users) · **Est:** 3–5 sessions

> **What this project does:** make it safe to put real invited people on the product at Week 1, and make
> sure you can **learn** from the season. Two halves: the **instrumentation** the pilot plan requires
> *before* you onboard anyone (must-have), and the **ops polish** that can trail into the season
> (can-be-late). Design source: `context/appendices/pilot-2026.md` — P6 executes its V1 pre-launch slice; its season-long go/no-go gates (week-4 data-quality, week-8 engine gate) remain the reference for *when to widen access* beyond the initial invite cohort.

---

## Context — the pilot's own gates

`pilot-2026.md` is explicit about the order of operations:

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
| **S4 — The demo costs nothing to serve** *(must-have before real traffic)* | Traffic stops being able to take the site down | **Precompute the demo.** Once S2d freezes it (own `league_id`, own lineage, week 5, never changes), compute its responses ONCE instead of once per visitor — today every anonymous visit fires **eleven analytical queries** returning byte-identical data. Three strengths, pick in-session: an in-process cache (**weak here** — scale-to-zero kills the process constantly), a table of precomputed responses (one keyed lookup instead of eleven analytical ones), or **baking the responses into the image as static files (zero database hits)**. Honest scope note: it is not eleven files — five weeks × every player/team/matchup/dossier drill-down is hundreds to low thousands of small responses, so a hybrid (precompute the surfaces, leave rare drill-downs on the DB) may be the right call. **NOTE (S2b, 2026-08-11): every `/api` response now carries `Cache-Control: private, no-store` + `Vary: Authorization`,** because the same URL returns data to one caller and 404 to another. That is the correct default and it is also exactly what this session must undo — **for the demo only, and tied to the visibility predicate rather than to path matching**, since this is the one place a caching change could serve one caller's league to another. **Plus Cloudflare's free tier in front of Fly** — per-IP limiting, bot filtering and static caching applied *before* a request costs anything. | An anonymous visit costs zero (or one trivial) Supabase queries; the demo renders identically; Cloudflare fronts the origin |

## Decisions to settle

- **What's the minimal-sufficient usage instrumentation?** Read-before-lock is the one the pilot names;
  resist adding more (instrumentation you don't analyze is cost without payoff).
- **Monitoring stack** — the lightest thing that surfaces errors + the weekly coverage/health check (can
  reuse P1's alerting).
- **Cloudflare in front of Fly — recommended, decide in S4.** Free tier, DNS change plus config, no
  code. It is the only layer where blocking actually works, because it refuses a request *before* Fly
  wakes or Supabase is touched. The alternative — rate limiting inside the app — fires at the most
  expensive possible moment and was rejected for that reason (see `SESSION_P5_S2B_SCOPED_READS.md`,
  which keeps a *counter* on unowned-league attempts but no cap).
- **Two of these are not sessions and should not queue behind P5.** Cloudflare is an afternoon of
  dashboard work; the runbook (`context/OPERATIONS.md`) is already written. P6 sits last in the build
  order while its ops half is designated must-have for Week 1 — so the non-session items come forward.
- **Which of S3 blocks Week 1** — error visibility and cost caps probably yes; deeper alerting/perf can
  trail.

## Risks / notes

- **THE RISK MODEL, corrected 2026-08-11 (with Will) — `context/OPERATIONS.md` is the standing version.**
  There is **no runaway-bill path**: one machine, no autoscaling, and a Supabase **free tier that cannot
  bill — it pauses.** "Cost caps" here therefore means *the AI runtime* (P4), not hosting. The single
  real failure is **Supabase pausing**, which unlike a saturated Fly machine **does not recover on its
  own**. What consumes the free tier is queries and bytes, which is what makes S4 (precompute + edge) a
  guardrail rather than a performance nicety.

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
