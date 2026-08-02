# Appendix — Auth (how the front door actually works)

**Scope:** the mechanism behind ARCHITECTURE's Auth bullet. Read this when touching sign-in, keys,
the deploy plumbing, or the `app_users` table. Shipped P5/S1 (2026-08-02);
`sessions/v1/P5-Self_Serve/SESSION_P5_S1_REPORT.md` has the session narrative and the proofs.

---

## The invite gate is a project setting, not app code

Account creation is off at the Supabase project ("allow new users to sign up"). There is therefore
**no signup path for app code to guard, and no invite-list table to get wrong** — a check in code
can be bypassed if any other signup path exists; a project that refuses to create users has no such
path. `scripts/invite.py` (`invite <email>` / `--list`) is the one sanctioned way in.

Measured behaviour, same endpoint and key each time, account state the only variable:

| account state | result |
|---|---|
| uninvited, `create_user=false` (what the SPA sends) | 422 `otp_disabled` |
| uninvited, `create_user=true` (a sloppier client) | 422 `signup_disabled` |
| invited but **unconfirmed** | 422 `signup_disabled` |
| invited **and confirmed** | passes the gate |

**The unconfirmed row is an onboarding fact worth knowing:** an invited-but-unconfirmed account
still looks like a *signup* to GoTrue, so magic link is refused until the invite is accepted once.
The invite email is a one-time bootstrap; after it, magic link works normally. Expect at least one
"I was invited and it says signups are disabled" report.

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

Both are committed rather than passed as flags, so a **bare `fly deploy` stays correct** — this
project has already shipped a merged-but-undeployed change (P0/B3) and a stale bundle (S4a); a
deploy that needs a remembered flag would be a third way to break it.

**Misconfiguration fails loudly but never fatally.** `supabase` is null when unconfigured
(`REPLACE_ME` counts as unconfigured — "looks fine, sign-in quietly dead" is the worse failure), the
console names exactly what is missing, and the overlay renders an honest unavailable state. The demo
keeps working: auth being misconfigured must not cause more damage than the thing it broke.

## `app_users` lives outside the generated schema — structurally

There is **no migration mechanism in this project**. The only DDL is `serve/schema.sql`, which
`build_db --emit` rewrites wholesale and `--load` applies after DROPping every table it names. An
auth table listed there would be dropped by the next full reload.

So it lives in hand-written `api/auth_schema.sql`, applied by `api/init_auth_schema.py`, whose
`--verify` **asserts the table is absent from the generated DDL** — the guarantee is tested, not
documented. The row is written on first authenticated `/api/me` call rather than by a database
trigger, keeping the behaviour in reviewable code instead of invisible DDL.

**The hazard is not theoretical:** `ros_player_band` has RLS **off** while the other 13 served
tables have it on, because RLS was enabled by hand and a later `--emit`/`--load` recreated the table
without it. Any out-of-band property on a `schema.sql` table — RLS, a grant, a trigger, an FK — is
destroyed by the next full load. The durable fix is to make `--emit` emit the RLS lines (S2).

## The client seam

The bearer token attaches in exactly one place: `queries.js`'s `apiGet`, as a module-level
`_token`/`setAuthToken` pair mirroring the `_slice`/`setActiveSlice` pattern beside it. No view
component knows auth exists. `App.jsx` republishes the token on **every** `onAuthStateChange` event,
not just sign-in — that event also fires on `TOKEN_REFRESHED`, and a token that stops being
republished there starts failing silently about an hour in. Session persistence and refresh are
supabase-js's own, never hand-rolled: magic-link auth that authenticates but doesn't persist emails
the user on every visit, which reads as broken.
