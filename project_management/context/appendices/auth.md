# Appendix — Auth (how the front door actually works)

**Current as of:** 2026-08-11 (re-stamped by S2c).
**Scope:** the mechanism behind ARCHITECTURE's Auth and Ownership bullets. Read this when touching
sign-in, keys, the deploy plumbing, or the app-side tables. Shipped P5/S1, signup model corrected in
**S1b** (2026-08-03), ownership + the scoped catalog added in **S2a** (2026-08-09), the reads scoped
in **S2b** (2026-08-10), and the punch list closed in **S2c** (2026-08-11: the season derived
locally, the signup check order, the constraint assertions, the client's session-lost copy); the
session reports in `sessions/v1/P5-Self_Serve/` carry the narratives and proofs, and
`SIGNUP_MODEL_ASSESSMENT.md` records why the signup model changed.

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

`fly.toml` sets `min_machines_running = 0` and `auto_stop_machines = "stop"`, so in-process state is
**erased whenever the machine stops** — the limiter could be reset by simply waiting out the idle
window, and a limiter you defeat by being patient is not a limiter. On top of that the budget would
be **split across machines**, and there are **two** (measured 2026-08-11: `fly scale show` →
`app │ 2 │ … │ iad(2)`) — so an attacker would get roughly double, non-deterministically, which also
makes "the limit bites" flaky to demonstrate. The count is a **deploy-time property, not something
`fly.toml` declares**: this appendix used to cite `fly.toml` for it, the S1b audit correctly called
that citation wrong, and S2c finally ran the command. Hence `public.signup_attempts`, and hence the
check that it still bites from a brand-new process.

What it is actually defending: the code is chosen to be sayable out loud, so it is low-entropy by
construction. **Brute-force resistance is the first job**, protecting the email send budget the
second. Client IP comes from Fly's `Fly-Client-IP` header — `request.client.host` is Fly's proxy,
identical for every caller, so limiting on it would throttle all users as one.

### The order of the checks, which is the rule (S2c)

**The email counter only ever counts requests that presented a VALID access code.**

S1b applied the email limit *first*, keyed on the caller-supplied address, and recorded every
attempt regardless of outcome. So five requests carrying somebody's address and any garbage code
locked that person out of sign-in for an hour — no access code required. The limiter was handing
out the exact harm it exists to prevent, and it is the reason this is stated as a rule rather than
as a reordering.

`POST /api/signup` now runs: **config gate (503) → IP limit → validate the code → email limit →
send.** The IP limit is safe to apply first precisely because it is keyed on the caller's own
address: it cannot be aimed at anyone else, and it is the limit that actually bounds brute-forcing
a low-entropy code. A wrong code is recorded with a **NULL email**, which is invisible to
`count(*) FILTER (WHERE email = …)` while the IP filter still counts it — that single detail is the
whole mechanism. Both counts come from one query, so the two enforcement points describe the same
instant and cost no extra round trip.

The trade-off, accepted knowingly: someone holding a valid code can spend send budget, backstopped
by Supabase's own hourly ceiling and its per-address minimum interval. `check_signup` asserts both
halves from fixtures — including that a **correct** code from a rate-limited IP is still refused,
since knowing the code must not be a bypass — and re-runs them against the pre-S2c ordering, where
the victim gets a 429 while holding the right code.

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

## The app-side tables live outside the generated schema — structurally

There is **no migration mechanism in this project**. The only DDL is `serve/schema.sql`, which
`build_db --emit` rewrites wholesale and `--load` applies after DROPping every table it names. An
auth table listed there would be dropped by the next full reload.

So they live in hand-written `api/auth_schema.sql` — `app_users`, S1b's `signup_attempts` and S2a's
`user_leagues` — applied by `api/init_auth_schema.py`, whose `--verify` **asserts they are absent
from the generated DDL**: the guarantee is tested, not documented. Adding a table is one entry in
`_TABLES` and it inherits the column dump and the leak check; S2c removed one the same way
(`nfl_state_cache`, retired with the Sleeper call it cached, dropped by an idempotent statement in
the same file rather than by hand). The `app_users` row is written on first authenticated `/api/me`
call rather than by a database trigger, keeping the behaviour in reviewable code instead of
invisible DDL.

**`--verify` asserts constraints, not just columns (S2c, S2a audit F2).** The FKs on
`user_leagues.user_id` and `app_users.id` must exist *and* carry `ON DELETE CASCADE`
(`pg_constraint.confdeltype = 'c'`), and orphan rows are counted. S2b deleted two accounts and
observed zero leftover rows, which is a measurement; `CREATE TABLE IF NOT EXISTS` is a no-op on an
existing table, so a database that already had these tables in another shape keeps that shape and
nothing notices. Same trap as `_ALTERED_COLUMNS`, one level down.

**The hazard is not theoretical:** `ros_player_band` has RLS **off** while the other 13 served
tables have it on, because RLS was enabled by hand and a later `--emit`/`--load` recreated the table
without it. Any out-of-band property on a `schema.sql` table — RLS, a grant, a trigger, an FK — is
destroyed by the next full load. The durable fix is to make `--emit` emit the RLS lines.
**That fix is NOT S2c's** (an earlier version of this appendix said it was): proving it bites means
re-running `--load`, which DROPs every table it names against the single Supabase project that also
serves production. It is a scheduled event, not a punch-list line — it rides with **S2d**, the other
store-touching session, or takes its own slot.

## Ownership and visibility (S2a)

Visibility is **one predicate in one function** (`reads.visible`), so there is one place to get it
wrong and one place to test:

    visible(league) = (league_id == DEMO_LEAGUE_ID) OR (owned by caller AND season == current)

**The demo term is first and season-independent, and that ordering is load-bearing.** The demo is a
2025 league living in the 2026 season; expressed as a global `season = current` filter it disappears,
and a missing demo reads as an auth bug rather than as the filter it is.

**Ownership is `public.user_leagues`** — `(user_id, league_id)`, cascading off `auth.users`. No
`season` column on purpose: a redraft `league_id` already pins one `(league, season)` slice, so a
season here would be a second copy of a fact `demo_manifest` holds, and the two would eventually
disagree. It is read **per request**, never carried in the token, so a revoke bites immediately
rather than an hour later (demonstrated: a revoke changed the catalog for an access token that had
already been issued).

**A grant is an operator act about a league, not evidence about a person.** S1b creates accounts
`email_confirm: true` *before* the magic link is known to have sent, so an address nobody controls
can hold a confirmed account. S4's connect flow writes the same row from the other direction — a user
claiming their own league — and that is where identity actually gets established.

> **Decided, S2c: the ownership model does not care, and nothing is built for it.** An account
> confers nothing on its own. Visibility needs a grant, a grant is an operator act, and signing up
> never creates one — so a confirmed account with nobody behind it holds zero grants and reads
> exactly what a signed-out visitor reads: the demo. Reordering create-after-send would not be a
> reorder anyway (`/otp` with `create_user: false` refuses an address with no account), so it would
> be real machinery for a non-problem.
>
> **The tripwire, which is the part worth keeping:** this stops being true the moment an account can
> claim a league **by itself**. If S4's connect flow ever grants ownership without an operator in
> the loop, "confirmed" starts to carry weight and the create-before-send ordering becomes a real
> defect. **Revisit at S4.** The same note sits at the `email_confirm: true` call site in
> `api/signup.py`, so the next reader of that line does not re-raise it from scratch.

**"Current season" is derived locally (S2c) — there is no third party on the request path.** It is
the calendar year, or the year before it until **August 1**, from `settings.current_season`. The
boundary deliberately **leads** Sleeper's own flip by a few days because the error directions are
not symmetric: flipping early drops last season's league from a catalog slightly sooner than
necessary, which nobody notices; flipping late hides the league somebody has just connected.

Until S2c this resolved Sleeper's `/v1/state/nfl` through a `public.nfl_state_cache` last-known-good
and failed closed. That whole apparatus — the 5s timeout, the 12h TTL, the stale-cache branch, the
unresolved branch, the table — existed to survive a Sleeper outage, and S2b had put it on **eleven**
endpoints (audit F6). On a single 256mb machine with shared workers the realistic failure was worker
exhaustion taking the public demo down, not slow pages. Deleting a fail-closed path would normally
be alarming; it is right here, because **removing the failure beats handling it** — after this there
is no third party to fail. What remains fail-closed is the predicate's own contract: `reads.visible`
still denies the owned term on an unresolvable season, kept because the function is pure, public and
holds eleven call sites, so its contract is its signature rather than today's callers.

**Sleeper is now an assertion, not a dependency.** `check_ownership` fetches `/v1/state/nfl` once and
fails loudly if it disagrees with the derived value, so drift is still caught — just not by every
page load. Unreachable is a failure there rather than a skip: a gate reporting agreement it never
checked is green having verified nothing.

**`CURRENT_SEASON` is the documented manual lever**, process-env only, with no `config.py` fallback
on purpose. It is how the ownership proofs run against deployed code (the corpus tops out at 2025),
and how the rollover gets moved by hand if the calendar rule ever disagrees with the real season. An
override that can hide in a gitignored file is the failure mode, so it goes in plain `[env]` — and
**`/health` publishes the resolved season and its source** (S2a audit F7), so a stray override
cannot hide behind a startup log line nobody re-reads. `/health` stays DB-free, which the runbook
depends on, and after S2c it is DB-free *by construction*: the derivation is `os.environ` plus the
calendar.

**Catalog ordering is the landing rule.** The SPA lands on `leagues[0]`, so "a caller's own leagues
first, the demo last" is what decides where a signed-in user lands. Two SPA-shaped constraints are
enforced in `reads.build_catalog` because both fail silently: `/api/leagues` must never 401
(`loadLeagues` only `console.error`s, leaving a permanent "Loading…") and must never return zero
leagues (`if (lgs.length)` guards the only slice selection).

## Scoping the reads — the seam, and why it is shaped this way (S2b)

S2a closed *discovery*. S2b closed *access*: every one of the eleven per-panel reads now inherits the
predicate from **one** place, `routes.slice_params`, which is a thin adapter over the pure
`reads.authorize_slice`. Pure and injectable on purpose — `check_ownership` is a gate people actually
run because it needs no server and no accounts, and burying the decision inside a FastAPI dependency
would have made the isolation matrix runnable only against two live Supabase users.

**Existence and season come from `teams`, not `demo_manifest`.** `slice_exists` read the catalog, which
made *catalog membership* double as the authorization boundary — true only because the manifest happens
to hold exactly the demo set, and false the moment S4 gives a real user a league that has data before it
is catalogued. One combined query answers existence, season, ownership and the granted seat, which is
also what makes the work symmetric: a nonexistent league and an existing-but-unowned one cost the same
lookups, so the response time cannot leak what the status code does not.

**The refusal is one exception type, and the 404 detail is a constant.** It used to echo the
`league_id`, which meant an unowned 404 and a nonexistent 404 could never be the same bytes — the whole
no-enumeration design rested on a comparison nobody could make. `SliceUnavailable` (503) is deliberately
separate: an unset `DEMO_LEAGUE_ID`, or a league with two seasons in the store, is a deploy problem, and
answering "unknown league_id" would hide an outage behind an authorization message for as long as nobody
looked.

**The season resolves last.** `visible` short-circuits — the demo needs no season, an unowned league
needs no season — which is what keeps the two refusal branches timing-identical. S2b was right that
this was call ordering rather than a fix for audit F6; **S2c fixed F6 at the source** by making the
season a local derivation with no I/O, so the ordering is no longer load-bearing for latency. It
stays because the timing symmetry of the two refusals still is.

**The viewer seat became a user × league property**: `user_leagues.roster_id`, added by an explicit
`ALTER TABLE … ADD COLUMN IF NOT EXISTS` (a column inside `CREATE TABLE IF NOT EXISTS` would never
appear on a database that already has the table — the F2 trap), asserted by `verify()`, settable as
`--grant EMAIL LEAGUE_ID [ROSTER_ID]`. The load-bearing part is that **`build_catalog` emits it**: the
client sends back whatever the catalog told it, and `authorize_slice` honours a caller-supplied seat, so
a grant that only changed the server's fallback would have shipped and never fired. Caller-supplied
still wins, because viewing your own league *as* another manager is a feature the dossiers depend on;
what was ever the bug is reaching into a league you cannot see.

**Denied reads are counted and nothing acts on the count** (settled with Will). No cap: blind
enumeration of 19-digit ids is implausible, the realistic attacker knows one id and needs one request,
and a limiter keyed on caller-supplied input is the S1b bug. It is an in-process integer, not a row,
because a DB write on an unauthenticated path is attacker-triggerable write amplification — and because
a counter that fired on *unowned* but not on *nonexistent* would rebuild the timing oracle the single
lookup exists to prevent.

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

**S2a made the ORDER load-bearing too.** The catalog effect used to run alongside `getSession()`
rather than after it — correct while `/api/leagues` was unscoped, and a bug the moment it wasn't:
`getSession()` is async, so the first catalog request went out with no token and a signed-in user
landed on the demo until they reloaded. The catalog now waits on an `authReady` flag and refetches
on identity change. **"Identity changed" means the USER ID changed — not that an event named
`SIGNED_IN` arrived (S2c).** supabase-js reports a tab **refocus** as `SIGNED_IN`, so keying off the
event name meant switching tabs and coming back cleared the slice and refetched: league, season,
week and the whole drill-down stack, gone, for a person who did nothing. A `useRef` holds the
last-seen id (the subscription's `[]`-deps closure would capture `session` as `null` forever), the
first event only records it, and `SIGNED_OUT` counts as a change *to null* — which is what keeps the
rejected-token rescue below working, since it depends on this branch clearing the poisoned slice.
Comparing ids also subsumes the old event filter: `TOKEN_REFRESHED` is the same person, and that is
now a fact about the id rather than a list of event names to keep in sync with the library.

That fix also **retired the `lastPath` de-dupe in `analytics.js`** — it existed only to swallow the
duplicate pageview the spurious refetch caused. Measured after the change: five consecutive
refocuses fire **zero** pageviews, three real tab clicks fire exactly three.

Sign-out clears the **selection** (`setActiveSlice({})`,
`setSlice(null)`), not just the list: a stale `league_id`/`viewer_roster_id` left in `queries.js`
would keep riding on every request — the previous person's league still on screen. `authReady` also
flips immediately when `supabase` is null (an unconfigured build), because a permanently-false flag
would hang every visitor on "Loading…" — auth breaking must not break the app around it.

**S2b had to make a rejected token survivable, because it multiplied the exposure by eleven.** Before
it, only `/api/leagues` could 401; after it every read can, and `apiGet` threw on any non-2xx while the
app-shell loaders only `console.error` — i.e. a permanent "Loading…" for signed-in users on an expired
token, a deleted account, or a Supabase outage. `apiGet` now attaches `err.status` and, on a **401**,
drops the token and retries once anonymously. That alone does not rescue anything: `_slice` still names
a league the anonymous caller cannot see, so the retry 404s. So it also calls `setOnAuthRejected`, which
`App` wires to `supabase.auth.signOut()` — that fires `SIGNED_OUT`, which clears the slice and refetches
the catalog, and *that* is what lands the visitor on the public demo. Strictly less access than they
had, never more, and the server still refuses the bad token either way. A **503** is retried once but
never signs anyone out: a verifier outage or a Fly cold start is not a bad credential.

**S2c gave the transition a voice** (S2a audit F1's remaining half). The rescue worked and said
nothing — a signed-in person was dropped onto the public demo with no explanation. A banner now
reads *"We couldn't restore your session — showing the public demo"* with a sign-in prompt. It is
keyed on the discriminator `apiGet` already computed, `Boolean(sent) && res.status === 401`, where
`sent` is the token snapshot taken *before* the fetch — so it fires only when a token was actually
present and rejected. **A visitor who was never signed in is in a normal state, not an error state**,
and sees nothing. It is a dismissible banner rather than a modal because the app underneath is
genuinely working, on the demo, which is what the copy says.

S2c also gave `loadLeagues` a real failure state. Its rejection only `console.error`d, so `slice`
stayed `null` and the shell rendered "Loading…" **forever** — a spinner that will never resolve,
describing an error as progress. `/api/leagues` never 401ing is a property `build_catalog` enforces;
it is not a reason for the client to have no answer when the call fails anyway.
