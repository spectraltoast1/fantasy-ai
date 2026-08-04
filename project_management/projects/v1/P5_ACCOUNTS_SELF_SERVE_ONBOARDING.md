# Project 5 — Accounts + Invite-Gated Self-Serve Onboarding

**Created:** 2026-07-26 · **Updated:** 2026-07-31 — session map rewritten S0–S6; the stale "write the RLS policies" row corrected; the store-ownership rule and the viewer-identity change added · **Status:** Active — S0 next · **Track:** Critical spine — **the biggest single block** · **Depends on:** P0 (keyed reads + viewer-as-data), P2 (the ingestion pipeline it automates) · **Est:** 7 sessions · **Session docs:** `sessions/v1/P5-Self_Serve/`

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
  refactor. Run Code's short latency spike first (**S0**), then build it (**S3**). **Fly volumes attach to
  exactly one Machine and are locked to that physical host** — no multi-attach, no moving — so the worker is a
  **stateful singleton**, not a pool. That is the right shape for an invited cohort, and it means the worker
  must be a **separate Fly app** from the API (don't entangle the API's scale-to-zero with a multi-minute job).
- **The store-ownership rule (Will, 2026-07-31) — one-directional, decide it before S3.** Once a cloud worker
  writes derived data, two stores can diverge. The cut follows the directory layout that already exists:
  the **laptop owns** `derived/ledger` (145 MB — the certification spine, never leaves) and `derived/scoring`
  (16 MB — the shared scoring-keyed substrate, authored locally and pushed up); the **worker owns**
  `derived/league` and the joins, and **never sends anything back**. The volume is therefore a
  **reconstructible cache, not precious data** — lose the host, re-seed it. Postgres stays the served truth.
  ~245 MB is what actually has to live on the volume.
- **Viewer-as-data is ready after P0/B5** (`viewer_roster_id`), so "you" resolves per league without a
  hardcode — **but it is a property of a *league* today**, read off the `/api/leagues` catalog. With real
  users it must become a property of ***user × league***, because two people in the same league need different
  "you" highlights. Related: `/api/leagues` is the **one unscoped read** and currently hands every caller all
  31 demo slices. Both are real, uncosted work inside S1–S2 — they were missing from this brief's original
  session map.

- **This is the boundary the migration doc drew.** `MULTI_LEAGUE_STORE_MIGRATION.md` explicitly scoped *"auth + the import UX out of scope"* and built the seeded demo instead — **P5 is that deferred project, picking up exactly at that line.** `../post-v1/owner-keyed-dossiers.md` is the natural refinement once a user has multiple leagues.

## The core reframe

Self-serve onboarding is essentially **"run the P2 ingestion pipeline for an arbitrary user-supplied league,
safely, on demand, and show them the result behind a login."** That's why P2 must land first: this project
*wraps* P2's pipeline in auth, isolation, an on-demand trigger, and scope-validation.

## Session map

**Rewritten 2026-07-31.** The original four-row map is superseded. Two things changed: the old S2 told a
session to *"write the RLS policies"* — wrong layer, since the app's owner role **bypasses** RLS, so per-user
isolation is **API-layer** work; and the old S3 welded three separable jobs (the cloud worker, the job queue,
the connect UX) into one session. **Everything except S6 is buildable and provable today against the 2025
replay** — the constraint on this project is calendar-gated *proof*, not build time, so build it all now and
let Gate A (Will's draft, ~late Aug) be a verification batch rather than a build.

| Session | Goal | Scope | Definition of done |
|---|---|---|---|
| **S0 — Latency spike** | Know what "connect" actually costs | Time a **brand-new** league end to end (not a re-run — the pipeline's per-step gates make a repeat look artificially fast); report the per-step split (fetch / join / spine / load); confirm the 2026 ppr+half substrate is genuinely shared so per-league work excludes it | A number, a per-step breakdown, and a sizing recommendation. It decides spinner-vs-email in S4 and the machine size in S3 |
| **S1 — Auth + user model** ✅ *shipped 2026-08-02* | The app knows who is asking | Wire **Supabase Auth** (magic link); a minimal `app_users` profile; token verification via the project's **JWKS** endpoint (asymmetric, not the legacy shared HS256 secret) | Magic-link sign-in works; `/api/me` 401s on missing/forged/expired; session survives a browser restart; every existing read stays byte-parity identical → `sessions/v1/P5-Self_Serve/SESSION_P5_S1_AUTH_AND_INVITE.md` |
| **S1b — The shared access code** ✅ *shipped 2026-08-03, audited 2026-08-04* | Self-serve signup, strangers still out | Validate a shared access code **server-side at signup** (an API endpoint that checks the code before calling Supabase — **not** the SPA, whose publishable key is public by design); code in config + a Fly secret; rotation = one config change; honest copy; `scripts/invite.py` → `scripts/users.py` (`--list` / `--ban` / `--unban`) | A stranger with the URL cannot create an account; a person with the code can, with **zero per-user work from Will**; the check is proven un-bypassable from the client (live `disable_signup: true`, confirmed in audit) → `sessions/v1/P5-Self_Serve/SESSION_P5_S1B_ACCESS_CODE.md` + `SESSION_P5_S1B_AUDIT.md` |
| **S2 — Ownership + API-layer isolation** | Users see only their leagues | A user→league ownership model; **scope every read to the authenticated caller in the API layer** (NOT an RLS-policy build — the owner role bypasses RLS); scope `/api/leagues`; move viewer identity from a *league* property to a ***user × league*** property | A logged-in user sees only their leagues plus the public demo; a direct request for another user's `league_id` is **denied, demonstrated**. **The security session — do not let a fast cadence compress it; isolation bugs are silent** |
| **S3 — The Fly worker + the store boundary** | The laptop stops being infrastructure | Stand up a **separate Fly app** + volume; seed it per the one-directional store-ownership rule above (write it as an ADR first); run the **existing pipeline unchanged** there, replay league → prod Postgres. No queue yet — a manually triggered run | The full pipeline completes on the worker for a replay league and lands in Postgres, byte-parity with a local run. Will can power off his laptop and it still works |
| **S4 — The job queue + connect flow** | A user can ask for their league | A Postgres `jobs` table (no new infra — you already have transactional Postgres and the job count is in the dozens); worker leases one job at a time; states `queued → validating → fetching → building → loading → ready \| rejected \| failed`; the connect endpoint + a progress screen | A league already in the demo slate is onboarded through the **real** flow end to end, with progress visible and a clean re-submit |
| **S5 — Preflight scope validation + honest rejection** | Safe on leagues you didn't hand-pick | A ~1-second Sleeper settings read **before** anything is enqueued: redraft vs dynasty/keeper, reception tier, roster shape (1QB/SF, skill positions), scoreability. Decline out-of-scope with clear copy; the reception-tier caveat copy | In-scope leagues enqueue; dynasty/exotic/custom are declined honestly **without ever starting a job**; tested against the demo lineages + real league ids |
| **S6 — End-to-end + failure drills** | It fails loudly, not silently | Real shapes × weeks; deliberately kill a job mid-run, time out Sleeper, double-submit, submit a league twice from two users | Every drill either recovers cleanly or dead-letters with a notification — **never a half-built league that looks complete**. The only session that wants Gate A |

## Decisions — settled 2026-07-31

- **Async ingestion — SETTLED.** The chain takes minutes and can't block a request: a job queue plus a "we're
  building your league…" progress state. S0 decides whether the wait is a spinner or an email.
- **True self-serve, not concierge — SETTLED (Will).** A cheaper path was proposed — ship the request UX and
  drain the queue by hand for the first few weeks — and **declined**: the cadence is several sessions a day,
  so the full build fits. Do not re-litigate it.
- **Sign-in = magic link — SETTLED (Will).** No password storage, no reset flow; possession of the invited
  inbox is the credential.
- **Logged-out visitors keep a public demo — SETTLED (Will).** This gives S2 a security rule that fits in one
  sentence: *demo slices are world-readable; user slices require their owner.* Far easier to get right and to
  test than "everything is private except a carve-out." **Open sub-decisions:** trim the demo to **one league
  frozen at a mid-season week** (not today's 31 slices), and how to handle the demo's honestly-empty panels
  → see Risks.
- **Per-user on-demand loading — SETTLED.** P2/S2 shipped `build_db.load_league` (delete + re-COPY one league
  in one transaction, byte-parity-proven against a full load, idempotent). The DROP+CREATE loader is not used
  per user. **This is the single biggest de-risking in P5 and it is already done.**
- **RLS depth — SETTLED.** Not an RLS-policy build. The app connects as an owner role that bypasses RLS, so
  RLS is defense-in-depth; authorization is enforced in the API layer, per read, on every request.

**Still open:**

- **Identity mapping** — Sleeper username → app user; one user with many leagues; and the *user × league*
  viewer change described in Context. S2 must settle this.
- **~~The invite mechanism~~ — SETTLED 2026-08-02: a shared access code (Option 1).** *This bullet previously
  recommended admin-provisioning and that recommendation was wrong.* "Word of mouth" describes **discovery**, not
  **provisioning** — Will's constraint is that **per-user manual work must be zero**, which is not the same as
  wanting the door open to everyone. Signup is self-serve; completing it requires a code Will hands out however
  he's already talking to the person. Forwarding it is fine (that *is* word of mouth); a leak is answered by
  rotating the code. The check must live **server-side**, because the SPA's publishable key ships in the public
  bundle — a client-side check is a speed bump with the instructions printed on it. Option 2's identity/entitlement
  split stays the right long-term shape, once there's a reason to let strangers hold accounts.
  → full analysis: `sessions/v1/P5-Self_Serve/SIGNUP_MODEL_ASSESSMENT.md`
- **Cohort — SETTLED 2026-08-02.** Pilot cohorts A and B collapse into one word-of-mouth cohort at the draft:
  **Will's one qualifying league + friends ≈ 10–15 leagues.** The pilot's **week-4 data-quality gate survives as a
  checklist Will runs**, not a cohort boundary (`context/appendices/pilot-2026.md`). Cohort C is still held back —
  by the access code now, not a calendar.
- **Custom SMTP is a Week-1 DEPENDENCY, not a nicety.** Supabase's built-in auth email sender is **2 messages per
  hour**, documented as non-production and best-effort to **pre-authorized addresses only**. S1 exhausted it with
  one real user and locked Will out of his own product for an hour. Self-serve signup without custom SMTP means a
  friend requests a link and may simply never receive one — with no support channel. Free tiers (e.g. Resend's
  100/day) cover a 10–15 league cohort many times over, and configuring custom SMTP also raises Supabase's own
  baseline to 30/hour.

## Risks / notes

- **This is the critical-path long-tail** — protect its start date; it can't be compressed into the final
  days before kickoff.
- **Ingestion latency + cost per new league** — each connect runs the full pipeline (and, if P4 is on, an AI
  batch). Bound it; consider pre-warming shared substrate (ppr/half 2026 is shared across leagues, so only
  the league-specific spine runs per user).
- **Isolation correctness is a security surface** — a leak here is real-user data exposure, not a demo bug.
  It's also the one failure mode with **no feedback signal**: a broken ingestion job fails loudly, a broken
  scope rule fails silently and the first alarm is a user seeing someone else's league. S2 gets an explicit
  adversarial pass before merge, not just a green run.
- **The pipeline was built for batch, not per-user on-demand** — making it safely callable per league
  (isolation, idempotency, failure handling) is real work, partly inherited from P2's incremental load.
- **Abuse / rate limits** — an invited-only launch bounds this, but the connect endpoint hits Sleeper's API
  per request; add basic rate limiting.
- **The demo's empty panels are real product gaps, not cosmetic ones — don't fabricate over them.** Will wants
  the public demo to look complete. Two of its holes (the ROS AI outlook; the gated market read) are honest
  empty states standing in for capabilities that genuinely don't exist yet, and a third (the ROS band panel)
  **lights up by itself at Gate A**. Filling them with synthetic data would make the demo promise things a new
  user discovers are missing within five minutes — the exact dishonesty this engine's north star forbids, and
  it also puts fabricated rows in the same tables as real ones. The honest version: **choose the demo league
  and week so the panels that are real look their best**, label the rest as coming, and let Gate A close two
  of the holes for free. A clearly-labelled synthetic *sample* league is a legitimate alternative — but it
  must be visibly a sample, and isolated from real slices.
- **Metric legibility has no home in the roadmap — and it is Will's most-repeated user feedback.** People
  don't intuitively understand what the numbers mean or what to do with them. Every V1 project is about making
  the numbers *right*; none is about making them *legible*. That is a genuine gap in `BUILD_ORDER.md`, and it
  bears directly on the north star: a wide, honest band that a user can't read isn't honesty, it's noise.
  Needs its own scoped work (in-app explainers / a "how to read this" layer), sized separately — **do not let
  it get smuggled into a P5 session**.

## Critical files

Supabase Auth config; new `app_users` + league-ownership tables (**not** an RLS-policy build — API-layer
scoping); a new onboarding API + async ingestion orchestrator (wraps the P2 pipeline per league);
`shared/league_registry.py` / `leagues.parquet` (`onboarded_at`/cohort/owner); `application/api/routes.py`
(the `slice_params` dependency — the natural chokepoint for per-user scoping) + `reads.py`;
`data/data_layer.py`; `frontend/src/queries.js` (`apiGet` — the one place a token attaches);
`App.jsx` (auth state + the user's league list).

## Definition of done (project)

An invited tester who is **not** Will can sign up, connect a fresh PPR or half-PPR redraft league (1QB or
SF), and get a correct live 2026 dashboard with their own team highlighted — while seeing only their leagues,
and while an out-of-scope league is declined gracefully. **This is the capability that makes V1 a product
other people can use.**
