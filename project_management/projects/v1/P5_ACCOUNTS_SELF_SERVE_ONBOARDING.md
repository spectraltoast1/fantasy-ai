# Project 5 — Accounts + Invite-Gated Self-Serve Onboarding

**Created:** 2026-07-26 · **Updated:** 2026-08-14 — **S4a + S4b + S4c SHIPPED**; S4 is **S4a–S4e** (the dossier job moved out of S4c) · **Status:** Active — **S4d next** · **Track:** Critical spine — **the biggest single block** · **Depends on:** P0 (keyed reads + viewer-as-data), P2 (the ingestion pipeline it automates) · **Est:** 11 sessions (S4 became five) · **Session docs:** `sessions/v1/P5-Self_Serve/`

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
| **S2 — Ownership + API-layer isolation** — split **S2a ✅ shipped+audited 2026-08-09** / **S2b ✅ shipped+audited 2026-08-11** / **S2c ✅ punch list shipped 2026-08-11** / **S2d ✅ demo clone + RLS emit shipped 2026-08-12** / **S2e ✅ honesty pass + season selector shipped 2026-08-12** | Users see only their leagues | A user→league ownership model; **scope every read to the authenticated caller in the API layer** (NOT an RLS-policy build — the owner role bypasses RLS); scope `/api/leagues`; move viewer identity from a *league* property to a ***user × league*** property | **The acceptance rule is the settled predicate, not a looser paraphrase:** `visible = (league_id == DEMO_LEAGUE_ID) OR (owned by caller AND season == current)` — one public demo, season-independent; everything else private; an unowned `league_id` returns the **same 404** as a nonexistent one. A direct request for another user's `league_id` is **denied, demonstrated**. **S2a** closed the catalog (`/api/leagues` answers per caller) — that is *discovery*; **S2b** closes the eleven per-panel reads — that is *access* — and owns the adversarial matrix. **Split 2026-08-11 into one brief per session:** `SESSION_P5_S2A_OWNERSHIP_AND_CATALOG.md` (shipped) · `SESSION_P5_S2B_SCOPED_READS.md` (shipped — closed the only real exposure) · `SESSION_P5_S2C_PUNCH_LIST.md` (shipped — nine loop-closers incl. audit F6; the `--emit` RLS fix moved OUT, since its prove-it-bites `--load` DROPs tables on the production database) · `SESSION_P5_S2D_DEMO_CLONE_AND_SELECTOR.md` (shipped — the generated demo clone, the catalog-table rename, and the `--emit` RLS fix, off ONE 145s planned outage; **Part 2, the season selector, was its named release valve and did not fit the commit map → S2e**). `SESSION_P5_S2E_SELECTOR_AND_CLINCH.md` (shipped — the honesty pass on the League screen: `<1%`/`>99%` odds, the magic-line label set, `posture` withheld as inverted, the season selector removed and the catalog flattened). Audits: `SESSION_P5_S2A_AUDIT.md`, `SESSION_P5_S2B_AUDIT.md`, `SESSION_P5_S2C_AUDIT.md`, `SESSION_P5_S2D_AUDIT.md`, `SESSION_P5_S2E_AUDIT.md`, `SESSION_P5_S3_AUDIT.md`. **The security session — do not let a fast cadence compress it; isolation bugs are silent** |
| **S3 — The Fly worker + the store boundary** ✅ *shipped + closed 2026-08-14*. **The worker has written production Postgres**: `build_db --reload-league` on `fantasy-ai-worker` reloaded LoRP 2025 — **14,624 rows across 12 tables**, per-table counts matching the prior state exactly, *every other league + `league_catalog` untouched*. Egress and the Supabase **session** pooler both work under a `COPY` inside a transaction. **Stronger than the DoD asked:** `--verify` was run from the LAPTOP (laptop disk vs Postgres) on rows the WORKER wrote from its own volume, so `VERIFY OK` is a **cross-machine parity proof** — the 244 MB seed is now *validated*, not merely measured, which is the ADR's *reconstructible cache* claim earning its first evidence. Not literally demonstrated: the laptop physically powered off — no laptop was in the **data path** (it supplied the ssh trigger only), so this is satisfied in substance. Built and verified: the `STORE_ROLE=worker` boundary in `data_layer` (allow-list, 11 classified destinations, `check_store_boundary` 21/21 with prove-bites failing all 10), the separate Fly app **`fantasy-ai-worker`** (1 GB + 1 GB volume at `application/data/snapshots`, no server), and a **measured 37s seed** of 244 MB. **The model is ONE WRITER, not laptop-vs-worker** — there is a third machine (the GHA runner) and `STORE_ROLE` is set on both non-laptop machines. → `SESSION_P5_S3_REPORT.md` + `SESSION_P5_S3_AUDIT.md`. — **ADR ACCEPTED (Will, 2026-08-13) and BUILT, option (b): `context/appendices/store-boundary.md`. It CORRECTS this row — the pipeline canNOT run "unchanged": `weekly_refresh` rebuilds `ros_player_band` into laptop-owned `derived/scoring`, a substrate SHARED by every league on that scoring key and built under human-promoted engine constants. The worker gets it READ-ONLY, enforced in `data_layer`. Briefed: `sessions/v1/P5-Self_Serve/SESSION_P5_S3_WORKER_AND_STORE_BOUNDARY.md`.** | The laptop stops being infrastructure | Stand up a **separate Fly app** + volume; seed it per the one-directional store-ownership rule above (write it as an ADR first); run the **existing pipeline unchanged** there, replay league → prod Postgres. No queue yet — a manually triggered run | The full pipeline completes on the worker for a replay league and lands in Postgres, byte-parity with a local run. Will can power off his laptop and it still works. **SHIPPED:** `fantasy-ai-worker` (separate app, 1 GB + 1 GB volume) runs the pipeline off a seeded volume; boundary enforced as an ALLOW-LIST in `data_layer` over 16 laptop-owned writers with `STORE_ROLE=worker` on BOTH non-laptop machines (the Fly worker AND the GHA runner — the rule is one writer, not laptop-vs-worker). The band VERIFIES rather than refusing, or every 2026 refresh would break. Parity 10/10 value-identical; seed measured **37s**. Outstanding: the Postgres write half of the proving run, blocked on `DATABASE_URL` (Will's to set). → `sessions/v1/P5-Self_Serve/SESSION_P5_S3_REPORT.md` |
| **S4a — The cold onboard + the catalog** ✅ *shipped + audited + ENDORSED 2026-08-14* | The store can accept a league it has never seen | `connected_catalog.parquet` — a third catalog source, **append-shaped and WORKER-owned** (ADR classification 11 → 12); `_resolve_scoring_key` from the league's **own** settings (catalog → settings → **raise**, no more silent fallback to *the owner's* key); the onboard chain promoted to `serve/onboard_league.py::run_chain`, which `bench_cold_league` now measures rather than duplicating | **DONE. The worker onboarded a league that existed nowhere:** `1258181662160719872` "Rex Lumber 2025" — cold → catalogued → **14,999 rows / 10 tables** committed to production Postgres from the worker's own volume, `league_catalog` 32 → 33; all five clauses proven, **release valve not taken**. **The ADR was wrong and is corrected — `write_leagues` was never on this path** (every reader filters `is_mine` first; `application/api/` never imports `data_layer`). **It created one hazard, now S4b's first item:** the laptop holds the stale catalog, so `reload_manifest`/`--load` there would delete connected leagues. → `SESSION_P5_S4A_REPORT.md` + `SESSION_P5_S4A_AUDIT.md` |
| **S4b — The job queue** ✅ *shipped + audited + ENDORSED 2026-08-14* | Work reaches the worker without a human | The catalog-drift guard first (`assert_catalog_covers_postgres` — compares id **sets**, which `--verify` never did); `public.jobs` in **`api/auth_schema.sql`** (never `serve/schema.sql`, which `--load` DROPs); `id uuid`; `FOR UPDATE SKIP LOCKED` ordered by `created_at`; `LEASE_SECONDS=120` renewed per stage; **LISTEN + a 60s safety poll served in 5s slices**; `sleep infinity` → `worker_loop` | **DONE. All five clauses on the live worker, valve not taken.** Leased **0.2s** after insert, `ready` in **10.6s**; kill drill reclaimed at **130s** with Postgres identical to baseline. Idle cost **~2,880 statements/day, one held connection** (a **third** against the free tier — P6, recorded not solved). **Two latent defects found and fixed:** a crashed cold run was **permanently un-onboardable** (terminal `rejected`), and a truncated fetch **read as complete** (`_raw_present` is true on week one alone). → `SESSION_P5_S4B_REPORT.md` + `SESSION_P5_S4B_AUDIT.md` |
| **S4c — The connect flow + identity** — ✅ **SHIPPED + DEPLOYED 2026-08-14** (API v28, worker redeployed) | The ownership row stops being something Will types | **The enqueue seam moves UP into `application/api/`** — the API image contains **no `application/data/`** (`.dockerignore` excludes `data`; the Dockerfile copies `api/` only), so it cannot import `job_queue`; `job_queue` re-exports it, one implementation. `POST /api/connect` + `GET /api/connect/{id}` (scoped to `requested_by`, **same 404** as nonexistent); per-**user** Postgres-backed rate limit; **identity split** — discovery on the API via stdlib urllib, seat resolution on the worker via the existing `_roster_for_owner`; the progress screen; S4a **finding F** (the null-seat fallback); `users.py --delete`; `init_auth_schema`'s **unknown ≠ pass** | **The ownership row is written at `ready`, NOT at enqueue** — `visible` is `demo OR (owned AND season == current)` and `build_catalog` sorts **owned first**, so an early row lands the user on their own league with **every panel empty** and no error. So the progress screen is driven by the **job**, not the catalog, and a mid-build refresh must recover it. A real signed-in account connects a league end to end **with no operator step**. → `sessions/v1/P5-Self_Serve/SESSION_P5_S4C_CONNECT_FLOW.md` |
| **S4d — The weekly cadence** | Every connected league advances each week, unattended | **Enumerate connected leagues from the ownership table** instead of one hardcoded `LEAGUE_ID`, and **enqueue onto S4b's jobs table** — which is what dissolves the open question of what the Action pokes: **it pokes Postgres**, which it already has credentials for. Then **gut `.github/workflows/weekly_refresh.yml` to a pure trigger**: keep the Tue+Wed crons and the catch-up idempotency (GitHub is the better scheduler — free, reliable, already trusted for the collectors), lose all pipeline logic plus `MY_USERNAME`/`LEAGUE_ID`, which **retires** the hardcoded-identity bug rather than relocating it | **Every connected league advances a week unattended, executing ON THE WORKER.** Retire the workflow's pipeline logic only once S4d's version is proven — nothing is lost either way: it has **NEVER worked** (scaffolded in P2/S2 as bones for this session) and since the Aug 1 rollover it dies at `shared/league_resolver.py:59` because its hardcoded `LEAGUE_ID` is LoRP **2025**. **Week-1 critical — this is what stops the app being frozen in-season** |
| **S4e — The Manager Dossier deferred job** *(moved out of S4c 2026-08-14)* | The fifth surface lights up for connected leagues | The dossier executor as a **second job class** on S4b's queue (the `kind` column already exists), then flip `panels_manager` to True **in the same session that makes it true** | **Not Week-1 critical, and that is the reasoning for the move:** S0 designed connect as **staged** — the four fast surfaces on a spinner, manager profiling as a *separate deferred job class*, because the fan-out is **80s / 248 Sleeper calls**. So `panels_manager: false` on a connected league is the **designed** behaviour with an honest empty state already in place, not a gap. **Reversible** if it should ride with S4c |
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

- **S4 SPLIT into S4a / S4b / S4c / S4d / S4e — SETTLED (Will, 2026-08-14; split twice more the same day as each session revealed the next).** The dossier job moved out of S4c on the PM's call — reversible. S4 as written was a queue **plus** a
  connect endpoint **plus** a progress screen **plus** identity acquisition **plus** the catalog wall
  **plus** the weekly cadence **plus** two carried fixes — three sessions against the 3-commit cap. Same
  shape as S2 becoming S2a–S2e, and the same rule applies: *one brief per session, do not re-bundle.*
  **S4a is first because it is the only one where nobody knows whether it works**, and because a queue
  whose payload cannot run and a cadence over leagues that cannot be connected are both proofs that pass
  by doing nothing.
- **The "S4 wall" was mis-scoped and the ADR is corrected by S4a.** `store-boundary.md` names
  `write_leagues`. In the code there are **three** laptop-owned whole-file catalog writers —
  `write_leagues`, `write_demo_manifest`, `write_synthetic_catalog` — and it is the **last two** that
  block the loader: `build_db._catalog()` is `demo_manifest ⧺ synthetic_catalog`, `_slices()` comes from
  `_catalog()`, and `load_league` refuses anything absent from it *in as many words*. **So there is today
  no artifact a real user's league row can legally live in**, and **nothing in this system has ever
  catalogued a league** — `bench_cold_league` rolls its load back specifically to sidestep that gate.
  **This also blocks Gate A**, which STATUS files as "a manual admin load, not P5": that load needs the
  same missing row.
- **A 2026 league cannot prove S4a — SETTLED (Will, 2026-08-14).** Will's 2026 leagues have not drafted,
  so there are no rosters and nothing to join. S4a proves against a real, played **2025** league that is
  cold by every catalog. The 2026 combination — a *cold* 2026 league whose scoring key's substrate must
  already be on the volume — is **carried to Gate A and stated in the report**, not quietly rounded up.

**Still open:**

- **Identity mapping — HALF CLOSED, reassigned to S4b (2026-08-13; re-pointed at S4b 2026-08-14).** S2 settled the **model**: the viewer
  seat is a *user × league* property (`user_leagues.roster_id`). It did NOT settle **acquisition** —
  `api/routes.py:102` is explicit that ownership rows are *"written by an operator rather than inferred
  from a sign-in"*, so a self-serve user can sign up and reach nothing until Will types a row. Mapping a
  Sleeper username to an app user is **connect-flow work → S4c**.
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
