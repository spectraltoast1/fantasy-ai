# Project 1 — Reliable Off-Laptop Data Collection

**Created:** 2026-07-26 · **Status:** ~Complete — **S1 live (hosted → Supabase Storage); S2 hardening shipped (2026-07-27): sidecar timestamps + catch-up retry + flush-batching + coverage-gate email. Only the rolling two-week ≥95% soak remains (calendar) — P1 closes when it clears.** · **Track:** Must-have; longest lead time · **Est:** 1–2 sessions

> **What this project does:** move the daily data collectors off Will's laptop (macOS launchd, ~63–71%
> coverage) to a **hosted scheduler** that hits **≥95% coverage**, and add the fetch-timestamp metadata the
> cache is missing. This is small, but it's a **pilot go/no-go gate** and it has the **longest lead-time
> value of anything in the plan** — the daily series are "bank it or lose it," so every day we wait is a
> permanent hole in the 2026 market and news history that the live trade read (P2) and AI outlook (P4) rely
> on. Start it the same day as P0.

---

## Context — what's collected and why it's fragile

Two collectors run daily on the laptop via launchd:

- **LeagueLogs market values** (~4am ET) — the daily trade-value snapshots that feed `market_vor` / the
  trade lean.
- **NFL team news RSS** (~5am ET, 96 feeds) — the situation-news input that feeds the AI ROS outlook.

Sleeper and nflreadpy are pulled **on demand** (in the weekly refresh, P2), *not* daily — so they are **out
of scope here**. This project is only about the two "bank it or lose it" daily series.

**Why it's fragile:** the scheduler is a laptop. Over the audited window coverage was ~63% complete / ~71%
any-data — roughly 8 laptop-off days + 7 no-retry days. A missed day cannot be backfilled (the APIs don't
serve history for these). The store also doesn't currently record *when* each fetch happened
("Add a `metadata.json` sidecar… before in-season use").

## The one real architecture decision (settle in Session 1)

The collectors historically wrote **parquet snapshots** to the local `snapshots/` tree. The served store is
now **Supabase Postgres**, and a CI runner has no persistent local disk. So: **where does a hosted collector
write its output?** Options to weigh:

- **(a) Commit append-only snapshots to the repo's data dir** (simple, versioned, but noisy git history and
  size growth).
- **(b) Write to a durable object store / Supabase Storage bucket** the weekly transform (P2) then reads.
- **(c) Write directly to a Postgres "raw snapshots" table.**

**Recommend (b)** — a durable bucket keeps raw collection decoupled from both git and the served schema, and
the P2 weekly transform consumes it the same way it consumes local parquet today. Confirm with Will; it's a
real fork with downstream effects on P2.

## Session map

| Session | Goal | Scope | Definition of done |
|---|---|---|---|
| **S1 — Host the collectors** | Collectors run unattended in CI | Port the `fetchers/run.py` daily jobs (leaguelogs, news) to a hosted scheduler (**GitHub Actions is the lead**); manage secrets/credentials; write outputs to the chosen durable store (decision above); confirm the CI environment can run the fetchers (network, `nflreadpy`/RSS deps) | Both collectors run on schedule in CI and land data in the durable store; a manual re-run works |
| **S2 — Reliability + observability** | Prove ≥95% and make failures visible | Add the `metadata.json` fetch-timestamp sidecar; retry/backoff on transient failures; a daily coverage check + a simple alert (email/push on miss); a **two-week soak** | ≥95% coverage over a rolling 2-week window; every fetch timestamped; a missed day is visibly flagged, not silent |

## Risks / notes

- **CI environment drift** — the fetchers were built to run on Will's Mac; verify deps + network egress in
  the runner early (this is the most likely S1 surprise).
- **Secrets** — LeagueLogs/Sleeper access + the store write credentials move into CI secrets; keep them out
  of the repo.
- **Cadence mismatch** — the two collectors have different natural times; schedule independently.
- **The gap is already accruing** — days missed between now and cutover are unrecoverable, which is the
  whole argument for starting today.

## Definition of done (project)

Both daily collectors run unattended off the laptop at ≥95% coverage, every fetch is timestamped, misses are
visible, and the 2026 market + news history is banking cleanly from here forward — the prerequisite for a
trustworthy live market read (P2) and AI outlook (P4).
