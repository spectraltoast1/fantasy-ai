# V1 · P5 · Session S2c — The punch list · REPORT

**Shipped 2026-08-11.** Brief: `SESSION_P5_S2C_PUNCH_LIST.md`. Sources: `SESSION_P5_S2A_AUDIT.md`
(F1/F2/F5/F6/F7), `SESSION_P5_S2B_AUDIT.md` (finding A), `SESSION_P5_S1B_AUDIT.md` (the limiter
ordering, the `email_confirm` note). **Next:** `SESSION_P5_S2D_DEMO_CLONE_AND_SELECTOR.md`.

Nine independent items, three commits. No open security hole among them — S2b closed the last one.
This was the set of places where a rule was written down but not enforced, proven but not
re-provable, handled but not observable, or fixed in the engine but not in the copy the user reads.

---

## 1 + 3 — The season is ours now, and it is visible (audit F6, F7)

**The priority, and it was an availability fix rather than a security one.** S2b made the season
resolve on every owned read, so a long Sleeper outage cost 5s per read across eleven endpoints on a
single 256mb machine with shared workers. The realistic failure was **worker exhaustion taking the
public demo down**, not slow pages.

`settings.current_season(today=None)` now derives the season: the calendar year, or the year before
it until **August 1**. `application/api/nfl_state.py` is **deleted**, and with it
`public.nfl_state_cache`, the 5s timeout, the 12h TTL, the stale-cache branch and the
unresolved/fail-closed branch.

**On deleting a fail-closed path — which normally should be alarming.** It is correct here, and the
reason is worth stating rather than leaving a reviewer to wonder: fail-closed existed to survive a
*third-party outage*, and after this there is no third party in the path. **Removing the failure
beats handling it.** A fail-closed branch for a failure that cannot occur is dead code that implies
a risk that is gone.

What was deliberately *kept*: `reads.visible` still denies the owned term when `current_season is
None`. No live caller can reach that now — but "unreachable" is a claim about every caller, and
`visible` is pure, public and just acquired eleven call sites, so its contract is its signature
rather than today's call list. Deleting it would not even give a clean error: `int(None)` raises
*inside an authorization predicate*, i.e. a 500 on a read. Two lines keep it total and the deny
direction is the safe one. **Its comment was the actual work** — it described fail-closed-during-a-
Sleeper-outage, a scenario this session deleted, and leaving that would have been the same defect as
item 8 committed in the session that fixes item 8.

**Where it landed, and why not a module of its own.** Env-first with a computed default is
structurally identical to `access_code()` and `demo_league_id()` — the idiom `settings.py` already
holds. A module named after a third party it no longer touches is a name that will mislead someone.

**Why the boundary leads Sleeper.** The error directions are not symmetric. Flipping early drops
last season's league from a catalog slightly sooner than necessary, which nobody notices; flipping
late hides the league somebody *just* connected. Lead, don't lag.

**Sleeper became an assertion, not a dependency.** `check_ownership.check_sleeper_agrees` fetches
`/v1/state/nfl` once and fails loudly on disagreement. Unreachable is a **failure there, not a
skip** — a gate printing "Sleeper agrees" without having asked is green having verified nothing,
which is precisely the defect item 5 exists to remove.

`CURRENT_SEASON` survives as the **documented manual lever** (reframed in `fly.toml`,
`config.example.py` and the module docstring; still process-env-only, still absent from the deploy).
`/health` now returns `{"status","season","season_source"}` — audit F7, turning a startup log line
read once into a property anyone can check at any time. **It stays DB-free**, which the runbook's
whole diagnostic rests on, and now by *construction*: the derivation is `os.environ` plus the
calendar.

### Proof

| assertion | result |
|---|---|
| the derivation, **11 dates** spanning Aug 1 in both directions and New Year in both (incl. a leap day) | all correct — testing the function, not the clock |
| env override honoured; reported as `source: "env"`; garbage refused | ok |
| Sleeper agrees | **Sleeper 2026 = derived 2026** |
| no api module **imports** `nfl_state` | ok — parsed with `ast`, not grepped |
| the derivation references no `urllib`/`http`/`socket`/`db` | ok |
| `check_isolation` (endpoint × role matrix) | **ALL GREEN** — item 1 moved no isolation behaviour |
| `/health` over HTTP | `{"status":"ok","season":2026,"season_source":"derived"}` |

The first version of the import check **grepped** file text and failed on `init_auth_schema.py`'s
*comment* saying the table was retired — the textual-check trap this file warns about elsewhere. It
parses imports now.

---

## 2 — The email counter only counts requests bearing a valid code (S1b audit)

`routes.py` ran `rate_limit.check(request, email)` **before** the code was validated, keyed on a
caller-supplied address, and recorded every attempt regardless of outcome. Five requests carrying
somebody's address and any garbage code locked that person out of sign-in for an hour. **The limiter
was handing out the exact harm it exists to prevent, and it needed no access code to do it.**

New order: **config gate (503) → IP limit → validate the code → email limit → send.** The IP limit
is safe first precisely because it is keyed on the caller's own address — it cannot be aimed at
anyone else, and it is the limit that actually bounds brute-forcing a low-entropy code.

The mechanism is one detail: a bad code records a row with a **NULL email**, invisible to
`count(*) FILTER (WHERE email = …)` while the IP filter still counts it. `rate_limit.check` split
into `counts` / `enforce_ip` / `enforce_email` so the two limits apply at different points from
**one** query — both numbers describe the same instant, at no extra round trip. `counts_fn` is
injectable, matching `reads.authorize_slice`'s `lookup`: an ordering bug you can only exercise
against a live Supabase is one nobody re-checks after the session that wrote it.

`signup.request_link` keeps its own code check. A duplicated `compare_digest` is free, and it means
the function can never be called without one.

### Proof — both halves, from fixtures, plus prove-it-bites

- five wrong codes → 403 each, no mail sent; the victim's **email budget stays 0** while all five
  land on the attacker's IP; the victim then signs in with the correct code → **200**.
- the IP limit still bites at 15/hour → 429 on the 16th — **and refuses a *correct* code too**,
  because knowing the code must not be a bypass. (A refusal alone proves nothing; that is the half
  a naive test would skip.)
- **prove-it-bites reproduces the bug exactly**: under the pre-S2c ordering the victim gets **429
  while holding the right code** — 2 of these assertions fail, as they must.

---

## 4 — Assert the constraint, not just the column (audit F2)

`init_auth_schema.verify()` read `information_schema.columns` and nothing else: no FK, PK, index or
RLS check existed. S2b deleted two accounts and counted zero leftover rows — a fine measurement, and
not an invariant. `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so a database that
already had these tables in another shape keeps that shape and nothing notices.

`_CASCADE_FKS` now asserts the FK exists **and** carries `ON DELETE CASCADE`
(`pg_constraint.confdeltype = 'c'`), then counts orphans. `app_users.id` rides along — same query,
same risk, one list entry.

**Verified against the real database:** both FKs cascade (`user_leagues_user_id_fkey`,
`app_users_id_fkey`), **0 orphans each**. Checked the assertion is not vacuous: it returns `[]` for
a column with no FK, and `confdeltype` is a real discriminator rather than a constant.

---

## 5 — `--live` requires 401 specifically (audit F5)

`check_anonymous_is_not_denied` passed on `401 OR 503`, so on a machine with no Supabase config it
went green **having never run the verifier** — `auth.current_user` raises 503 before it looks at the
credential. The code is now recorded and named in both branches; a 503 in the default run says
plainly that the verifier did not run, and `--live` requires 401.

---

## 8 — The `/api/me` docstring describes the system as it is (S2b audit A)

It still read *"Every OTHER read stays open this session, deliberately."* True when S1 wrote it,
false since S2b merged. Worse in code than in a project doc, because whoever reads it is deciding
whether something is protected. **Replaced, not appended** — it now says what is actually different
about this endpoint (it takes `current_user` and 401s, where the reads take `optional_user` and
serve the demo) and points at `reads.authorize_slice` as the real answer.

---

## 9 — The `email_confirm` decision: **no**, and the tripwire ships with it

`signup.py` creates a confirmed account *before* the magic link is known to have sent, so a mailer
failure can leave one behind for an address nobody controls.

**Decided: the ownership model does not care, and nothing is built.** An account confers nothing on
its own — visibility needs a grant, a grant is an operator act about a league, and signing up never
creates one. An orphan confirmed account reads exactly what a signed-out visitor reads: the demo.
Reordering create-after-send would not even be a reorder (`/otp` with `create_user: false` refuses an
address with no account), so it would be real machinery for a non-problem.

**The tripwire is the part worth keeping:** this stops being true the moment an account can claim a
league **by itself**. If S4's connect flow ever grants ownership without an operator in the loop,
"confirmed" starts to carry weight and the create-before-send ordering becomes a real defect.
**Revisit at S4.** Written in two places, no code: `appendices/auth.md`, and one note at the
`email_confirm: true` call site so the next reader of that line does not re-raise it from scratch.

---

## 7 — A tab refocus is not an identity change

supabase-js reports a **refocus** as `SIGNED_IN`, and `App.jsx` treated that as an identity change:
it cleared the slice and refetched the catalog. Switch tabs, come back, and your league, season,
week and drill-down stack were gone — for doing nothing.

The epoch now bumps only when the **user id** actually changes. A `useRef` holds the last-seen id
(the subscription's `[]`-deps closure would capture `session` as `null` forever, and there was no
`useRef` anywhere in `src/`), seeded from the `getSession()` bootstrap *and* guarded by an
`undefined` sentinel on the first event — belt and braces, because whichever async path lands first
must record the boot identity without triggering a second catalog fetch. **A first draft used only
the sentinel, which had a hole**: if `INITIAL_SESSION` were never emitted, a later real sign-in
would count as "first" and skip the refetch, leaving the user on the demo.

`SIGNED_OUT` still counts, as a change *to null* — that is load-bearing, because item 6's rescue
depends on this branch clearing the poisoned slice. Comparing ids also subsumes the old event
filter: `TOKEN_REFRESHED` is the same person, now a fact about the id rather than a list of event
names to keep in sync with the library.

**The `lastPath` de-dupe in `analytics.js` is deleted**, its cause removed.

### Proof (browser, real Supabase session minted via `generate_link` → `/verify`)

| case | expected | observed |
|---|---|---|
| `SIGNED_IN`, **same** id (a refocus) | nothing lost | week 2, drill-down "Bski", back button — **all survive** |
| `SIGNED_IN`, **different** id | reset | drill-down cleared, catalog refetched |
| `SIGNED_OUT` | reset to anonymous | signed-out chrome, slice cleared |
| 5 consecutive refocuses | 0 pageviews | **0** |
| 3 real tab clicks | 3 pageviews | **3, all distinct** |

The trigger is `_notifyAllSubscribers('SIGNED_IN', session)` — the library's own notification
boundary, i.e. exactly what a refocus delivers to `App.jsx`. Stated plainly because a bare
`visibilitychange` dispatch did **not** reproduce it (supabase-js only re-emits when it actually
recovers a session), and a test that silently proves nothing is worse than no test.

---

## 6 — A rejected token now says so (audit F1's copy half)

S2b made a rejected token survivable — drop it, retry anonymously, sign out, land on the demo — and
completely silent. A signed-in person was dropped onto the public demo with no explanation.

A banner now reads **"We couldn't restore your session — showing the public demo"**, with a sign-in
prompt wired to the existing modal. It keys on the discriminator `apiGet` already computed:
`Boolean(sent) && res.status === 401`, where `sent` is the token snapshot taken *before* the fetch.
**A visitor who was never signed in is in a normal state, not an error state**, and sees nothing. A
dismissible banner rather than a modal, because the app underneath genuinely is working — on the
demo — which is what the copy says.

`loadLeagues` also got a real failure state. Its rejection only `console.error`d, so `slice` stayed
`null` and the shell rendered **"Loading…" forever** — a spinner that will never resolve, describing
an error as progress.

### Proof

- seeded a well-formed but invalid JWT → banner shown, demo rendered, bad token cleared from
  storage, **no spinner**; "Sign in again" opens the sign-in form.
- cleared storage → **no banner** for an anonymous visitor.
- valid session → **no banner**.

---

## What this session did NOT do, and why

**The `--emit` RLS fix.** It belongs here by subject, but its prove-it-bites is *"drop RLS by hand,
re-run `--emit`/`--load`, show it comes back"* — and `--load` **DROPs every table it names**, against
the single Supabase project that also serves production. It is the only item on the list that can
take the site down while it runs, and bundling a planned outage with nine local fixes lets one item
sink the other nine. **It rides with S2d**, the other store-touching session, or takes its own slot.
Every doc that attributed it to S2c was repointed this session (`appendices/auth.md`, `STATUS.md`).

---

## Docs touched (CODING_BIBLE §7 — replace, don't append)

`STATUS.md` (S2c into current state; **deleted** the F6-regression paragraph and S2a's now-false
resolver sentence — net **+6 lines** for a nine-item session, after two condensing passes) ·
`ARCHITECTURE.md` (the season bullet;
four app-side tables → three) · `appendices/auth.md` (re-stamped; the season section rewritten, the
check-order rule added, the `email_confirm` decision + tripwire, the client-seam paragraphs for items
6 and 7, the `--emit` attribution corrected, **and the "runs two machines" claim fixed** — `fly.toml`
declares no machine count; that is a deploy-time property, and the scale-to-zero argument carries
the decision alone) · `appendices/analytics.md` (the de-dupe, marked removed with the measurement) ·
`OPERATIONS.md` (the "Sleeper is down" button retired as obsolete; `/health`'s new third answer) ·
`projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md` (the session map still said "S2b next").

---

## Deploy + live proof

Deployed with `fly deploy` from the worktree's `application/`, before the merge — the tree that
shipped is byte-identical to the tree that merges, and item 2 cannot be honestly proven anywhere but
against the deployed binary.

**Order mattered, because step 5 locks the originating IP for an hour — Will's house.**

| # | step | result |
|---|---|---|
| 1 | `https://surplusff.com/health` | `{"status":"ok","season":2026,"season_source":"derived"}` — was `{"status":"ok"}` before the deploy |
| 1b | `/api/leagues` signed out | unchanged: the demo, one lineage |
| 2 | five bad codes for `+s2c-a@gmail.com` | **403 ×5**, no mail |
| 2b | what the ledger charged them to | 5 rows, **`email=NULL`**, IP-only → live counters **`by_email=0, by_ip=5`** — the fix, on production |
| 3 | the **correct** code, same address | **200 `{"sent":true}`** — a real magic link sent. Under the pre-S2c ordering this is a 429 |
| 4 | Will clicks the link, end to end | **lands signed in** — the front door works |
| 5a | bad codes until the IP limit bites | **403 … then 429** at exactly 15 recorded attempts in the window |
| 5b | the **correct** code from that IP, to a *fresh* address | **429** — an IP-limited caller is limited regardless of what they know |
| 6 | `DELETE FROM public.signup_attempts WHERE id > 20` | 15 rows removed; back to **7 rows, max(id)=20**, live counters `by_ip=0`, test-address rows `0` |

Step 5b used a fresh address deliberately: against `+s2c-a@` it would have been ambiguous which
limit fired. Step 6 is not optional — step 5 deliberately poisons the originating IP's counter for
an hour, and leaving that behind would have locked Will's house out of sign-in.

**`public.nfl_state_cache` dropped from production** (confirmed with Will first — the one destructive
DDL this session carries). Every statement in `auth_schema.sql` was audited as idempotent
beforehand; `init_auth_schema` applied it, `verify()` re-asserted the three remaining tables, both
cascading FKs and 0 orphans, and `to_regclass` confirms the table is gone. `/health` and
`/api/leagues` unaffected after the drop.

### A contradiction settled by measurement

The deploy updated **two** machines, so `fly scale show` finally got run:
`app │ 2 │ shared │ 1 │ 256 MB │ iad(2)`. `OPERATIONS.md` said **one** machine; `appendices/auth.md`
said `fly.toml` "runs two". The S1b audit was right that the *citation* was wrong — `fly.toml`
declares no count — but nobody had run the command, so the number itself had never been checked.
**Two.** Both docs now carry the measurement and its date, and the rate limiter's
split-across-machines argument turns out to be live rather than hypothetical.

---

## Definition of done

| # | requirement | state |
|---|---|---|
| 1 | no request path imports `nfl_state`; `nfl_state_cache` gone from schema + table list; the derivation proven across the August boundary **both ways** | ✅ (also dropped from the live database) |
| 2 | `check_ownership` asserts Sleeper agrees, fails loudly if not | ✅ (unreachable is a failure, not a skip) |
| 3 | five bad codes do **not** stop that address signing in — demonstrated — and the IP counter still bites | ✅ on production, both halves |
| 4 | `/health` reports season **2026** + source, still DB-free | ✅ |
| 5 | `verify()` asserts `ON DELETE CASCADE` and counts orphans | ✅ (two FKs, 0 orphans) |
| 6 | `check_ownership --live` requires **401** | ✅ |
| 7 | a rejected token produces a visible, accurate message | ✅ |
| 8 | a tab refocus leaves league, week and drill-down untouched | ✅ |
| 9 | the `/api/me` docstring describes the system as it is | ✅ |
| 10 | the `email_confirm` decision written down, where it was decided | ✅ (`appendices/auth.md` + the call site) |
| 11 | merged, **redeployed**, confirmed live, Will's sign-in round trip passes | ✅ |

**Three commits**, at the cap, one theme each: the season; the backend punch list; the client + docs.
Nine small fixes in one commit is how a green run stops meaning anything.
