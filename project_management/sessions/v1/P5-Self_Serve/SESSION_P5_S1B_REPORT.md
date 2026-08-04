# P5 · S1b — The shared access code — report

**Ran:** 2026-08-03 · **Brief:** `SESSION_P5_S1B_ACCESS_CODE.md` · **Commits:** 3
**Status: SHIPPED, DEPLOYED, MERGED** (main `c85761c`) — every DoD item demonstrated.

---

## Verdict

**The gate is built and it is the un-bypassable kind.** Signup is self-serve behind a shared
access code, checked **server-side** at `POST /api/signup`; the API holds the secret key and
performs the admin create itself, which is what makes platform-signup-OFF compatible with zero
per-user work for Will. The brief's central insight was right and is the thing that makes this
work — *platform-signup-OFF does not imply a human provisions people.*

The headline check passes: with platform signup off, a direct `POST /auth/v1/otp` — using the
publishable key anyone can read out of the bundle — is refused. That is the property S1 shipped
without and the reason this session exists.

Custom SMTP is live on **surplusff.com** and a magic link has been confirmed arriving at a non-team
address — which was the thing actually standing between the cohort and the product, and is unrelated
to the gate.

---

## What shipped

| | |
|---|---|
| `api/signup.py` | code check (`hmac.compare_digest`) + admin-create + send. Fails **closed** |
| `api/rate_limit.py` | by IP and email, over Postgres. Fails **open**, deliberately |
| `api/auth_schema.sql` | `+ signup_attempts`; `init_auth_schema.py` generalized to a table list |
| `api/settings.py` | `access_code()`, `supabase_publishable_key()`; corrected the now-false "the API never calls an admin endpoint" docstrings |
| `routes.py` | `POST /api/signup` — the API's first write endpoint and only unauthenticated one |
| `api/check_signup.py` | the offline proof |
| `queries.js` | `apiPost` — the seam's first POST |
| `SignIn.jsx` | code field; posts through the seam instead of calling Supabase; honest copy |
| `scripts/invite.py` → `users.py` | `--list` / `--ban` / `--unban` |
| `config.example.py` | the four auth values a fresh worktree had no way to discover |

---

## Proven

**Offline** (`check_signup.py`, no DB, no network): accepts the right code and tolerates
surrounding whitespace (people paste from Messages); rejects a wrong code, an empty one, an
omitted one, a **one-character near miss**, a prefix, an over-long variant, wrong case, and an
inner-space variant. **An unconfigured server refuses everyone** — absent config never means
"welcome". Uses `hmac.compare_digest`, so a near miss isn't distinguishable by timing. One uniform
refusal message, asserted to contain none of *close / almost / length / exists / registered /
unknown*.

**Live, against the real project:**

| check | result |
|---|---|
| missing / wrong / near-miss code | **403**, identical message each time |
| malformed email | 400, before any Supabase call |
| **valid code** | **gate opens** — account created and confirmed; the *mailer* is what then fails, which is the SMTP dependency proving itself rather than the gate |
| rate limit | trips on the **6th** attempt for one email |
| **limit survives a restart** | killed the process, started a fresh one — still 429. An in-memory limiter would have forgotten, which on a scale-to-zero app is how you reset it by being patient |
| `Fly-Client-IP` | honoured when present (`request.client.host` is Fly's proxy, identical for everyone) |
| attempt log | wrong codes are recorded, so brute-force counts against the budget rather than being free |
| **browser, desktop + mobile** | code field renders; a wrong code shows **the server's sentence** — which is the entire reason `apiPost` surfaces `detail`, since `apiGet` would have shown `POST /signup → 403` |
| logged-out demo | unchanged |

**And the headline check (DoD 1) — the one S1's gate failed.** Will flipped platform signup OFF
mid-session, so this is now demonstrated rather than pending. Bypassing the SPA entirely and using
the publishable key anyone can read out of the bundle: `POST /auth/v1/otp` with `create_user: true`
→ **422 `signup_disabled`**; with `create_user: false` → **422 `otp_disabled`**. **There is no
public path to account creation left.** The only door is `POST /api/signup`, which checks the code
server-side before doing anything at all. This is the property the whole session exists for, and it
is the one S1 shipped without.

---

## The two that were open at write-time — both since proven

1. **A magic link reaching a non-team inbox (DoD 6).** Will registered **surplusff.com** on Resend and
   configured it as Supabase's SMTP sender. `POST /api/signup` with the real code for
   `willdaniel.wrd+test@gmail.com` — a *different address string*, so not a project team member —
   returned **200**, and **Will confirmed the email arrived** from surplusff.com. The same call before
   SMTP returned **502** on the mailer, so this is a clean A/B rather than an assertion.

   Worth recording for whoever sets this up next: **Resend requires a verified domain** — *"You must
   add and verify at least one domain to send and receive emails"* — and its `onboarding@resend.dev`
   test sender only reaches the account owner. So "use Resend without a domain" solves nothing; it
   reproduces exactly the restriction it was meant to escape.

2. **`--ban` (DoD 7) — proven, and the technique is the interesting part.** Two obvious routes are both
   dead ends: the sign-in path returns **429** (Supabase's per-address minimum interval), which *looks*
   like a refusal but isn't the ban; and `admin/generate_link` returns **200 for a banned user**,
   because it's an admin call that doesn't enforce bans. The definitive test is to **redeem** the link
   the way a browser would — `GET /auth/v1/verify?token=…` → **303** to
   `#error=access_denied&error_code=user_banned`, **no session issued**.

   The lesson generalises: **bans bite at token exchange, not at link generation.** A consequence worth
   knowing operationally — an already-issued access token stays valid until it expires (~1h), so a ban
   is not an instant eviction.

   I nearly recorded the first 429 as a pass. It is the same error class as reading a status code
   without reading the error body, which cost time in S1; flagging it because the habit is the thing
   worth keeping, not the individual catch.

**Every DoD item is now demonstrated.** Test artifacts removed: the `+test` account is deleted and the
attempt log is back to 0 rows; Will's account was banned and unbanned during testing and is in its
original state.

## Decisions worth carrying

**The rate limiter had to go in Postgres, and that was forced by the deployment rather than
taste.** `fly.toml` runs **two** machines with `min_machines_running = 0` and
`auto_stop_machines = "stop"`. In-process state would be split across both *and erased on
scale-to-zero* — defeatable on purpose by waiting out the idle window. Its first job is
brute-force resistance (a code chosen to be sayable is low-entropy by construction); protecting
the send budget is second.

**Two opposite failure modes, deliberately.** `signup.py` fails **closed** — missing config,
unreachable Supabase, anything unexpected refuses. `rate_limit.py` fails **open** — it is a
nuisance control, not an authorization one, and a database hiccup should not mean nobody can sign
in. The code check is what decides admission.

**The posture change is real and is recorded, not slipped in.** The secret key is now a Fly
secret, so an admin-grade credential lives in the deployed environment for the first time. That is
the price of the gate being un-bypassable; gating in the SPA was *measured* to be no gate at all.

**This endpoint is scaffolding.** When signup opens to the public, `signInWithOtp` handles
create-or-send natively — so `signup.py` should be **deleted**, not promoted. Worth knowing before
someone invests in it.

---

## Deployed state

`ACCESS_CODE` and `SUPABASE_SECRET_KEY` are Fly secrets; `SUPABASE_URL` stays in `fly.toml`'s `[env]`
and the publishable key in `[build.args]`, so a bare `fly deploy` remains correct. Verified on
production: the gate refuses a missing and a wrong code, the bundle carries the code field, **neither
the secret key nor the access code appears in the bundle**, the publishable key does (as designed),
`/api/me` is unchanged, and all **12 reads are byte-identical** to the pre-S1 baseline.

## For S2

Unchanged by this session: per-user isolation in the API layer, `/api/leagues` is still the one
unscoped read, viewer identity still needs to become *user × league*, and the `ros_player_band`
RLS drift still wants fixing at its source (`--emit` should emit the RLS lines). S1b touched no
read path — the twelve reads are untouched and `slice_params` is unchanged.
