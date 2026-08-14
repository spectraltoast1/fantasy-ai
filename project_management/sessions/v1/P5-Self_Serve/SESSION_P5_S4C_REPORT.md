# V1 · P5 · S4c — The connect flow: a user links their own league

**Shipped 2026-08-14.** **Brief:** `SESSION_P5_S4C_CONNECT_FLOW.md` ·
**Appendix extended:** `context/appendices/auth.md` ("Linking a league").
**3 commits. API redeployed (v28) AND worker redeployed — the first S4 session needing both.**
**The release valve was NOT taken:** both §5 carried items shipped.

> `api/routes.py:102` said ownership was *"written by an operator rather than inferred from a
> sign-in."* It is now inferred, and that line is deleted.

---

## What shipped

### 1 · The enqueue seam moved up, because it had to

`job_queue.enqueue`'s docstring said *"S4c's `POST /api/connect` … call this."* **It cannot.**
`application/.dockerignore` excludes a bare `data` and `application/Dockerfile` copies `api/` only,
so the API image contains **no `application/data/` at all** — which is also why
`api/requirements.txt` has no polars.

The producer half now lives in **`application/api/jobs.py`** and `job_queue` re-exports it. **One
INSERT, one NOTIFY**, and `check_connect` asserts that from the **AST** rather than by grepping —
`jobs.py`'s own docstring contains the words `INSERT INTO public.jobs`, so a text scan would have
been counting documentation. That is S4b's lesson applied before it could bite again.

**Neither venv can import both halves** (`api/.venv` has no polars, `venv` has no fastapi), which is
this session's constraint showing up in its own tooling. So `check_connect` asserts the worker's
shape from **source**, and the behavioural worker leg lives in `check_queue`, next to the `kind`
refusal it mirrors.

### 2 · Four routes, and what makes each one safe

| route | what it does |
|---|---|
| `GET /api/platforms/{platform}/leagues?handle=` | discovery, marked supported/unsupported **with a reason** |
| `POST /api/connect` `{platform, handle, league_id}` | enqueues. Builds nothing |
| `GET /api/connect` | the caller's in-flight job — **required**, see §3 |
| `GET /api/connect/{job_id}` | one job, **scoped to `requested_by`** |

**Discovery is not under `/connect/`.** `/api/connect/discover` would sit beside
`/api/connect/{job_id}` and depend on FastAPI's declaration order not to be shadowed — correct
today, one reordered function from being wrong. There is no ordering to get wrong now.

**The season is server-derived, never taken from the body.** It is the same
`settings.current_season()` that `reads.visible` applies to the owned term, so a job cannot be
enqueued for a season whose league the catalog would then refuse to show — a failure whose symptom
is a league that builds perfectly and is invisible to the person who asked for it.

**Rate limiting: two budgets, two natural sources, no duplicated record.** Connect counts
`public.jobs` itself — the job row **is** the thing being limited, so the counter cannot drift from
what it counts. Discovery counts a new `public.connect_attempts`, because a lookup starts no job and
leaves no other trace. Both keyed on the **authenticated user** (not IP or email — S1b's key was an
unauthenticated caller's, which is what forced all of its careful reasoning about aiming a limit at
somebody else). Both fail open. What discovery defends is **our egress IP**: throttling by Sleeper
stops onboarding for everyone, not just the abuser.

### 3 · The ownership row lands at `ready`, in the same transaction

The decision most likely to be got wrong, and it fails silently in **both** directions:

- **Early** — `visible` is `demo OR (owned AND season == current)`, `build_catalog` sorts owned
  first, and the SPA lands on `leagues[0]`. A row that exists mid-build drops the user onto their
  own league with **every panel empty**, for the whole build, with no error anywhere.
- **Separately** — a crash between the grant and the `ready` leaves a job that is terminal over a
  league nobody owns. Nothing retries a terminal job.

**Consequence, and it is a requirement:** the progress screen cannot be driven by the catalog. It is
driven by the job — hence `GET /api/connect`, because a job id in browser memory does not survive a
reload and a mid-build refresh must recover.

### 4 · Identity, split across two machines — and the brief was wrong about the cheap half

**Discovery on the API**, stdlib `urllib` (the `scripts/users.py` precedent — no dependency for
three GETs). Two calls per lookup plus one for the prior season, which is what makes the grey-out
non-vacuous in preseason rather than showing an empty list.

**Seat resolution on the worker.** The brief said `_roster_for_owner(rosters, owner_id)` costs no
extra call because "the worker fetches rosters anyway". **It does not retain them:** `fetch_teams`
reads `/rosters` transiently and persists only `teams_{season}.parquet`, and on a `resume` or
`reonboard` run the fetch stage is skipped entirely, so there is no rosters payload in memory at
all. The genuinely zero-call path is that parquet, which has carried `owner_id` since Session 3a.
So: parquet first (**0 calls**), then one `/rosters` GET for the **co-owner** case, which is the
only thing the parquet cannot answer.

### 5 · The scope marker is advisory, and says so

It greys out only what it can **positively rule out**, and every rule mirrors a real downstream
gate: not redraft (`assert_in_scope`, including its *absence is not redraft* rule), a reception tier
with no 2026 substrate, and not the current season. **Roster shape is deliberately not judged** —
1QB and superflex are both in scope, and greying out a league the worker would happily build is a
false refusal with no appeal.

The reception comparison uses a **tolerance, not equality**: Sleeper serves weights at float32, so
`rec in {1.0, 0.5}` greys out an ordinary half-PPR league. That is the Session-0.6 bug, and
`transforms/_scoring.py` carries the same constant for the same reason.

**Measured on real data, and it is the argument for not bulk-importing:** one handle returned **10
leagues, of which 1 qualified**. A blind "import everything" would have enqueued nine jobs whose
only possible outcome is a refusal — making the reject path the common path.

### 6 · Finding F, closed by construction

`resolve_viewer`'s `MY_USERNAME` fallback now JOINs `league_catalog` and requires `is_mine`. The
join is the fix: no input to that query reaches a linked league, however it is called. A Python `if`
would have been equivalent today and one refactor away from not being.

### 7 · The SPA — "Manage Leagues"

Permanent entry in the league switcher (not a first-run wizard: people link mid-season, and a second
league months later). Platform tab row driven by a data array. Dual-mode input on the store's own
18-19-digit snowflake rule. Unsupported leagues **greyed and labelled**, never hidden.

Progress is a **banner, not a modal** — `SessionLost`'s precedent, and for its stated reason: the app
underneath is working, on the demo, and a modal would claim otherwise. A `rejected` or `failed` job
ends the screen with **whatever words the refusal already carries**. Honest, not polished: S5 owns
the polished version, and the alternative is a spinner over a job that ended.

### 8 · The two §5 carried items — both shipped

**`users.py --delete`.** One GoTrue call; every app-side table cascades. Safe only because
`auth_schema.sql` declares `ON DELETE CASCADE` on all four and `init_auth_schema --verify` asserts
the constraint. Counts are printed before and **re-verified after**, because a cascade that silently
did not fire looks exactly like one that did.

**`init_auth_schema`: unknown ≠ pass.** An unreadable orphan count printed `??` and `continue`d
without setting `ok = False` — a green exit code over an assertion that produced nothing. It is a
third state now, reported separately, never counted as a success.

---

## Two bugs the live proof caught that no gate would have

**A · The lease's `RETURNING` never included the new columns.** The worker built the league
perfectly, landed `ready`, and **granted nobody anything** — `job.get("requested_by")` on a row that
never carried the column is `None`, and `grant_ownership` reads `None` as "hand-enqueued, nothing to
grant". No error in the table, in the logs, or on the screen: the user watches a league build and
then never appear. Found by a watcher polling `user_leagues` during the first end-to-end run.
`check_connect` now derives the required columns from **what the worker actually reads** (`job["…"]`
and `job.get("…")`, from the AST), so a future column is covered without anyone remembering.

**B · `check_queue --live` was reporting failures of a working queue.** The gate writes throwaway
rows into the same `public.jobs` the **live worker drains**. Measured: leased **0.12s** after the
INSERT (the NOTIFY, not the poll), run against a league id that is not Sleeper-shaped, 404, buried
as `failed` at **0.23s**. Two legs then found their row gone and reported a FAILURE — of a mechanism
that was working perfectly. **Pre-existing, not an S4c regression:** the deployed worker was S4b's
v5 image, three hours older than this session. Those legs are now **UNEVALUATED** — not a pass, and
not a failure — with the count printed before the verdict so a green line cannot be read as full
coverage. The detector was **proven to fire** rather than assumed: forced the race, and it caught it
on the second of its two tells (`leased_by` was already NULL by then, because `finish` clears it).

**The stronger fix is recorded and deferred:** run those legs on one connection inside a transaction
that is never committed, so the rows are never visible to any other session. That is a rewrite of a
working gate rather than a guard on it, and it belongs to a session that owns that file.

**One more, in my own instrument:** the finding-F ordering assertion first compared
`src.index("if viewer_roster_id")` against `src.index("_VIEWER_BY_USERNAME")` — and the **docstring**
names the constant, several lines above the code, so correct code failed. Prose that describes a
statement is not the statement. It walks the AST now.

---

## Proof

| gate | result |
|---|---|
| `check_connect` (new) | **30/30** offline · **34/34** with `--live` against **production** |
| `check_queue` | **16/16** offline (up from 14) · **23/23** `--live` |
| `check_onboard` | **23/23** |
| `check_store_boundary` | **32/32** |
| `check_auth` / `check_signup` / `check_ownership` / `check_isolation` | green offline, incl. every prove-it-bites block |
| `init_auth_schema --verify` | green; all four ALTERed `jobs` columns present on the existing table |
| `users.py --delete` | 4 rows across 4 tables removed by cascade, verified independently |

**The end-to-end run, in a browser, signed in as a real account, with no terminal:**
handle → pick → progress banner → **the app switched to Rex Lumber 2025 and the standings showed
"Ricky Wade · YOU"** — roster 1, resolved from the teams parquet with **zero** extra Sleeper calls.
No operator step and no `--grant` anywhere.

**DoD 2, measured rather than asserted.** A watcher polled `jobs` and `user_leagues` four times a
second through a second link (account B, handle `RandallDDM`):

```
t+ 17.70s  job='queued'    grants=[]
t+ 19.27s  job='building'  grants=[]
t+ 20.83s  job='loading'   grants=[]
t+ 24.04s  job='ready'     grants=[{league 1258181662160719872, roster_id 2}]
```

**Running states were observed** — `queued`, `building`, `loading` — so the proof is not the vacuous
kind that passes by seeing only the end state. The grant existed in none of them.

**The per-user seat, proven by two accounts on one league:** A sees Rex Lumber with
`viewer_roster_id: 1`, B with `viewer_roster_id: 2`, signed-out sees only the demo. That is Will's
designed case, not an edge case.

**Finding F:** across **all 33 catalog leagues** the new query changes **0** payloads (the old one
matched in exactly 2, both `is_mine`, both roster 8 — unchanged). And it **bites**: in the
non-`is_mine` league `1000568035473801216` the pre-S4c query highlights roster 1 for handle
`tgaw813` — a stranger's roster as "you" — and the new one returns nothing.

**Live, after the deploy (API v28):** signed-out prod returns **exactly** `DEMO-2025`, one league;
`/health` reports `season 2026, source derived`; all four new routes 401 anonymously; and a second
account's job vs a nonexistent id are **byte-identical** 404s over real HTTP.

**Nothing else moved.** Every public table was counted at session start and again at the end: of 19,
exactly **two** changed — `jobs` 5 → 8 (three real connect jobs) and `user_leagues` 1 → 3 (A's and
B's grants). All 14 served data tables, `league_catalog` (33) and `teams` (386) are **unmoved**,
which is also what proves the re-onboards were true no-ops rather than rebuilds.

**Residual state, left deliberately:** test accounts A and B still own Rex Lumber 2025 with seats 1
and 2 — they are the evidence for the per-user seat, and they are invisible on production anyway
(2025 league, 2026 season). `scripts/users.py --revoke` removes them when they have served their
purpose.

### What the live isolation gates say, honestly

`check_ownership --live` and `check_isolation --live` **fail against production, for reasons that
predate this session and are not defects.** Their fixture world is S2a/S2b's: `DEMO` is
`1182101676608823296`, which **S2d replaced** with `DEMO-2025`, and they expect accounts A and B to
own Trap 2025 and YPFL 2025 — grants that no longer exist. The session-start baseline recorded
`user_leagues` at **1 row** (Will's account → Rex Lumber, from S4a), so those expectations could not
have been met before S4c either, and `check_ownership.py` was last modified in **S4a**.

**Every one of the 55 live failures is in the "refused something the fixture expected to be
readable" direction. Zero are in the leaking direction.** Both files' offline matrices — including
every prove-it-bites block — are green. Refreshing those fixtures is S2d's debt and is left as one.

---

## Decisions recorded, so they are not "fixed" later as oversights

**No Sleeper ownership verification** (Will, 2026-08-14). We do not check that the caller holds a
seat in the league they name. Anyone with a `league_id` can already read that league's rosters,
owners and matchups from `api.sleeper.app` — the id is the secret and we are not the weak link — and
Sleeper offers no OAuth and no verification primitive. Combined with invite-gated signup, that is
the accepted risk.

**No roster uniqueness.** `user_leagues.roster_id` is a **per-user display property** inside a league
the caller can already read. Two people in one league both linking it is the designed case;
first-claim-wins would create a griefing vector (claim a seat, lock the real owner out of their own
highlight) that not enforcing it does not.

**Linking a league you hold no seat in is allowed**, and renders as no "you" highlight. The direct
league-id path has no handle at all, so this is a normal path rather than an edge case — which is
also what finding F's fix makes safe.

**The platform dimension without the second implementation.** `jobs.platform`, one platform-taking
discovery function, a `{platform, handle, league_id}` contract, a tab row that grows by addition, and
a worker that rejects an unimplemented platform the way it rejects an unknown `kind`. **Deliberately
NOT done:** `platform` on `user_leagues`, `league_catalog` or the 14 data tables, and namespaced
league ids. Both would be migrations across the loader, the corpus and every served payload, needed
by nothing today. → `projects/post-v1/other-platforms.md`.

**The S2c tripwire fired, and the answer is "still not a defect".** S2c said the create-confirmed-
before-send ordering becomes a real defect "the moment an account can claim a league by itself". It
now can. But claiming needs a **token**, a token needs the magic link, and the link goes to the
address — so an orphan confirmed account still holds no grants and reads what a visitor reads. What
*did* change is the **value of an account**: a token now buys the ability to enqueue work onto a
single-machine worker and grant yourself a league, which strengthens the case for rotating the access
code if it spreads. → *appendix: auth*.

---

## Findings for later

- **A supported 2026 league already exists on Sleeper** and discovery marks it linkable. What is
  still untested is the combination **Gate A owns**: a *cold* 2026 league with **0 completed weeks**,
  whose join / spine / schedule stages have never run against an empty season. S4c deliberately did
  not go there — discovering it is broken inside this session would have consumed it.
- **The catalog hop is the one thing no live proof covers**, unchanged from S4a: production derives
  2026, and a linked 2025 league is correctly invisible to its own owner. It was proven against a
  local process at `CURRENT_SEASON=2025` on production Postgres with the **real Fly worker** doing
  the build, and `/health` reports `season_source: env` throughout so it cannot be mistaken for
  production. **The command is in `OPERATIONS.md`, not in `.claude/launch.json`** — `.claude/` is
  gitignored, so a launch config does not survive the worktree it was written in.
- **An account can be created unconfirmed and then be permanently unable to sign in** while platform
  signup is off — GoTrue reads the magic-link redemption as a signup and refuses it (`otp_expired`).
  Hit on test account B during this session and fixed with an admin `email_confirm`. `signup.py`
  creates accounts confirmed, so its accounts are fine; this is about accounts created by any other
  route.
- **`check_ownership`/`check_isolation`'s live fixtures are stale since S2d** — see above.

## Deliberately not done

The Manager Dossier executor and the `panels_manager` flip (**S4e**) · S5's authoritative preflight
and rejection copy · the weekly cadence, `weekly_refresh.yml`, `MY_USERNAME`/`LEAGUE_ID` (**S4d**) ·
the "leagues you already have" list in the Manage Leagues shell (built so it can sit above "Link a
League", not built) · GA events for the connect funnel · `--emit`/`--load` against production.
