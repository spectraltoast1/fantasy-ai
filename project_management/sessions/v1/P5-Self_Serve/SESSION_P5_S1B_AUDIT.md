# P5 · S1b Audit — the shared access code

**Reviewed:** 2026-08-04 · **By:** PM, against live code + the merged diff (`7986ff2`, `8cf01b2`, `98f8297`,
merge `c85761c`, `46af761` on `main`) and the **live Supabase project**.
**Report:** `SESSION_P5_S1B_REPORT.md` · **Brief:** `SESSION_P5_S1B_ACCESS_CODE.md`.

**Bottom line: endorse.** The gate is the un-bypassable kind and I confirmed the load-bearing fact
independently rather than from the report or the dashboard: the live project answers
`disable_signup: true`. The design insight the brief turned on — platform-signup-OFF does not imply Will
provisions anyone — is implemented exactly as specified, and the scope guard held completely. Two
corrections, one finding worth a small follow-up, and **one DoD item I could not close from a cloud session**
(since closed by Will: production returned 403 to a code-less request — the endpoint is deployed and
refusing). None of them changes the verdict.

## Verified independently (not taken from the report)

- **`disable_signup: true` on the live project.** `GET /auth/v1/settings` with the publishable key —
  the ground truth the brief insisted on, checked against the API rather than a dashboard screenshot.
  `mailer_autoconfirm: false`, as it should be. This is the property S1 shipped without.
- **Scope guard held exactly.** The full diff is 16 files: `api/` (signup, rate_limit, auth_schema,
  init_auth_schema, routes, settings), `SignIn.jsx` + `queries.js`, `scripts/`, `config.example.py`, and
  docs. **No pipeline, transform, loader, engine constant, corpus, `reads.py`, or `slice_params`.** The
  "12 reads byte-identical" claim is therefore structurally true, not merely asserted — there is no code
  path by which they could have moved.
- **The code check does what it says.** `hmac.compare_digest`; **fails closed** when nothing is
  configured (`code_matches` returns False with no code set — absent config never means "welcome"); one
  uniform refusal string with no enumeration branch; and the code is checked *before* any account is
  created or any mail is sent, so a wrong attempt costs a log row and nothing else.
- **The limiter's state genuinely survives a restart** because it is a Postgres table, and
  `rate_limit.check` runs before any work. Fail-open there / fail-closed in `signup.py` is the right
  split and is documented at both sites.
- **`access_code()` is read per call** (`os.environ.get` → `config` fallback, no caching anywhere in
  `settings.py`), so rotation really is one config change with no restart-stale value. See correction 1.

## Two corrections

1. **DoD #4 — rotation — was not demonstrated by the session. ✅ CLOSED 2026-08-04 by Will.** The report
   claimed "every DoD item is now demonstrated"; rotation was in neither `check_signup.py` (which covers
   wrong / near-miss / empty / absent / mis-cased codes, but never a *changed* one) nor the live table. The
   property holds by construction and I checked the construction — but "true by construction" is exactly
   what S1 believed about its gate. **Will then ran it on production:** rotated `ACCESS_CODE`, confirmed the
   **old code refused** *and* the **new code accepted** (both halves — a refusal alone would also be what a
   failed deploy looks like), then restored the original. Rotation is one config change, no redeploy, no
   migration, effective immediately. The claim is now evidence.
2. **"`fly.toml` runs TWO machines" is sourced to the wrong artifact.** `application/fly.toml` declares
   `auto_stop_machines`, `min_machines_running = 0` and a single `[[vm]]` block — **no machine count**.
   The count is a deploy-time property (`fly status` / `fly scale show`), not a config-file one. The
   *decision* is still correct and doesn't need the two-machine argument at all: scale-to-zero alone
   makes in-process state defeatable by waiting out the idle window. Fix the citation, keep the design.

## DoD #9 — deployed. ✅ CLOSED 2026-08-04 (Will ran the curl: **403**)

`GET /api/signup` on production returns **404**, which looks like "the route isn't deployed" and is
**not** evidence of that. `main.py` mounts the SPA at `/` with `html=True` as a catch-all; in Starlette a
full-match mount beats the router's *partial* (method-mismatch) match, so a POST-only route under a
catch-all returns 404 on GET instead of 405. I reproduced that locally before drawing any conclusion —
**the 404 is uninformative.** `curl` to `fly.dev` is blocked from a cloud PM session and WebFetch cannot
POST, so the deploy proof has to come from Will's machine:

    curl -i -X POST https://fantasy-ai-api.fly.dev/api/signup \
      -H 'Content-Type: application/json' -d '{"email":"anything@example.com"}'

**Expect `403` + `That access code isn't right.`** — no code supplied, so it is refused before anything
is created or sent, and no email budget is spent. A **404** would mean merged-but-undeployed, which is
the P0/B3 failure this project has already shipped once.

## The finding worth acting on — the limiter supplies the harm it was built to prevent

`rate_limit.check(request, email)` runs **before** the code is validated, is keyed on the
caller-supplied email, and every attempt is recorded regardless of outcome. So **five requests carrying a
known address and any garbage code lock that person out of sign-in for an hour** — no access code
required. The limiter exists to stop denial-of-sign-in against real users; in this ordering it also
hands someone a targeted one.

**Proportionality first: this is not a launch blocker and not worth its own session.** The cohort is
10–15 friends, their addresses aren't published, and nobody is attacking a preseason fantasy app. It is
also the classic account-lockout trade-off, not a mistake unique to this code.

**The fix is small and belongs to whoever next opens this file** (S2 is in the auth code anyway):
validate the code first, keep counting failures against the email and IP budgets exactly as now, but
**never let a correct code be refused by the email counter**. Brute force stays bounded by the IP limit
and by the per-email count on failures, while a real user holding the real code can always get in. The
trade-off to accept knowingly: a valid-code holder could then spend send budget, backstopped by
Supabase's own 30/hour ceiling and its per-address minimum interval.

## Minor

- **Accounts are created *confirmed* before the link is known to send.** `admin/users` with
  `email_confirm: true` runs before `/otp`, so a mailer failure leaves a confirmed account behind — which
  is precisely what happened to the `+test` address pre-SMTP. **S2 should know that an account can exist
  for an address no human has ever proved control of** when it defines ownership.
- **`invite.py` → `users.py` is a deviation from the brief's letter and the right call.** The brief said
  "keeps `--list`, gains `--ban`"; the rename follows the brief's own reasoning that it is no longer an
  invite tool. The stale references in `SIGNUP_MODEL_ASSESSMENT.md` and this session's brief are left as
  written (they are historical); the **live** doc — the P5 project map — is corrected with this audit.
- **Four non-merge commits against a "≤3" guide**, the fourth being post-merge documentation that closed
  the two open proofs. Immaterial, but the report header still reads "Commits: 3" and "merged (main
  `c85761c`)" while `main` is at `46af761`.
- **Report quality, and this is worth naming.** The `--ban` investigation — that bans bite at *token
  exchange*, not at link generation, and that a 429 looks like a refusal without being one — plus the
  volunteered note about nearly recording that 429 as a pass, are the two most valuable paragraphs in the
  report. A report that flags its own near-miss is the kind that can be audited at all.

## Bundled with this audit (doc corrections, not code)

- **`STATUS.md`:** re-stamped to 2026-08-04; the **matchup tie bug re-filed from "Deferred / parked (not
  blocking)" to a Gate-A blocker** — a freshly drafted 2026 league is the first thing that hits it; the
  **SurplusFF / surplusff.com / Resend** sending domain recorded as the live SMTP dependency.
- **`projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md`:** the session map still read **"S1b ⚠️ NOT YET
  BUILT — currently the only gate, and it is client-side."** That is the same class of stale map that
  caused the S1 failure, in the same document, three days later. Corrected to shipped.

## Post-audit finding (2026-08-04) — the custom domain and the magic-link redirect

Will pointed **surplusff.com** at the app (Fly cert + DNS live; the app loads over HTTPS). The SSL
certificate is **not** all that is required, and the gap is silent rather than loud.

**S1b removed the redirect that S1 had.** S1's `SignIn.jsx` called Supabase directly with
`emailRedirectTo: window.location.origin`. S1b re-pointed the form at `POST /api/signup`, and
`signup.py`'s `/otp` call passes **only** `{email, create_user: false}` — there is no `redirect_to`
anywhere in the codebase now (grepped: zero hits outside vendored packages). So the magic link's
destination is governed entirely by the **Supabase project's Site URL**.

**The failure mode if Site URL is still the fly.dev host:** someone signs up on surplusff.com, clicks
the link, and lands on `fantasy-ai-api.fly.dev` — where `detectSessionInUrl` stores the session in
**that origin's** localStorage. Back on surplusff.com they are still signed out, with no error. That is
precisely the "authenticates but does not persist" symptom `supabase.js` warns reads as broken, and it
would hit every cohort member if the code is texted alongside the surplusff.com URL.

**Ground truth without the dashboard:** request a link and read the URL in the email — it carries the
`redirect_to` it will use.

**Two ways to close it.** (a) Set Supabase's **Site URL** to `https://surplusff.com` and add it (plus
`www.`, if used) to the Redirect URLs allow-list — one setting, no code, and it makes fly.dev the
second-class origin. (b) Plumb an allow-listed `redirect_to` from the client through `/api/signup` — a
small code change, and the right answer only if both origins must genuinely work. **Recommend (a), and
pick one canonical origin**: two live origins means two independent session stores and a class of
"I'm signed in on one of them" confusion that is expensive to debug and cheap to avoid.

**Status: ✅ CLOSED 2026-08-04.** Will set the Supabase Site URL to surplusff.com (option a) and then
**observed the round trip**: signed out beforehand, requested a link from surplusff.com, clicked it, and
landed on surplusff.com *signed in*. The prior signed-out state matters — it rules out the test passing
for the wrong reason, since before the setting changed any link would have parked the session on the
fly.dev origin. Note the change is now bidirectional: anyone signing in from the fly.dev
host will also be returned to surplusff.com, which is correct if surplusff.com is canonical.

## For S2

Nothing in S1b constrains it. `/api/leagues` is still the one unscoped read, viewer identity is still a
league property rather than user × league, and the `ros_player_band` RLS drift still wants fixing at its
source (`--emit` should emit the `ALTER TABLE … ENABLE ROW LEVEL SECURITY` lines). Add to its inbox: the
lockout reordering above, and the confirmed-account-without-a-human case.
