# V1 · P5 · Session S4c — The connect flow: a user asks for their own league

**Written 2026-08-14.** **Status: READY — paste-block below.**
**Prior:** `SESSION_P5_S4B_REPORT.md` + `SESSION_P5_S4B_AUDIT.md` (the queue this fills) ·
`SESSION_P5_S4A_REPORT.md` (finding F, carried here) · `context/appendices/auth.md` ·
`store-boundary.md`.
**Goal: the ownership row stops being something Will types.**

> **What this session does:** puts a front door on S4b's queue. `api/routes.py:102` says ownership is
> *"written by an operator rather than inferred from a sign-in"* — after this, it is inferred.

---

## THE CONSTRAINT THAT SHAPES THE WHOLE SESSION — the API cannot import the queue

**`job_queue.enqueue`'s docstring says *"S4c's `POST /api/connect` … call this."* It cannot.**
Verified two ways: `application/.dockerignore` excludes a bare **`data`**, and
`application/Dockerfile:56` copies **`api/` only**. The API image contains **no
`application/data/`** at all — which is also why `api/requirements.txt` has no polars, and why
`data/fetchers/sleeper.py` (which imports both polars and `data_layer`) is unreachable from a route.

**This is the same wall S4b hit from the other side**, and it has a clean answer with precedent:
**move the enqueue seam UP into `application/api/`, and have `job_queue` re-export it.** The
dependency direction is already established — `job_queue` imports `application.api.db` today — and the
shape is exactly S4a's, where `canonical_rows` moved down into `data_layer` and `check_scoped_reload`
kept a one-line re-export. **One implementation, reachable from both images.** Do not write a second
INSERT: two enqueue paths that drift is how a job gets inserted without its `NOTIFY` and sits until the
safety-net poll.

## 1 · Identity acquisition — split it, because the two halves live on different machines

`api/routes.py:102` is the line this session deletes. Two distinct Sleeper interactions, and
conflating them is what forces a bad architecture:

- **Discovery — interactive, on the API.** Sleeper username → `user_id` → their leagues for the
  current season, so the user *picks* rather than pasting an 18-digit id. This must be a request-time
  call. Use **stdlib `urllib`** — the precedent is `scripts/users.py`, which talks to Supabase that way
  precisely so it needs no dependency. Do **not** add an HTTP client to `api/requirements.txt` for two
  calls.
- **Seat resolution — on the worker, from data it already has.** `sleeper._roster_for_owner(rosters,
  owner_id)` already exists and the worker fetches rosters anyway. **No extra Sleeper call, and no
  guessing.**

**Carry the user's Sleeper `user_id` on the job** so the worker can resolve the seat without
re-discovering it.

### The ownership row is written when the job reaches `ready` — NOT at enqueue

**This is the decision most likely to be got wrong, and it fails silently.** `reads.visible` is
`demo OR (owned AND season == current)` and `build_catalog` sorts **owned first**
(`reads.py:1303`) — the SPA lands on `leagues[0]`. So an ownership row written at enqueue makes the
user land on **their own league with every panel empty**, for the ~10s the build takes, with no
error anywhere. That is the worst possible first impression and nothing would report it.

**Consequence, and it is a requirement not a detail: the progress screen cannot be driven by the
catalog.** It is driven by the job. Which means a signed-in user who refreshes mid-build must be able
to find their job again — so there is a caller-scoped way to ask *"do I have a job in flight?"*, not
just `GET /api/connect/{id}` with an id held in browser memory.

## 2 · The endpoints

- **`POST /api/connect`** — authenticated, enqueues, returns the job id. **It does not build
  anything** and must not block on Sleeper beyond the discovery call.
- **`GET /api/connect/{id}`** — the job's state for its owner. **Scope it to `requested_by`, and
  refuse exactly as the rest of the app does:** a job that is not yours returns the **same 404** as one
  that does not exist. The uuid PK makes enumeration impractical; that is not a reason to skip the
  check. S2b's principle applies to every object, not just leagues.
- **Rate limiting.** Reuse `rate_limit`'s **Postgres-backed** shape — S1b's lesson is that an
  in-process limiter is defeatable by waiting out `min_machines_running = 0`. But **the key and the
  budget are different**: the caller is authenticated, so key on the **user**, and what is being
  protected is Sleeper calls and worker minutes, not an email send budget. **Say what you chose and
  against what.**

## 3 · The reject path has to reach a human — without writing S5

A user who submits a dynasty league today gets a `rejected` job carrying a raw `SystemExit` string.
**S5 owns the graceful preflight and the copy; do not build it.** But S4c must not leave the user
staring at a spinner that never resolves — the job ended, and the screen must say so and say why, in
whatever words the error already carries. **Honest, not polished.** That is the same standing rule the
empty panels follow.

## 4 · S4a finding F — the null seat, now that it matters

`reads.resolve_viewer` falls back to matching `MY_USERNAME` against `teams.owner_name` **in any
league**. On a connected league that is wrong in both directions: it highlights nothing (measured: 0
of 211), or — if Will's handle happens to be an `owner_name` in someone's league — it silently
highlights **a stranger's roster as "you"**, and nothing checks the roster belongs to the caller.

**It is a display-integrity defect inside a league the caller may already read — NOT a cross-user
leak. Do not over-scope it.** With the seat now written from `_roster_for_owner`, state the predicate:
**a connected league must never resolve its seat by username fallback.** Then make the fallback
unreachable for connected leagues rather than patching the symptom.

## 5 · Two carried items — the release valve if the cap bites

- **`scripts/users.py --delete`** — account lifecycle. `--grant`/`--revoke`/`--ban`/`--unban` exist;
  deletion does not, and self-serve signup is what created the need.
- **`init_auth_schema.py:117-121`** swallows an orphan-count failure and `continue`s **without setting
  `ok = False`** — a green exit code over an assertion that produced nothing. **The fix is a third
  state (unknown ≠ pass), not a louder failure:** an unavailable count genuinely is not a failure, it
  just must not be counted as a success. It lands here because `--delete` is exactly what the cascade
  and that orphan count exist to protect.

## What this session does NOT do — and one scope call I am making

**The Manager Dossier executor and the `panels_manager` flip move OUT of S4c** (they were listed in the
roadmap's S4c row). **Reversible if you disagree, and here is the reasoning:** S0 designed connect as
**staged** — the four fast surfaces on a spinner, manager profiling as a *separate deferred job class* —
because the fan-out is **80s / 248 Sleeper calls**. So a connected league showing `panels_manager:
false` is **the designed behaviour, not a gap**, and the honest empty state already exists. It is a
feature on a Week-1-critical path that does not need it. → **S4e, after S4d.**

Also NOT: S5's preflight or rejection copy · the weekly cadence (**S4d**) · `--emit`/`--load` against
production · engine constants, any transform's maths, the corpus, the frozen corpus manifest, or
`demo_manifest.parquet`'s 31 rows.

**`reload_manifest()` is currently refused on BOTH machines** (S4b audit) — the worker by the
`STORE_ROLE` guard, the laptop by `assert_catalog_covers_postgres`. **Use `upsert_catalog_row(conn,
lid)` for any per-league catalog write.** Do not "fix" `reload_manifest` here.

**Named release valve:** if the 3-commit cap bites, defer **§5's two carried items** and say so. The
endpoints, identity acquisition and the progress screen are the session.

---

## The brief to paste to Code — S4c

```
Goal: V1 Project 5, Session S4c (projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md) — put a front door
on S4b's queue: POST /api/connect, GET /api/connect/{id}, identity acquisition, and a progress screen.
api/routes.py:102 says ownership is "written by an operator rather than inferred from a sign-in".
After this session it is inferred.

Read first: sessions/v1/P5-Self_Serve/SESSION_P5_S4C_CONNECT_FLOW.md (this brief),
SESSION_P5_S4B_REPORT.md + SESSION_P5_S4B_AUDIT.md, SESSION_P5_S4A_REPORT.md (finding F),
context/appendices/auth.md, context/CODING_BIBLE.md, SESSION_GUIDE.md. CHECK THIS BRIEF AGAINST
OBSERVABLE REALITY BEFORE EXECUTING — it has been wrong in every session so far and you have caught it
every time.

0. THE CONSTRAINT THAT SHAPES EVERYTHING — THE API CANNOT IMPORT THE QUEUE.
   job_queue.enqueue's docstring says "S4c's POST /api/connect ... call this." IT CANNOT. Verified two
   ways: application/.dockerignore excludes a bare `data`, and application/Dockerfile:56 copies `api/`
   ONLY. The API image contains NO application/data/ — which is also why api/requirements.txt has no
   polars and why data/fetchers/sleeper.py (imports polars AND data_layer) is unreachable from a route.
   ANSWER: move the enqueue seam UP into application/api/ and have job_queue RE-EXPORT it. The
   dependency direction is already established (job_queue imports application.api.db), and the shape is
   S4a's canonical_rows move with its one-line re-export. ONE implementation, reachable from both
   images. Do NOT write a second INSERT: two enqueue paths that drift is how a job gets inserted
   without its NOTIFY and sits until the safety-net poll.

1. IDENTITY ACQUISITION — SPLIT IT, the halves live on different machines.
   DISCOVERY (interactive, on the API): Sleeper username -> user_id -> their leagues for the current
   season, so the user PICKS rather than pasting an 18-digit id. Use stdlib urllib — the precedent is
   scripts/users.py, which talks to Supabase that way precisely so it needs no dependency. Do NOT add
   an HTTP client to api/requirements.txt for two calls.
   SEAT RESOLUTION (on the worker, from data it already has): sleeper._roster_for_owner(rosters,
   owner_id) already exists and the worker fetches rosters anyway. No extra Sleeper call, no guessing.
   Carry the user's Sleeper user_id on the job so the worker can resolve the seat without
   re-discovering it.

   THE OWNERSHIP ROW IS WRITTEN WHEN THE JOB REACHES `ready`, NOT AT ENQUEUE. This fails SILENTLY if
   you get it wrong: reads.visible is `demo OR (owned AND season == current)` and build_catalog sorts
   OWNED FIRST (reads.py:1303) — the SPA lands on leagues[0]. An ownership row at enqueue makes the
   user land on THEIR OWN LEAGUE WITH EVERY PANEL EMPTY for the ~10s the build takes, with no error
   anywhere.
   CONSEQUENCE, a requirement not a detail: the progress screen CANNOT be driven by the catalog. It is
   driven by the job — so a signed-in user who refreshes mid-build must be able to find their job
   again. There must be a caller-scoped way to ask "do I have a job in flight?", not just
   GET /api/connect/{id} with an id held in browser memory.

2. THE ENDPOINTS.
   POST /api/connect — authenticated, enqueues, returns the job id. It does NOT build anything and must
   not block on Sleeper beyond the discovery call.
   GET /api/connect/{id} — the job's state FOR ITS OWNER. Scope it to requested_by, and refuse the way
   the rest of the app does: a job that is not yours returns the SAME 404 as one that does not exist.
   The uuid PK makes enumeration impractical; that is not a reason to skip the check. S2b's principle
   applies to every object, not just leagues.
   RATE LIMITING: reuse rate_limit's POSTGRES-BACKED shape (S1b: an in-process limiter is defeatable by
   waiting out min_machines_running = 0). But the key and the budget are DIFFERENT — the caller is
   authenticated, so key on the USER, and what is protected is Sleeper calls and worker minutes, not an
   email send budget. Say what you chose and against what.

3. THE REJECT PATH MUST REACH A HUMAN — WITHOUT WRITING S5.
   A user who submits a dynasty league today gets a `rejected` job carrying a raw SystemExit string. S5
   owns the graceful preflight and the copy — DO NOT BUILD IT. But do not leave the user on a spinner
   that never resolves: the job ended, and the screen must say so and say why, in whatever words the
   error already carries. Honest, not polished — the same rule the empty panels follow.

4. S4a FINDING F — THE NULL SEAT, now that it matters.
   reads.resolve_viewer falls back to matching MY_USERNAME against teams.owner_name IN ANY LEAGUE. On a
   connected league that is wrong both ways: it highlights nothing (measured 0 of 211), or — if Will's
   handle IS an owner_name in someone's league — it silently highlights A STRANGER'S ROSTER AS "you",
   and nothing checks the roster belongs to the caller.
   IT IS A DISPLAY-INTEGRITY DEFECT INSIDE A LEAGUE THE CALLER MAY ALREADY READ — NOT A CROSS-USER
   LEAK. Do not over-scope it. With the seat now written from _roster_for_owner, state the predicate: a
   connected league must NEVER resolve its seat by username fallback. Make the fallback unreachable for
   connected leagues rather than patching the symptom.

5. TWO CARRIED ITEMS (and these are the release valve).
   scripts/users.py --delete — account lifecycle; --grant/--revoke/--ban/--unban exist, deletion does
   not, and self-serve signup created the need.
   init_auth_schema.py:117-121 swallows an orphan-count failure and `continue`s WITHOUT setting
   ok = False — a green exit code over an assertion that produced nothing. THE FIX IS A THIRD STATE
   (unknown != pass), not a louder failure: an unavailable count is genuinely not a failure, it just
   must not be counted as a success.

PROVE IT.
 (1) A REAL SIGNED-IN ACCOUNT connects a league end to end through the UI: username -> pick -> progress
     -> the league appears and is theirs. No operator step, no scripts/users.py --grant anywhere.
 (2) The ownership row does NOT exist before `ready`, shown — and the catalog does not offer a
     half-built league at any point during the build.
 (3) A second account cannot read the first's job: GET /api/connect/{id} returns the SAME 404 as a
     nonexistent id, byte-identical.
 (4) A refresh mid-build recovers the progress screen.
 (5) A rejected job (unknown kind, or an out-of-scope league) ends the screen with a reason rather than
     an infinite spinner.
 (6) Nothing else moved: signed-out live prod still returns EXACTLY the demo; check_ownership and
     check_isolation still green, with counts.
 VERIFY THE INSTRUMENT: this project's signature failure is a proof that passes by doing nothing —
 caught FIVE times now (_db_max_as_of, the parity run's skips, check_onboard's first prove-bites, pkill
 missing on python:3.13-slim so the kill drill killed nothing, and two assertions matching PROSE
 describing a statement rather than the call). Show the work happened.

Scope guard — does NOT: build the Manager Dossier executor or flip panels_manager (moved OUT of S4c to
S4e — S0 designed connect as STAGED, four fast surfaces on a spinner with manager profiling as a
separate deferred job class at 80s / 248 Sleeper calls, so panels_manager: false is the DESIGNED
behaviour and the honest empty state already exists); write S5's preflight or rejection copy; build the
weekly cadence or touch weekly_refresh.yml, MY_USERNAME or LEAGUE_ID (S4d); run --emit or --load against
production; touch engine constants, any transform's maths, the corpus, the frozen corpus manifest, or
demo_manifest.parquet's 31 rows.
NOTE: reload_manifest() is currently refused on BOTH machines (S4b audit) — the worker by the
STORE_ROLE guard, the laptop by assert_catalog_covers_postgres. Use upsert_catalog_row(conn, lid) for
any per-league catalog write. Do NOT "fix" reload_manifest here.

Release valve if the 3-commit cap bites: defer the two §5 carried items and SAY SO. The endpoints,
identity acquisition and the progress screen are the session.

Suggested commit map (3): (1) the enqueue seam into api/ + POST/GET /api/connect + authorization +
rate limit; (2) identity acquisition (discovery on the API, seat on the worker, ownership row at
`ready`) + the finding-F fix; (3) the progress screen + the two carried items + docs.

Follow SESSION_GUIDE.md: fresh worktree, <=3 commits, update STATUS.md + ARCHITECTURE.md per §7
(REPLACE, don't append) and appendices/auth.md (this session changes how ownership is acquired, which
that appendix documents). THIS SESSION CHANGES SERVED CODE, so unlike S4a/S4b the API must be
REDEPLOYED — "merged" is not "deployed", and S2e shipped a merge that ran the previous release in
production for hours. Verify against the LIVE host, and remember an appended cache-buster does not
bust WebFetch's cache — reorder the params or fetch the second hostname. Sweep .git for stale locks at
closedown AND AGAIN AFTER COMMITTING.
```

## Will's checks after

1. **Connect a league from a browser, signed in as yourself, without touching a terminal.** That is
   the whole session; anything less is a facade.
2. **Watch the catalog during the build.** If your half-built league appears in the switcher before it
   is ready, the ownership row went in too early — the one failure here with no error attached.
3. **Sign out and reload.** Still exactly the demo.
4. **This one needs a real API deploy** — the first of the S4 series that does. `fly status -a
   fantasy-ai-api` and check the release, not just the merge.
