# V1 · Project 5 · Session S1 — Auth + user model + invite gate — a brief for Code

**Last reviewed:** 2026-07-31 · **Status:** Ready to run — **both forks settled by Will** · **Owner:** Code
drives; Will does the eyeball (sign in as himself; watch an uninvited address fail).
**Project:** `projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md` (S1 of P5). **Runs after S0, the latency
spike.**
**The first session of the biggest block: the app learns who is asking.**

> **What this session does:** put a real front door on the app. Wire **Supabase Auth**, add a minimal app-side
> user record, gate account creation to **invited people only**, and give the API a verified answer to the
> question it has never been able to ask — *who is this?* It builds the *identity* half only. The *isolation*
> half (what each identity is allowed to see) is S2, deliberately, and the reasoning is below.

> **Why it's launch-critical:** every other P5 session assumes an authenticated caller. Ownership (S2),
> connect-your-league (S4), and the job queue all key off a user id that does not exist today. Nothing in P5
> can start until this does.

---

## The timing reality (shapes verification)

Nothing here is gated on a 2026 league or on games being played. This session is fully buildable and fully
provable **today**, against the existing demo slate. There is no "prove it at the gate" component — if this
session's definition of done is met, it is met permanently. Do not defer any part of it to Gate A.

---

## Both forks — settled (Will, 2026-07-31)

**Sign-in = magic link.** Type an email, get a one-time link, you're in. No password storage, no reset flow,
no "I forgot my password" support. Will's reasoning: the cohort is small and nothing in the app is sensitive
enough that a compromised inbox is a serious exposure. Accepted.

**The public demo stays open.** A logged-out visitor still browses; signing in *adds* your leagues. This gives
S2 a security rule that fits in one sentence — *demo slices are world-readable; user slices require their
owner* — which is far easier to get right and to test than "everything is private except a carve-out."

**Two demo follow-ups that are NOT this session.** Will wants the demo trimmed to **one league frozen at a
mid-season week** (instead of today's 31 slices), and wants an in-app explainer for what the metrics mean.
Both are real and both are scoped separately — see the Risks section of the project brief. **Code: do not
change the demo slate or add any explainer in this session.** S1 leaves the logged-out experience exactly as
it is today.

**Will's eyeball:** sign in as yourself and land on the app exactly as it looks now. Then watch Code
demonstrate that an address you have *not* invited cannot get an account — that's the one behavior that has to
be true rather than reported.

---

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **The invite gate lives in the platform, not in app code — and there is no invite list.** Will shares by
   word of mouth; no allow-list exists or needs to. So: turn **off** public signup in the Supabase project,
   and give Will a **one-command admin invite** (`invite <email>`). Word-of-mouth still works — the mouth just
   routes through Will, which is the point: nobody consumes pipeline compute on the single worker without him
   knowing. Do **not** build an app-side allow-list table; an app-level check is a line of code that can be
   bypassed if any other signup path exists, whereas a project that refuses to create users has no such path.
   *(Invite codes are the natural upgrade when being in the loop stops being cheap — not now.)*

2. **Verify tokens against the project's JWKS endpoint with an asymmetric signing key (ES256), not the legacy
   shared HS256 secret.** Supabase's current guidance is explicit that the shared-secret path is legacy and
   not recommended for production; the asymmetric path publishes public keys at
   `https://<project>.supabase.co/auth/v1/.well-known/jwks.json`, so keys can rotate without redeploying the
   API and the API never holds a secret capable of *minting* tokens — only of checking them. Cache the JWKS
   with a bounded TTL. **Fail closed:** if verification cannot be performed, the request is unauthenticated,
   never optimistically trusted.

3. **Do NOT enforce auth on the read endpoints this session.** Build the verification dependency and apply it
   to exactly one new endpoint (`GET /api/me`) that proves it works end to end. Leave the existing reads open.
   The reason is not timidity — it's that authentication without scoping is a half-gate that *looks* like
   security while every caller still sees every league. Closing the reads and scoping them to their owner is
   one coherent change with one coherent proof, and that is S2. Shipping the half now would mean writing the
   gate twice and proving it neither time.

4. **One new dependency per side, and no more.** `application/api/requirements.txt` is deliberately minimal
   (its own comment says so) — add **only** `pyjwt[crypto]`. The frontend adds **only**
   `@supabase/supabase-js`. Do not add a router: the SPA has no routing library, and auth state belongs in
   `App.jsx`'s existing state model, not in new navigation machinery.

5. **The token attaches at exactly one place.** `queries.js`'s `apiGet` is the single client-side data seam and
   already merges a module-level slice into every request — attach the bearer token there, the same way. No
   view component learns that auth exists. This is the Coding Bible's seam rule, and it's why this session is
   small on the frontend.

6. **A minimal `public.app_users` profile row, keyed to the auth user's id.** Created on first sign-in. Enough
   to hang later work on (id, email, created_at, cohort) and nothing more — the user→league ownership model is
   S2's, and inventing it early guarantees rework.

7. **Parity is a hard requirement.** Every existing read must return **byte-identical** payloads with the app
   shell signed in. If a payload moves, that's a bug under the standing rule, not an acceptable side effect.

8. **Prove the gate bites.** A missing token, a forged token, and an expired token must each be rejected by
   `/api/me`, demonstrated — not asserted. An uninvited email must fail to obtain a session, demonstrated.
   A gate nobody watched fail is not a gate.

9. **Secrets placement, explicitly.** The publishable/anon key belongs in the SPA and is fine there. The
   **service-role key must never** reach the frontend bundle, the Docker image, or git — it is admin-grade.
   Follow the existing env-first pattern in `application/api/settings.py` (env var wins; `config.py` is a
   local-only fallback that the deployed image does not ship).

---

## The brief to paste to Code

```
Goal: V1 Project 5, Session S1 (projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md) — auth + user model +
invite gate. Give the app a real front door and give the API a verified answer to "who is asking?". This is
the IDENTITY half only; per-user data isolation is S2 and is deliberately out of scope. Fully buildable and
provable today against the existing demo slate — nothing here waits on a 2026 league.

Read first: project_management/context/STATUS.md, CODING_BIBLE.md, SESSION_GUIDE.md, and
projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md. Note that the P5 brief's S2 row is stale where it says
"write the RLS policies" — the app connects as an owner role that BYPASSES RLS, so per-user isolation is an
API-layer job. Do not build RLS policies in this session or the next.

Part 1 — Supabase Auth, invite-gated:
- Wire Supabase Auth on the project. Sign-in method is MAGIC LINK (settled). Turn OFF public signup so
  accounts can only be created by admin invite. The gate is the project setting, not an app-code check.
- There is NO invite list and none is wanted — sharing is word of mouth. Give Will a one-command admin invite
  (a small local script using the service-role key; the key must never reach the frontend, the image, or
  git). Do NOT build an app-side allow-list table.

Part 2 — token verification in FastAPI:
- Add a dependency that verifies the Supabase-issued JWT from the Authorization: Bearer header against the
  project's JWKS endpoint (https://<project>.supabase.co/auth/v1/.well-known/jwks.json), asymmetric
  (ES256). Do NOT use the legacy shared HS256 secret — Supabase's current guidance is that it is legacy and
  not recommended for production, and JWKS lets keys rotate without redeploying.
- Cache the JWKS with a bounded TTL. FAIL CLOSED: if verification can't be performed, the caller is
  unauthenticated. Never optimistically trust.
- Add exactly ONE dependency to application/api/requirements.txt: pyjwt[crypto]. That file is deliberately
  minimal — read its header comment before touching it.
- Resolve config env-first, matching application/api/settings.py's existing pattern (env var wins;
  config.py is a local-only fallback the deployed image does not ship).

Part 3 — the app-side user record:
- A minimal public.app_users row keyed to the auth user's id (id, email, created_at, cohort), created on
  first sign-in. Nothing more — the user->league ownership model is S2's and must not be invented here.

Part 4 — one proving endpoint, and NOT more:
- Add GET /api/me: returns the authenticated caller's identity; 401 on missing/forged/expired.
- Leave every existing /api read endpoint OPEN and unchanged this session. Authentication without scoping is
  a half-gate — closing and scoping the reads is one coherent change with one coherent proof, and that is S2.

Part 5 — the frontend:
- Add @supabase/supabase-js and nothing else. Do NOT add a router; the SPA has none and auth state belongs
  in App.jsx's existing state model.
- Attach the bearer token in exactly ONE place: queries.js's apiGet, alongside how the active slice is
  already merged into every request. No view component learns that auth exists.
- A minimal sign-in screen + a signed-in indicator with sign-out. Logged-out behavior (settled): the public
  demo stays browsable EXACTLY as it is today. Do NOT trim the demo slate, freeze a week, or add any metric
  explainer — both are wanted, both are scoped as separate work, neither is this session.

Prove it (all four demonstrated, not asserted):
1. An invited address can sign in and reach the app.
2. An UNINVITED address cannot obtain a session — show the attempt failing.
3. /api/me returns identity on a valid token and 401 on each of: no token, forged token, expired token.
4. PARITY: with the shell signed in, every existing read returns byte-identical payloads to today. A payload
   that moves is a bug under the standing rule, not an acceptable side effect.

Scope guard — this session does NOT: scope any read to a user, build the ownership model, write RLS
policies, touch the connect-your-league flow, touch the Fly worker or any pipeline/loader code, touch the
frozen corpus, or change any engine constant.

Follow SESSION_GUIDE.md: fresh worktree + scripts/worktree-setup.sh, <=3 commits, update
context/STATUS.md (and ARCHITECTURE.md — auth is a stack change, so it belongs there) per the anti-bloat
rule, then scripts/worktree-close.sh --merge and push. Redeploy so the change is actually live; a merged
commit that was never deployed has bitten this project before (P0/B3).
```

---

## Definition of done

1. An **invited** person signs in and lands on the app, which looks and behaves exactly as it does today.
2. An **uninvited** email **cannot obtain a session** — demonstrated, with the failure shown.
3. `GET /api/me` returns the caller's identity on a valid token and **401** on each of a missing, forged, and
   expired token — all three demonstrated.
4. **Parity holds:** every existing read returns byte-identical payloads with the shell signed in.
5. A logged-out visitor still browses the demo exactly as today — unchanged, not merely "still works."
6. The **service-role key appears nowhere** in the frontend bundle, the image, or git — verified, not assumed.
7. Merged **and redeployed**, with the live URL confirming the sign-in screen is actually there.

## Scope guard

Touches: Supabase Auth project config · a new API auth dependency + `/api/me` · a minimal `app_users` table ·
`queries.js`'s `apiGet` · `App.jsx`'s state + a sign-in screen · one dep per side · a local invite script.

Does **not** touch: read scoping or the ownership model (S2) · RLS policies (not the authz layer here at all)
· the connect-league flow or the job queue (S4) · the Fly worker (S3) · any pipeline, loader, transform, or
`data_layer.py` code · the frozen corpus · any engine constant.

## Notes / gotchas

- **`api/requirements.txt` is deliberately minimal** and says so in its own header — the deployed image is
  kept small on purpose. One dependency, `pyjwt[crypto]`. Resist any second.
- **Fly scale-to-zero + JWKS.** The API sleeps. The first request after a cold start may need to fetch the
  JWKS before it can verify anything. Cache it with a bounded TTL and a sane timeout — and make a JWKS fetch
  failure reject the *request*, not crash the *process*.
- **Supabase free-tier pausing.** `main.py`'s header already notes the project can pause, which is why
  `/health` is deliberately DB-free. Auth calls fail the same way when it's paused — don't diagnose that as an
  auth bug.
- **Magic-link deliverability.** Supabase's default email sender has modest rate limits and mediocre
  deliverability. Fine for a handful of testers; if the cohort grows, custom SMTP becomes a real to-do. Log
  it, don't solve it here.
- **The P5 brief's session map is stale in one row** — its S2 says "write the RLS policies." The owner role
  bypasses RLS, so that's defense-in-depth, not authorization. Per-user isolation is API-layer work. I'll
  correct the project brief; don't let the stale row leak into a future session.
- **Don't let this session grow into S2.** The pull to "just scope the reads while I'm in here" will be
  strong and should be resisted — see decision 3. S2 is the security session and deserves its own proof.
