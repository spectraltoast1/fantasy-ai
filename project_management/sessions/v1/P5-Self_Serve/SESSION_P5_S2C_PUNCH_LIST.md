# V1 · P5 · Session S2c — The punch list — a brief for Code

**Written 2026-08-11**, after S2b shipped and was audited. **Status:** ready to run · **Owner:** Code
drives; Will signs in once, end to end, after the deploy.
**Sources:** the S1b audit (items 2, 9), `SESSION_P5_S2A_AUDIT.md` (F1/F2/F5/F6/F7),
`SESSION_P5_S2B_AUDIT.md` (item 8). **Next:** `SESSION_P5_S2D_DEMO_CLONE_AND_SELECTOR.md`.

> **What this session does:** closes the loops. Nothing here is an open security hole — S2b shut the last
> one. This is the set of places where a rule is written down but not enforced, proven but not
> re-provable, handled but not observable, or fixed in the engine but not in the copy the user reads.

## The timing reality

**S2c runs before S2d even though S2d has the deadline.** S2b multiplied audit F6 by eleven: the season
now resolves on every owned read, so a long Sleeper outage costs 5s per read on a **single 256mb machine**,
and blocked workers are shared across visitors. The realistic failure is **worker exhaustion taking the
public demo down**, not slow pages. Item 1 retires that. Gate A is ~2 weeks out; this session is small.

## Not in this session — and why it is not just scope trimming

**The `--emit` RLS fix has moved out.** It belongs here by subject, but its prove-it-bites is *"drop RLS by
hand, re-run `--emit`/`--load`, show it comes back"* — and `--load` **DROPs every table it names**, against
the **single Supabase project that also serves production**. That makes it the only item on this list that
can take the site down while it runs. Bundling a planned outage with nine local fixes means one item can
sink the other nine. **It rides with S2d** (Will, 2026-08-11) — the other store-touching session, so
the outage happens once instead of twice. A scheduled event, not a punch-list line. **S2d's Part 3 now
also records that a `--load` would WIPE a hand-inserted demo clone**, which changes how that session's
Part 1 must be built.

## Your part, Will

**After the deploy — sign in, end to end.** Item 2 rewrites the order of checks on `POST /api/signup`,
which is the front door. Request a magic link at https://surplusff.com/ with the access code, click it,
land signed in. **If that breaks, nobody can create an account** — and unlike the isolation work, this
failure is silent until somebody tries.

**Then one URL:** `https://surplusff.com/health` should now report the season **2026** and its source. That
is item 3, and it is what makes item 1 checkable by you rather than by a log line Code read once.

**If a live run needs accounts:** same pattern as before — `willdaniel.wrd+s2c-a@gmail.com` /
`+s2c-b@gmail.com`, minted by Code, deleted at the end. Your real account stays out.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **The email counter only ever counts requests that presented a VALID access code.** That is the whole
   fix for the targeted lockout, stated as a rule rather than as a reordering. Bad-code attempts count
   against **IP only**. So: IP check first (safe — it is keyed on the caller's own address, and it is what
   stops code brute-forcing), then validate the code, then the email counter. A stranger can no longer
   spend a real person's allowance, and mailbox-flood protection survives for people who do have the code.
2. **The season derivation is local and total** — no network call in the request path, so there is nothing
   left to fail closed *about*. Delete `nfl_state_cache`, the 5s timeout, the stale-cache branch and the
   unresolved branch. They exist only to survive a failure that stops existing.
3. **Sleeper becomes an assertion, not a dependency** — `check_ownership` asks once and fails loudly if the
   derived value disagrees. Drift is still caught; it just is not caught by every page load.
4. **`CURRENT_SEASON` stays**, and is promoted from a temporary proof hack to the documented manual lever.

## The brief to paste to Code — S2c

```
Goal: V1 Project 5, Session S2c (projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md) — the punch list.
Nine independent items. No open security hole here; S2b closed the last one. Read the brief at
sessions/v1/P5-Self_Serve/SESSION_P5_S2C_PUNCH_LIST.md, plus SESSION_P5_S2A_AUDIT.md and
SESSION_P5_S2B_AUDIT.md (the findings are the source), context/CODING_BIBLE.md, SESSION_GUIDE.md.
Check each item against observable reality before executing.

1. (Audit F6 — the priority.) Own the current season; take Sleeper out of the request path.
   Derive locally: season = year, or year-1 before August 1. The August boundary is deliberately a few
   days EARLIER than Sleeper's actual flip because the error directions are not symmetric — flipping
   early drops last season's league from a catalog slightly sooner than necessary, which nobody notices;
   flipping late hides the league someone JUST connected. Lead, don't lag.
   DELETE what only existed to survive a network failure: public.nfl_state_cache, the 5s timeout, the
   stale-cache branch, the unresolved/fail-closed branch. A local derivation cannot fail, so a fail-closed
   path for it is dead code that implies a risk that is gone.
   Sleeper moves into check_ownership: fetch /v1/state/nfl ONCE and fail loudly if it disagrees with the
   derived value. Keep the CURRENT_SEASON env override; it is now the documented manual lever, not a hack.
   Prove it: the derived value is correct for a table of dates spanning the boundary in both directions
   (test the function, not the clock); Sleeper agrees today; no import of nfl_state remains in any request
   path. Remove nfl_state_cache from init_auth_schema's table list.

2. (S1b audit.) The email rate-limit counter must only count requests that presented a VALID access code.
   Today routes.py:126 runs rate_limit.check(request, email) BEFORE the code is validated, so five
   garbage-code attempts lock a known address out of sign-in for an hour. Order: IP check -> validate the
   code -> email check. A bad code records an IP failure only. Prove BOTH halves: five bad codes against
   address X do not stop X signing in with the right code; and the IP counter still stops brute-forcing.

3. (Audit F7.) Publish the resolved season + its source on the existing unauthenticated /health endpoint.
   Sleeper publishes the season publicly so this leaks nothing, and it turns a startup log line read once
   into a property anyone can check at any time. Keep /health DB-free — that property is the diagnostic
   the runbook depends on (health up + app broken = Supabase; health down = Fly).

4. (Audit F2.) Assert the constraint, not just the column. init_auth_schema.verify() must check that the
   FK on user_leagues.user_id exists AND carries ON DELETE CASCADE (pg_constraint.confdeltype = 'c'), and
   count orphans. S2b measured 0 orphans once; a measurement is not an invariant.

5. (Audit F5.) check_ownership.py:312 passes on 401 OR 503, so on a machine with no Supabase config it
   goes green having never verified a token. Record which code came back; make the --live run require 401.

6. (Audit F1 — the COPY; S2b already shipped the mechanism.) apiGet drops a rejected token and retries
   anonymously, but the sign-out is silent. Add the user-facing state: "We couldn't restore your session —
   showing the public demo", plus a sign-in prompt. ONLY when a token was actually present and rejected —
   a visitor who was never signed in is in a normal state, not an error state. Give the surfaces a real
   error state instead of an infinite "Loading...".

7. (PM.) A tab refocus resets the user's place. supabase-js reports a REFOCUS as SIGNED_IN, and S2a treats
   SIGNED_IN as an identity change, so it clears the slice and refetches the catalog — switch tabs and come
   back and your league, week and drill-down are gone. Bump identityEpoch only when the user id actually
   CHANGES. That also retires the pageview de-dupe hack in analytics.js.

8. (S2b audit A.) routes.py:92 — /api/me's docstring still says "Every OTHER read stays open this session,
   deliberately". True when S1 wrote it, false since S2b merged. A docstring on the auth endpoint telling
   the next reader the reads are open is worse than the same drift in a project doc. Replace, don't append.

9. (S1b audit.) signup.py creates accounts with email_confirm: true BEFORE the magic link is known to have
   sent, so a mailer failure leaves a confirmed account with nobody behind it. DECIDE whether the ownership
   model cares now that a grant is an operator act about a league rather than evidence about a person. If
   it does not, write down that it does not, and where. Do not build machinery for a non-problem.

Scope guard — does NOT: the --emit RLS fix (moved out; its --load DROPs tables on the one production
database and is a scheduled event, not a punch-list line); the demo clone or the season selector (S2d);
any read scoping (done, S2b); RLS policy builds; the connect flow, jobs table or worker; any pipeline,
transform, loader or engine constant; the frozen corpus. No corpus slice is deleted.

Follow SESSION_GUIDE.md: fresh worktree, <=3 commits, update STATUS.md + ARCHITECTURE.md + appendices as
§7 requires (replace, don't append), then close/merge/push. This touches application/api/* AND
application/frontend/* — REDEPLOY and confirm live on https://surplusff.com/. Sweep .git for stale lock
files at closedown; that is now a recurring step on this repo.
```

## Definition of done

1. No request path imports `nfl_state`; `nfl_state_cache` is gone from the schema and the table list; the
   derived season is proven against a date table spanning the August boundary **in both directions**.
2. `check_ownership` asserts Sleeper agrees with the derived value, and fails loudly if not.
3. Five bad-code attempts against an address do **not** stop that address signing in with the right code —
   demonstrated — and the IP counter still bites.
4. `/health` reports season **2026** + source, and is still DB-free.
5. `verify()` asserts the FK carries `ON DELETE CASCADE`, and counts orphans.
6. `check_ownership --live` requires **401** specifically.
7. A rejected token produces a visible, accurate message — not a silent sign-out, not a spinner.
8. A tab refocus leaves league, week and drill-down untouched.
9. The `/api/me` docstring describes the system as it is.
10. The `email_confirm` decision is written down, wherever it was decided.
11. Merged, **redeployed**, confirmed live — and Will's sign-in round trip passes.

## Notes / gotchas

- **Item 1 deletes a fail-closed path, which normally would be alarming.** It is correct here: fail-closed
  existed to handle a third-party outage, and after this there is no third party in the path. Removing the
  failure beats handling it. Say so in the report rather than leaving a reviewer to wonder.
- **Item 2 touches the front door.** If it breaks, the symptom is nobody can sign in, and nothing announces
  it. Prove both halves — a refusal alone proves nothing.
- **Items are independent.** If one turns out to be bigger than it looks, land the others and say which one
  you stopped on. Nine small fixes bundled into one commit is how a green run stops meaning anything.

---

# AMENDMENT — 2026-08-11 — Code's four S2c questions, answered

**These are decisions, not suggestions.** Written the same turn they were made (CODING_BIBLE §7).

## 1. Where the season derivation lands — `settings.py`. Delete `nfl_state.py`.

After the change the value is **env-first with a computed default**, which is structurally identical to
`access_code()` and `demo_league_id()` — the idiom `settings.py` already exists to hold. A module named
after a third party that no longer touches that third party is a name that will mislead somebody.

- `settings.current_season(today=None)` — `CURRENT_SEASON` env first, else derive from `today` (defaulting
  to the system date). **The injectable `today` is required, not optional polish:** the DoD asks for a date
  table spanning the August boundary in both directions, and you cannot table-test a function that reads
  the clock itself.
- **The lazy import goes with it.** `settings.current_season` is imported lazily today only because
  `nfl_state` reaches Postgres and `settings` must stay DB-free at import. No DB, no reason.
- **Sleeper's fetch moves into `check_ownership.py`** — ~10 lines of stdlib `urllib`, used only by the
  agreement assertion. It is the last consumer.
- **Delete with the module:** `check_fails_closed` and the `nfl_state` monkeypatching at
  `check_ownership.py:157-178`, the `resolve`/`env_override` signature inspection at :249 (re-point it at
  `settings.current_season`), `nfl_state_cache` from `init_auth_schema._TABLES`, `main.py`'s
  `nfl_state.describe()` startup line (keep the log, move the function), `users.py`'s `_season_line`, and
  the pointer in `config.example.py:57`.

## 2. How far the live signup proof goes — all the way, **in this order**, because it can lock Will out

Both halves, against production. The order is not stylistic:

1. **Five bad codes** against `willdaniel.wrd+s2c-a@gmail.com` → all refused, no mail sent.
2. **Immediately, the correct code for the same address** → accepted, link sent. **This is the proof the
   lockout is gone**, and it doubles as the front-door check. **Will clicks the link and lands signed in
   before you go any further.**
3. **Only then, the IP half.** `_MAX_PER_IP = 15` per 60 minutes, so exhausting it **locks the originating
   IP out of signup for an hour** — and if you run this from Will's machine, that is *his* house, right
   when he is meant to be testing sign-in. Prove it last, and prove it bites on a *correct* code too (an
   IP-limited caller is limited regardless of what they know — that is the brute-force defense).
4. **Clean up.** Delete the test rows from `public.signup_attempts` at the end and say so in the report;
   it is a table this project owns and leaving a poisoned counter behind is not a result.

## 3. Item 9 — the answer is "no, and here is what would change it"

**The ownership model does not care.** An account confers nothing on its own: visibility requires a grant,
a grant is an operator act about a league, and signing up never creates one. So a confirmed account with
nobody behind it is **inert** — nobody can sign into it (that needs the mailbox), and if they could they
would see the demo, which is public anyway. `appendices/auth.md` already reasons this way; make it explicit
rather than implied.

**Write down the tripwire, not just the verdict** — a decision without its expiry condition is how a
resolved question comes back as a surprise:

> This stops being true the moment an account can claim a league **by itself**. If S4's connect flow ever
> grants ownership without an operator in the loop, "confirmed" starts to carry weight and the
> create-before-send ordering becomes a real defect. Revisit at S4.

Two places, no code: `appendices/auth.md`, and one line at the `email_confirm: true` site in `signup.py`
so the next reader of that line does not re-raise it. **Build nothing.**

## 4. Keep the `current_season is None` branch — and rewrite its reason

**Keep it.** Three reasons, in order:

1. **"Unreachable" is a claim about EVERY caller**, and this project has already paid for that inference
   once (`PM_SESSION_STARTUP.md`, "Where the PM was wrong"). `visible()` is pure, public, and has just
   acquired call sites; its contract is its signature, not today's callers.
2. **The failure mode of deleting it is not a clean error.** `int(season) == int(None)` raises TypeError
   *inside an authorization predicate* — a 500 on a read path, from a function whose whole job is to
   answer yes or no.
3. Two lines keep the predicate **total**, and the deny direction is the safe one.

**But the comment must change, and this is the actual work in this item.** It currently explains
fail-closed-during-a-Sleeper-outage — a scenario item 1 deletes. Leaving it is the same defect as
`/api/me`'s stale docstring in item 8, committed in the same session that fixes it. Replace the rationale
with the contract: *an unresolvable season denies the owned term; the predicate stays total and the deny
direction is the safe one.* No mention of Sleeper, caches or outages — none of them exist any more.
