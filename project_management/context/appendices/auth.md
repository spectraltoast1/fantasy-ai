# Appendix — Auth (how the front door actually works)

**Scope:** the mechanism behind ARCHITECTURE's Auth bullet. Read this when touching sign-in, keys,
the deploy plumbing, or the auth tables. Shipped P5/S1, signup model corrected in **S1b**
(2026-08-03); the session reports in `sessions/v1/P5-Self_Serve/` carry the narratives and proofs,
and `SIGNUP_MODEL_ASSESSMENT.md` records why the model changed.

---

## The gate: self-serve signup behind a shared access code

**S1 got this wrong and S1b fixed it.** The S1 brief read "word of mouth" as *provisioning* — Will
invites each person by hand — when he meant only that he wouldn't promote the site. The correction
turns on a distinction the original argument missed: **platform-signup-OFF does not imply a human
provisions people.** Turn it off, and let *the API* perform the admin action automatically when a
valid code is presented.

That gets both properties at once:

- **Zero per-user work.** The API is the admin, not Will.
- **Un-bypassable.** With platform signup off there is no public path to account creation except
  the endpoint that checks the code. The gate is not a line of client code — it is the *absence of
  any other door*. This matters concretely: the publishable key ships in the SPA bundle by design,
  so anything checked in the browser can be walked around with a direct call to Supabase. S1
  briefly shipped exactly that state, and it is what S1b exists to close.

**The code is required on every request, from everyone** — not only at account creation. That buys
a hard property: *no valid code, no email is ever sent, to anyone.* It also keeps one uniform path,
so there is no "does this account exist?" branch to leak whether an address is registered. Nothing
is lost later: when signup opens to the public, `signInWithOtp` handles create-or-send natively and
`api/signup.py` gets **deleted** rather than promoted — it is transitional scaffolding by design.

Rotation is one config change (`ACCESS_CODE` here and the Fly secret); the old value stops working
immediately, with no table to migrate. If the code spreads further than intended, the response is
`scripts/users.py --ban` on the accounts plus a rotation.

`api/signup.py` fails **closed** — missing config, unreachable Supabase, anything unexpected
refuses the request. `api/rate_limit.py` deliberately fails **open**, because it is a nuisance
control rather than an authorization one and a database hiccup should not mean nobody can sign in.

### The rate limiter is in Postgres because it has to be

`fly.toml` runs **two** machines with `min_machines_running = 0` and `auto_stop_machines = "stop"`.
In-process state would be split across both (an attacker gets ~double the budget) and, worse,
**erased whenever a machine stops** — so the limiter could be reset by waiting out the idle window.
A limiter you defeat by being patient is not a limiter. Hence `public.signup_attempts`, and hence
the check that it still bites from a brand-new process.

What it is actually defending: the code is chosen to be sayable out loud, so it is low-entropy by
construction. **Brute-force resistance is the first job**, protecting the email send budget the
second. Client IP comes from Fly's `Fly-Client-IP` header — `request.client.host` is Fly's proxy,
identical for every caller, so limiting on it would throttle all users as one.

## Custom SMTP is a hard dependency, not a nicety

Supabase's built-in auth sender is documented as **"best-effort only and intended for
non-production use cases"**, is capped at **"2 messages per hour"**, and — the decisive part —
**"will refuse to deliver messages to addresses that are not part of the project's team."**

So without custom SMTP, *no friend can receive a magic link at all*. Not slowly: not at all. That
is also why S1's invite reached Will and nobody else would have — he is the project owner.
Configuring custom SMTP raises Supabase's own baseline to 30 messages/hour.

## Token verification — asymmetric, fail-closed

`api/auth.py`'s `current_user` verifies the caller's access token (**ES256**) against the project's
published JWKS, checking `aud`, `iss` and `exp` with `require` set explicitly — a token that simply
*omits* a claim is rejected rather than skipping the check for it, which is the classic way a JWT
gate turns out to have no teeth. Not the legacy shared HS256 secret: keys rotate without a redeploy,
and the API holds nothing that can *mint* a token.

Two deliberate choices:

- **401 vs 503.** A token checked and rejected is 401. A JWKS that *couldn't be reached* is 503.
  Both deny; only one is diagnosable. Silently 401-ing every user during a JWKS outage looks like a
  fleet of bad passwords rather than an outage.
- **Nothing runs at import.** Fly is scale-to-zero, so the first request after a cold start does the
  JWKS fetch. It lives inside the dependency, wrapped, so a failure rejects a *request* instead of
  crashing the *process* and taking the public demo down with it. `pyjwt`'s own `PyJWKClient` does
  the fetch and the TTL cache, which is why `pyjwt[crypto]` is the only dependency the API gained.

## Key naming — publishable / secret, not anon / service_role

Supabase replaced the legacy `anon` / `service_role` JWTs with **publishable** (`sb_publishable_…`)
and **secret** (`sb_secret_…`) keys. Consequences here:

- They are **opaque strings, not JWTs**, so they go in the `apikey` header and **never**
  `Authorization`. Verified: `apikey` alone → 200, `Authorization` alone → **401**, both-matching →
  200 (a backward-compatibility path not worth depending on).
- **Token verification is untouched** by this — a *user's* access token is still an ES256 JWT. The
  API-key redesign and the token-verification path are separate systems.
- The **publishable** key is public by design: it ships in the JS bundle either way, and this
  project's Data API is disabled with RLS deny-by-default, so it opens nothing. The **secret** key
  is admin-grade, browser-forbidden by Supabase itself, and lives only in `application/config.py`.

## The config has to reach two places, for two different reasons

This is the part that is easy to get wrong, and it bit once during S1.

- **The SPA needs it at BUILD time.** Vite inlines `import.meta.env.VITE_*` into the bundle. A
  `frontend/.env` works in local dev and is then stripped from the build context by
  `.dockerignore`; a Fly *secret* reaches the running machine but never the builder. Both routes
  ship a bundle with `undefined` config, whose symptom — a sign-in button that does nothing — is
  indistinguishable from a stale bundle, a paused project, or a cold start. **Docker build args are
  the only route:** `ARG`/`ENV` in the Dockerfile's web stage (declared *after* `npm ci` so a key
  change doesn't bust the dependency layer), fed by `fly.toml`'s `[build.args]`.
- **The API needs `SUPABASE_URL` at RUNTIME**, to derive the JWKS endpoint and the expected issuer.
  The image ships no `config.py`, so without `fly.toml`'s `[env]` every `/api/me` returns 503 "auth
  is not configured". S1's first deploy did exactly this.
- **S1b added two runtime SECRETS**, which is a different category again: `ACCESS_CODE` and
  `SUPABASE_SECRET_KEY` are `fly secrets`, never build args (those are readable in image history)
  and never committed. So the full set is: build args for the SPA's public values, `[env]` for the
  public URL, and secrets for the two private ones.

The non-secret values are committed rather than passed as flags, so a **bare `fly deploy` stays correct** — this
project has already shipped a merged-but-undeployed change (P0/B3) and a stale bundle (S4a); a
deploy that needs a remembered flag would be a third way to break it.

**Misconfiguration fails loudly but never fatally.** `supabase` is null when unconfigured
(`REPLACE_ME` counts as unconfigured — "looks fine, sign-in quietly dead" is the worse failure), the
console names exactly what is missing, and the overlay renders an honest unavailable state. The demo
keeps working: auth being misconfigured must not cause more damage than the thing it broke.

## The auth tables live outside the generated schema — structurally

There is **no migration mechanism in this project**. The only DDL is `serve/schema.sql`, which
`build_db --emit` rewrites wholesale and `--load` applies after DROPping every table it names. An
auth table listed there would be dropped by the next full reload.

So they live in hand-written `api/auth_schema.sql` (`app_users`, and S1b's `signup_attempts`),
applied by `api/init_auth_schema.py`, whose `--verify` **asserts they are absent from the
generated DDL** — the guarantee is tested, not
documented. The row is written on first authenticated `/api/me` call rather than by a database
trigger, keeping the behaviour in reviewable code instead of invisible DDL.

**The hazard is not theoretical:** `ros_player_band` has RLS **off** while the other 13 served
tables have it on, because RLS was enabled by hand and a later `--emit`/`--load` recreated the table
without it. Any out-of-band property on a `schema.sql` table — RLS, a grant, a trigger, an FK — is
destroyed by the next full load. The durable fix is to make `--emit` emit the RLS lines (S2).

## The client seam

The bearer token attaches in exactly one place: `queries.js`'s `apiGet`, as a module-level
`_token`/`setAuthToken` pair mirroring the `_slice`/`setActiveSlice` pattern beside it. No view
component knows auth exists. S1b added `apiPost` alongside it for the signup call — `apiGet` merges
the active slice into every request (an auth call has no business carrying a `league_id`) and
discards the response body, whereas signup is the first endpoint whose message *is* the feature and
has to reach the person typing. `App.jsx` republishes the token on **every** `onAuthStateChange` event,
not just sign-in — that event also fires on `TOKEN_REFRESHED`, and a token that stops being
republished there starts failing silently about an hour in. Session persistence and refresh are
supabase-js's own, never hand-rolled: magic-link auth that authenticates but doesn't persist emails
the user on every visit, which reads as broken.
