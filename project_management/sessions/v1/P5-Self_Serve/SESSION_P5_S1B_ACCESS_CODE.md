# V1 · Project 5 · Session S1b — The shared access code (+ custom SMTP) — a brief for Code

**Last reviewed:** 2026-08-03 · **Status:** Ready to run — **run this before S2** · **Owner:** Code drives;
Will picks the code string and creates the SMTP account. **Project:**
`projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md` · **Background:** `SIGNUP_MODEL_ASSESSMENT.md` (why S1
shipped the wrong signup model — read it, the reasoning matters).

> **What this session does:** replace the invite-provisioning model S1 shipped with the one Will actually
> wants — **self-serve signup, gated by a shared access code, with zero per-user work for Will** — and
> enforce it **server-side**, where it can't be bypassed. It also configures **custom SMTP**, which is now a
> hard dependency rather than a nicety.

> **Why it runs before S2:** right now there is **no enforceable gate at all.** Will turned the platform's
> signup switch ON, so the only thing standing between a stranger and an account is `shouldCreateUser:false`
> in `SignIn.jsx` — one line of client code, in a bundle that ships the publishable key by design. A direct
> `POST /auth/v1/otp` with `create_user: true` walks straight past it. That's an acceptable *interim* state
> (nobody is being pointed at the site, and reads are open anyway until S2) but it must be a short one.

---

## The design insight the S1 brief missed — read this before choosing an approach

The S1 brief argued for gating at the platform ("a project that refuses to create users has no path around
it") and that argument was **correct about the mechanism and wrong about who pulls the lever.** It assumed
platform-signup-OFF implies *Will provisions each person by hand*. It does not.

**Turn platform signup OFF, and let the API do the admin action automatically on presentation of a valid
code.** The API holds the service-role key; when someone submits a correct code, the API creates the user
and sends the magic link — no human in the loop. That satisfies **both** constraints at once:

- **Zero per-user work for Will** — the API is the admin, not Will.
- **Un-bypassable** — with platform signup OFF there is no public path to account creation *except* through
  the endpoint that checks the code. The gate is not a line of client code; it's the absence of any other door.

This is the shape to build. Do not gate in the SPA, and do not leave platform signup ON.

---

## Your part, Will (~10 min)

1. **Pick the code string.** Something sayable out loud — you'll be texting it, not pasting it.
2. **Create a free transactional-email account** (Resend's free tier is ~100/day, far more than a 10–15
   league cohort needs) and hand Code the SMTP credentials. **This is not optional any more** — see below.
3. **Then the eyeball:** watch Code demonstrate that a stranger with the URL cannot make an account, and that
   *you did nothing* for the person who had the code.

## Why custom SMTP became a dependency (the numbers, so it isn't relitigated)

Will's read was that a burst spread over 1–2 weeks wouldn't strain the sender. The constraint turns out not
to be volume:

- Supabase's built-in auth email service is **2 messages per hour**, is documented as **non-production,
  best-effort**, sends only to **pre-authorized addresses (project team members)**, and its limits "can
  change without notice."
- **S1 exhausted it with one real user** and locked Will out of his own product for an hour.

So it isn't "slow under load" — it's a **rate** limit and an **addressing** restriction, either of which
means a friend can request a link and simply never receive one, with no support channel to notice. Under
self-serve that is a silently lost user. Configuring custom SMTP also raises Supabase's own baseline from
2/hour to **30/hour** (adjustable). It is free and it is small; it is also load-bearing.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Platform signup goes back OFF; the API becomes the admin.** Per the insight above. Signup flows through
   an API endpoint that validates the code, then uses the service-role key to create the user + send the
   link. **Verify the setting live** (`GET /auth/v1/settings` → `disable_signup: true`) rather than assuming
   the dashboard took.
2. **One code, in config — no table.** `application/config.py` + a Fly secret, resolved env-first exactly
   like `settings.py` already does. **Rotation must be one config change**, not a migration. A `codes` table
   only if per-code attribution is ever wanted — it isn't now.
3. **Compare the code in constant time**, and never log it or echo it back in an error.
4. **Rate-limit the signup endpoint** — by IP and by email. It is the one unauthenticated write surface, and
   what it spends is the email budget, which is a denial-of-sign-in against real users. Modest is fine
   (single-digit attempts per hour per key); the point is that it exists.
5. **Honest copy.** *"Invite-only while in testing"* is now inaccurate — it's a code field. Say what's true:
   an access code is required, and where to get one. Don't imply an application process that doesn't exist.
6. **`scripts/invite.py` keeps `--list` and gains `--ban`.** It loses its reason to exist as an invite tool,
   but with self-serve signup Will now needs a way to disable an account, and this is its natural home.
7. **Nothing about S1's auth mechanism changes.** JWKS/ES256 verification, `/api/me`, `app_users`, the
   `apiGet` token seam, session persistence, byte-parity on the reads — all independent of signup policy.
   **This is a policy correction, not rework.** Don't refactor them.

## The brief to paste to Code

```
Goal: V1 Project 5, Session S1b (projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md) — replace S1's
invite-provisioning signup with a SHARED ACCESS CODE, enforced SERVER-SIDE, plus custom SMTP. Zero
per-user work for Will; strangers with the URL still cannot get in.

Read first: sessions/v1/P5-Self_Serve/SIGNUP_MODEL_ASSESSMENT.md (the full analysis and why S1 shipped the
wrong model), context/CODING_BIBLE.md, SESSION_GUIDE.md.

THE KEY DESIGN POINT — do not skip it. Platform-signup-OFF does NOT mean Will provisions people by hand.
Turn Supabase's "allow new users to sign up" OFF, and let the API do the admin action automatically when a
valid code is presented: the API holds the service-role key, creates the user, sends the magic link. Zero
human in the loop, AND no public path to account creation except through the code check. Gating in the SPA
is NOT acceptable — the publishable key ships in the public bundle, so a client-side check is bypassable by
calling POST /auth/v1/otp with create_user:true directly. That is exactly the state we are fixing.

Part 1 — the gate:
- Turn platform signup OFF. VERIFY IT LIVE (GET /auth/v1/settings -> disable_signup: true), don't assume the
  dashboard took.
- Add a signup endpoint that validates a shared access code, then creates the user + sends the magic link
  via the service-role key. Constant-time compare. Never log or echo the code.
- The code lives in application/config.py + a Fly secret, resolved env-first exactly like
  application/api/settings.py already does. Rotation must be ONE config change, not a migration. No codes
  table.
- Rate-limit the endpoint by IP and by email. It is the only unauthenticated write surface and what it
  spends is the email budget — exhausting that is a denial-of-sign-in against real users.

Part 2 — custom SMTP (a hard dependency, not a nicety):
- Configure custom SMTP on the Supabase project with the credentials Will supplies. The built-in sender is
  2 messages/hour, non-production, and delivers only to pre-authorized addresses — S1 exhausted it with one
  real user. Custom SMTP also raises the baseline to 30/hour.
- Prove a magic link actually ARRIVES at an address that is not a project team member. That is the whole
  point; a green config screen is not the proof.

Part 3 — copy + operator tooling:
- Replace "Invite-only while in testing" with honest copy for a code field. Don't imply an application
  process that doesn't exist.
- scripts/invite.py: keep --list, add --ban (disable an account). It is no longer an invite tool.

Prove it (all demonstrated, not asserted):
1. A direct POST /auth/v1/otp with create_user:true FAILS — this is the proof the gate is un-bypassable
   from the client, and it is the single most important check in this session.
2. Someone with the correct code completes signup end to end with ZERO action from Will.
3. Wrong code and missing code are both refused, and the refusal doesn't leak whether the code was close.
4. Rotating the code in config invalidates the old one — show the old code failing after rotation.
5. The rate limit bites — show it triggering.
6. A magic link ARRIVES at a non-team-member inbox via custom SMTP.
7. --ban disables an account and the banned user cannot sign in.
8. S1's auth mechanism is untouched: /api/me still behaves, session still survives a browser restart, and
   the reads are still byte-parity identical.

Scope guard — does NOT: scope any read to a user or build the ownership model (S2 — keep S2's proof about
isolation and nothing else); touch the connect-league flow, the jobs table, or the Fly worker; touch any
pipeline, transform, loader, or engine constant; touch the frozen corpus; change the public demo.

Follow SESSION_GUIDE.md: fresh worktree + scripts/worktree-setup.sh, <=3 commits, update STATUS.md and
ARCHITECTURE.md (the signup model is a stack-level fact), then scripts/worktree-close.sh --merge and push.
REDEPLOY and confirm on the live URL — a merged commit that was never deployed has bitten this project
before (P0/B3).
```

---

## Definition of done

1. **A direct `POST /auth/v1/otp` with `create_user: true` fails** — the gate is un-bypassable from the
   client. *This is the check that matters most; S1's gate failed exactly here.*
2. Someone with the code signs up end to end with **zero action from Will**.
3. Wrong code and missing code are both refused, without leaking how close the attempt was.
4. **Rotating the code is one config change**, and the old code stops working — demonstrated.
5. The signup rate limit bites — demonstrated.
6. **A magic link arrives at a non-team-member inbox** through custom SMTP.
7. `--ban` disables an account; the banned user cannot sign in.
8. S1's mechanism is intact: `/api/me`, session persistence across a browser restart, byte-parity reads.
9. Merged, **redeployed**, and confirmed on the live URL.

## Scope guard

Touches: the Supabase signup setting · a new signup endpoint + code check + rate limit · custom SMTP config ·
`SignIn.jsx` copy + a code field · `scripts/invite.py` (`--ban`) · `STATUS.md` + `ARCHITECTURE.md`.

Does **not** touch: read scoping or the ownership model (S2) · the connect flow, jobs table, or worker
(S3–S4) · any pipeline, transform, loader, or engine constant · the frozen corpus · the public demo.

## Notes / gotchas

- **The interim window is real but bounded.** Until this ships, anyone who finds the URL can mint an account.
  Not a data exposure (reads are open anyway until S2) and not a compute exposure (no connect flow until S4)
  — but it *is* an email-budget exposure, and exhausting that locks real users out. Don't point anyone at the
  site until this lands.
- **The invited-but-unconfirmed gotcha disappears** with the invite flow — that dead end Will hit while
  testing was specific to invites reading as signups to GoTrue.
- **Verify the platform setting live, twice.** The whole S1 failure chain started with a documented intent
  that didn't match the live system. `GET /auth/v1/settings` is the ground truth; the dashboard is a claim.
- **Don't let this session grow into S2.** The pull to "scope the reads while I'm in the auth code" will be
  strong. S2's proof needs to be about isolation alone.
