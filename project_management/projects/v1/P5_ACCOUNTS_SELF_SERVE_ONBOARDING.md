# Project 5 — Accounts + Invite-Gated Self-Serve Onboarding

**Created:** 2026-07-26 · **Status:** Not started · **Track:** Critical spine — **the biggest single block** · **Depends on:** P0 (keyed reads + viewer-as-data), P2 (the ingestion pipeline it automates) · **Est:** 6–9 sessions

> **What this project does:** turn the app from "one hardcoded league, no login" into "**an invited user logs
> in, connects their own Sleeper league, and gets a live dashboard.**" This is the capability that makes
> V1 *invite-gated self-serve* (Will's decision), and it's the largest block of work in the plan. It sits on
> top of P0 (so reads can target any league and resolve "you") and P2 (so there's a live ingestion pipeline
> to run for a brand-new league). **Guard its start date jealously — if anything slips, slip P3/P4, never
> this.**

---

## Context — what exists, and what's deliberately teed up

The architecture was built so this is a **bolt-on, not a rewrite** — but the bolt-on is real work:

- **Auth was deferred on purpose.** Postgres/Supabase was chosen specifically so **Supabase Auth** can be
  added later without a second store move. Today there is no user model, no session, no login.
- **Data isolation is coarse today, but external exposure is closed.** RLS is **enabled deny-by-default on
  all public tables and the unused Data API is disabled**, so the DB is no longer openly
  reachable. The app still connects as an **owner role that bypasses RLS**, so this is defense-in-depth, not
  per-user isolation — **that's P5's job, enforced in the API layer** (not a large RLS-policy build, since the
  owner role bypasses RLS anyway): every read must be scoped to the authenticated user. Fine for one public
  league; unacceptable once real users each have their own.
- **Adding a league is currently an engineer task** (run fetchers + transforms + loader). The registry
  (`leagues.parquet`) already carries **`onboarded_at` + `pilot_cohort`** hooks that are unused — they exist
  for exactly this.
- **On-demand ingestion needs cloud execution — a P5 prerequisite (discovered in P2/S2).** The derived store
  lives on local disk; running the P2 pipeline for a user's league on a stateless cloud runner needs the store
  reachable there (P1's bucket backend covers only the 2 daily collectors). **Decision (Will): a small Fly
  worker holding the store on a volume**, reusing the pipeline — cheaper + lower-upkeep than a full serverless
  refactor. Run Code's short latency spike first, then build it at/near the start of P5. *(RLS/security posture
  in the next bullet is a separate open thread — confirm the live state with Will.)*
- **Viewer-as-data is ready after P0/B5** (`viewer_roster_id`), so "you" resolves per league without a
  hardcode.

- **This is the boundary the migration doc drew.** `MULTI_LEAGUE_STORE_MIGRATION.md` explicitly scoped *"auth + the import UX out of scope"* and built the seeded demo instead — **P5 is that deferred project, picking up exactly at that line.** `../post-v1/owner-keyed-dossiers.md` is the natural refinement once a user has multiple leagues.

## The core reframe

Self-serve onboarding is essentially **"run the P2 ingestion pipeline for an arbitrary user-supplied league,
safely, on demand, and show them the result behind a login."** That's why P2 must land first: this project
*wraps* P2's pipeline in auth, isolation, an on-demand trigger, and scope-validation.

## Session map

| Session | Goal | Scope | Definition of done |
|---|---|---|---|
| **S1 — Auth + user model** | Users can log in (invite-gated) | Wire **Supabase Auth**; a `users` table; sessions; login/signup UI; the invite mechanism (allow-list or invite codes) | An invited person can sign up and log in; a non-invited person cannot |
| **S2 — Ownership + data isolation (RLS)** | Users see only their leagues | A user→league ownership model; **write the RLS policies** so the served tables scope to the requesting user; stop the app relying on the RLS-bypassing owner role for user-facing reads | A logged-in user sees only their leagues + appropriate shared/global data; a direct attempt to read another user's league is denied |
| **S3 — Connect-your-league ingestion** | A user brings their own league | A "connect your Sleeper league" flow (enter username / league_id) that triggers the **P2 pipeline** for that league **asynchronously**, registers it (`onboarded_at`, cohort, owner), and shows progress; resolve the user's `viewer_roster_id` in that league | A user connects a fresh PPR/half redraft league and, after ingestion, sees a correct live dashboard with "you" highlighted |
| **S4 — Scope validation + graceful rejection + robustness** | Safe on leagues you didn't hand-pick | Validate the connected league is **in scope** (redraft, ppr/half, 1QB/SF, scoreable); **decline out-of-scope** leagues (dynasty, un-scoreable custom, exotic shapes) with a clear "not supported yet" message; handle the reception-tier caveat copy; sanity-check the SF market/QB-pool read | In-scope leagues onboard cleanly; out-of-scope leagues are declined honestly, not broken; a variety of real invited leagues render correctly |

## Decisions to settle (surface to Will)

- **Sync vs async ingestion.** The P2 fetch→transform→load chain takes minutes — it can't block a request.
  **Recommend async** (a job queue + a "we're building your league…" progress state). This is the biggest UX
  decision and it shapes S3.
- **Per-user on-demand loading vs the DROP+CREATE loader.** The current full-reload loader **cannot** be used
  per user. This project **requires P2's incremental/per-league load** — confirm that dependency is done
  before S3.
- **Identity mapping** — Sleeper username → app user; one user, many leagues; what happens when two users are
  in the same league (shared league data, per-user viewer).
- **Invite model** — allow-list vs invite codes vs manual approval.
- **RLS depth** — full row-level policies vs an app-layer scoping layer in front of the owner connection.
  (RLS is the more secure long-term answer; weigh time-to-ship.)

## Risks / notes

- **This is the critical-path long-tail** — protect its start date; it can't be compressed into the final
  days before kickoff.
- **Ingestion latency + cost per new league** — each connect runs the full pipeline (and, if P4 is on, an AI
  batch). Bound it; consider pre-warming shared substrate (ppr/half 2026 is shared across leagues, so only
  the league-specific spine runs per user).
- **RLS correctness is a security surface** — get isolation right; a leak here is a real-user data exposure,
  not a demo bug.
- **The pipeline was built for batch, not per-user on-demand** — making it safely callable per league
  (isolation, idempotency, failure handling) is real work, partly inherited from P2's incremental load.
- **Abuse / rate limits** — an invited-only launch bounds this, but the connect endpoint hits Sleeper's API
  per request; add basic rate limiting.

## Critical files

Supabase Auth config; new `users` + league-ownership tables + **RLS policies**; a new onboarding API +
async ingestion orchestrator (wraps the P2 pipeline per league); `shared/league_registry.py` /
`leagues.parquet` (`onboarded_at`/cohort/owner); `data/data_layer.py` (per-user scoping); frontend auth +
"connect league" UI; `App.jsx` (auth state + the user's league list).

## Definition of done (project)

An invited tester who is **not** Will can sign up, connect a fresh PPR or half-PPR redraft league (1QB or
SF), and get a correct live 2026 dashboard with their own team highlighted — while seeing only their leagues,
and while an out-of-scope league is declined gracefully. **This is the capability that makes V1 a product
other people can use.**
