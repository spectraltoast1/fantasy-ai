# P5 · S1 — Auth + user model + invite gate — report

**Ran:** 2026-08-02 · **Brief:** `SESSION_P5_S1_AUTH_AND_INVITE.md` · **Commits:** 3 ·
**Deployed:** https://fantasy-ai-api.fly.dev/ (bundle `index-sniu4dKP.js`)

---

## Verdict

**The app has a front door and it is live.** An invited person can sign in with a magic link; an
uninvited address is refused two independent ways; `/api/me` returns a verified identity or a 401;
and all twelve existing reads are byte-identical to their pre-session payloads. This is the
**identity** half only — every read except `/api/me` is deliberately still open, because
authentication without per-user scoping is a half-gate, and closing + scoping the reads is one
coherent change with one coherent proof (S2).

Two things the brief didn't anticipate, both real: **Supabase has replaced the anon/service_role
keys** with publishable/secret keys (Will caught this), and **the SPA's Supabase config has no
route into the image except a Docker build arg**. A third was mine — see *What I got wrong*.

---

## What shipped

| | |
|---|---|
| `api/auth.py` | `current_user` dependency: ES256 verification against the project's JWKS, bounded-TTL cache, fail-closed |
| `api/routes.py` | `GET /api/me` — the one gated endpoint; upserts the profile row on first authenticated call |
| `api/auth_schema.sql` + `init_auth_schema.py` | `public.app_users`, deliberately **outside** the generated DDL |
| `api/db.py` | `execute()` — the API's first write helper |
| `api/settings.py` | `supabase_url()` / `supabase_secret_key()`, env-first like everything else |
| `api/check_auth.py` | the offline gate proof |
| `scripts/invite.py` | `invite <email>` / `--list`, the one sanctioned way in |
| `frontend/src/supabase.js`, `SignIn.jsx` | the client + a magic-link overlay |
| `frontend/src/queries.js`, `App.jsx`, `styles.css` | token attach, auth state, the identity slot |
| `Dockerfile`, `fly.toml` | build args for the SPA, `[env]` for the API |

One dependency per side, as instructed: `pyjwt[crypto]==2.13.0` and `@supabase/supabase-js`.

---

## The gate, and why it lives in the platform

Account creation is off at the *project*, so there is no signup path for app code to guard — and
therefore no app-side allow-list to get wrong. `scripts/invite.py` is the only way in. Proven
against the live project, same endpoint and key each time, the account state being the only
variable:

| attempt | result |
|---|---|
| uninvited address, `create_user=false` (what the app sends) | **422 `otp_disabled`** |
| uninvited address, `create_user=true` (a sloppier client) | **422 `signup_disabled`** |
| invited but **unconfirmed** | **422 `signup_disabled`** |
| invited **and confirmed** | passes the gate (reached the mailer) |

The second row is the argument for the platform gate stated as evidence: even a client that *asks*
to create a user is refused, because the refusal isn't in the client.

**The unconfirmed row is a real onboarding fact, not a bug.** An invited-but-unconfirmed account
still looks like a signup to GoTrue, so magic link is refused until the invite is accepted once.
The invite email is a **one-time bootstrap**; after it, magic link works normally. Worth knowing
before someone reports "I was invited and it says signups are disabled."

---

## Proof

**Offline** (`check_auth.py`, DB-free and JWKS-stubbed) — accepts a correct token; rejects a token
signed by the wrong key, an expired one, one missing `sub`, one missing `exp`, one for the wrong
audience, one from the wrong issuer, structural garbage, and an **`alg: none`** token (the classic
JWT bypass). Plus header parsing: no header, empty Bearer, wrong scheme, bare token.

**Live, against production:**

| check | result |
|---|---|
| `/api/me` no token / garbage / forged / expired | **401** each |
| the forged token carried the project's **real `kid`** | so the live JWKS was fetched to reject it — the verifier is genuinely talking to Supabase |
| resolved signing key vs the published JWKS | `x` and `y` **byte-match** |
| JWKS unreachable (pointed at a dead project) | **503**, not 401 — denied either way, but an outage stays distinguishable from a bad credential |
| **parity: all 12 reads vs the pre-session baseline** | **12/12 byte-identical** |
| served bundle contains the project ref + publishable key | yes — positive proof the build arg landed |
| control build without the args | ref absent, loud error present instead |
| **secret key anywhere in the bundle** | **no** — the `sb_secret_` grep hit is supabase-js's own key-format check, `n.startsWith("sb_secret_")`; the actual key does not appear |
| logged-out demo | renders in full, console clean |

**Not yet demonstrated, and honestly so:** Will signing in end to end, and the session surviving a
browser restart (DoD 1 and 4). Both need his browser and his inbox. He has an invite email; the
magic-link retry hit Supabase's free-tier email rate limit (**429 `over_email_send_rate_limit`**)
during verification — the risk flagged when the session was planned, now observed. It throttles
*testing*, not real use, and custom SMTP stays out of scope per the brief.

---

## What I got wrong

**I designed the config-missing failure as a `throw` at module load.** Since `App.jsx` imports the
Supabase client, that would have taken down the **entire public demo** whenever a deploy shipped
without its build args — and "logged-out visitors keep browsing" is a settled requirement. The
misconfiguration would have caused strictly more damage than the thing it broke. Now: `supabase` is
null when unconfigured (fly.toml's `REPLACE_ME` placeholder counts as unconfigured, since "looks
fine, sign-in quietly dead" is the worse failure), the console names exactly what's missing and
where it comes from, and the overlay renders an honest unavailable state. Verified by running with
no config at all: the demo renders in full.

**I planned the build-time config path carefully and missed that the API needs `SUPABASE_URL` at
runtime too.** The first deploy 503'd every `/api/me` with "auth is not configured". The
post-deploy check caught it within a minute; the fix is `[env]` in `fly.toml`. Needing the same
value in two places, for two different reasons, is the easy thing to miss here.

**Twice during verification I announced a conclusion my own output didn't support** — reading a
status code without reading the error body. A 400 was `email_address_invalid` (Supabase rejects
`example.com`), not a gate refusal; a 429 was the email rate limit, not a gate refusal. Both times
the real signal was the *error code*, and both times it pointed the opposite way. Corrected in the
table above; noting it because a confident wrong reading is worse than no reading.

---

## Supabase's new API keys (Will's correction)

`anon` / `service_role` are legacy; the current keys are **publishable** (`sb_publishable_…`) and
**secret** (`sb_secret_…`). They matter here in three ways:

1. **They are opaque strings, not JWTs**, so they belong in the `apikey` header and **not** in
   `Authorization`. Verified: `apikey` alone → 200, `Authorization` alone → **401**, both-matching
   → 200 (a backward-compatibility path worth not depending on). `scripts/invite.py` sends `apikey`
   only.
2. **Token verification is unaffected** — a *user's* access token is still an ES256 JWT checked
   against the JWKS. The API-key redesign and the token-verification path are separate systems.
3. The project was **already on asymmetric keys**, so no legacy-HS256 migration was needed — the
   single largest unknown going in, resolved in our favour.

---

## The build-arg problem (the brief's blind spot)

Vite inlines `import.meta.env.VITE_*` at **build** time. A `frontend/.env` works perfectly in local
dev and is then **stripped from the build context** by `.dockerignore`; a Fly secret reaches the
running machine but never the builder. Both routes therefore ship a bundle with `undefined` config
whose symptom — a sign-in button that does nothing — is indistinguishable from a stale bundle, a
paused project, or a cold start.

So: `ARG`/`ENV` in the Dockerfile's web stage (after `npm ci`, so a key change doesn't bust the
dependency layer) fed by `fly.toml`'s `[build.args]`. Committed, so a **bare `fly deploy` stays
correct** — this project has already shipped a merged-but-undeployed change (P0/B3) and a stale
bundle (S4a), and a deploy needing a remembered flag would be a third way to break it. The
publishable key is public by design and the Data API is disabled with RLS deny-by-default, so it
opens nothing.

---

## Where `app_users` lives, and why it is not in `schema.sql`

There is **no migration mechanism in this project** — the only DDL is `serve/schema.sql`, which
`--emit` rewrites wholesale and `--load` applies after DROPping every table it names. An auth table
listed there would be dropped by the next full reload. So it lives in hand-written
`api/auth_schema.sql`, and `init_auth_schema.py --verify` **asserts the table is absent from the
generated DDL** — the guarantee is tested, not documented.

The hazard is not theoretical: **`ros_player_band` has RLS off while the other 13 have it on**,
because RLS was enabled by hand and a later `--emit`/`--load` recreated the table without it. Any
out-of-band property on a `schema.sql` table — RLS, a grant, a trigger, an FK — is destroyed by the
next full load. Logged in STATUS for **S2**; the durable fix is to make `--emit` emit the RLS lines.

---

## For S2

- **Per-user isolation is the whole job**, in the API layer (the owner role bypasses RLS, so this
  is not an RLS-policy build). `slice_params` is the natural chokepoint.
- **`/api/leagues` is the one unscoped read** and currently hands every caller all 31 demo slices.
- **Viewer identity must become a property of *user × league***, not of a league, or two people in
  the same league get the same "you".
- The security rule Will's demo decision buys: *demo slices are world-readable; user slices require
  their owner.* One sentence, and testable.
- **Fix the `ros_player_band` RLS drift at its source** while in there.
- Note the top bar now has one identity widget; the fake `myOwner` avatar is gone when signed in.
