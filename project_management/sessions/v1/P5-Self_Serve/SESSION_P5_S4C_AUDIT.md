# P5 · S4c — PM audit of the connect flow

**Audited:** 2026-08-14 · **Report:** `SESSION_P5_S4C_REPORT.md` · **Brief:**
`SESSION_P5_S4C_CONNECT_FLOW.md` · **Range:** `70a4022..191c62b` (3 commits + merge), diffed against
the **branch's base commit**.
**Verdict: ENDORSED, and S4c is CLOSEABLE.** All DoD clauses met, the release valve not taken, both
§5 carried items shipped, and **the API deploy independently verified from outside** — the first
session in this series where that was possible.
**One finding: the connect button can reach an untested path in production today.** Not a security or
data-loss issue, and it has a free fix.

---

## THE FINDING — the scope marker does not check whether the league has drafted

`platforms.classify` rules out exactly three things: **not the current season**, **not redraft**, and
**an unsupported reception tier**. It does not ask whether the league has *started*.

**So a `pre_draft` league is marked linkable, and the button is live in production now.** The report
names the gap accurately — *"a cold 2026 league with 0 completed weeks, whose join / spine / schedule
stages have never run against an empty season"* — and its reason for not going there in-session is
sound (*"discovering it is broken inside this session would have consumed it"*).

**But it is filed as a future risk, and it is a reachable path.** That is the difference between this
session and the last two: S4a and S4b could defer 2026 because **nothing could reach it**. S4c shipped
the thing that reaches it.

**Concretely, and it is not hypothetical.** I checked Will's Sleeper account directly on 2026-08-14:
`League of Random People 2.0` (`1389327290164314112`) is redraft, 10-team, full PPR, 2026 — it passes
all three of `classify`'s rules — and its status is **`pre_draft`**. It is *the* league Will links at
Gate A, and clicking it the first time he sees the button is the most natural thing in the world.
The likely outcome is a league that builds over an empty season and lands `state='ready'` — which is
the risk register's named failure (*"never a half-built league that looks complete"*) as the connect
flow's first impression.

**The fix is free, and it uses a field already in the same response.** Sleeper's league objects carry
`status` alongside `settings` and `scoring_settings` — I confirmed this on the same call that returned
the scoring data for all seven of Will's leagues (`pre_draft`, `drafting`, `in_season` all observed).
So `classify` gains a fourth rule at zero API cost: **`pre_draft` / `drafting` → not yet linkable,
"your draft hasn't happened yet — link it afterwards."**

**Be precise about where the line sits, because the obvious version is wrong.** Do **not** grey out on
"0 completed weeks" — before Week 1 *every* 2026 league has zero, and a **drafted** preseason league is
the *designed* path: rosters plus projections, actuals zero-filled, surfaced through P2/S4a's honest
thin-data window. The broken case is a league with **no rosters at all**, and `status` is exactly the
discriminator for that.

It also mirrors a real downstream reality rather than inventing policy, which is the standard
`classify`'s own docstring sets for itself.

**Owner: S4d, or a one-line fix now.** It is smaller than the session that carries it.

---

## Verified independently — recomputed, not read

| claim | verified |
|---|---|
| **the API was really redeployed** | ✅ **`GET /api/platforms/sleeper/leagues` on live `surplusff.com` returns 401, not 404.** The route exists on the deployed image — a 404 would have meant a merge that never shipped. **This is the S2e lesson closed**, and the first S4 session where an outside observer could check the deploy at all |
| signed-out prod is **exactly the demo** | ✅ one league, `DEMO-2025` — *with two real accounts now owning Rex Lumber*. The leak direction is closed after the grant path went live |
| no env override leaked to production | ✅ `/health` → `season 2026, source **derived**`. Load-bearing this session: the catalog-hop proof ran a local process at `CURRENT_SEASON=2025`, and `season_source` is what proves it stayed local |
| finding F fixed **structurally** | ✅ `_VIEWER_BY_USERNAME` JOINs `league_catalog` and requires `c.is_mine`. A Python `if` would have been equivalent today and one refactor from not being — the report says so and the SQL backs it |
| one INSERT, one NOTIFY, asserted from the **AST** | ✅ and the file proves the point on itself: `INSERT INTO public.jobs` appears **twice** in `jobs.py`, one of them the docstring. A grep would have counted documentation |
| `check_ownership` last touched in **S4a** | ✅ `2dbe01d`. So its live fixtures could not have matched production before this session either |
| the live fixtures are genuinely stale | ✅ both gates hardcode `DEMO = "1182101676608823296"` — the id **S2d replaced** with `DEMO-2025` |
| the new routes are gated **offline**, not just live | ✅ and this is the part I'd have missed: `check_isolation` gained a separate `_AUTHENTICATED` list beside `_EXEMPT`, asserting each new route depends on `auth.current_user` (401s) rather than `auth.optional_user` (serves anonymous the demo) — **with a complement check so adding a route to `_EXEMPT` without classifying it fails** |

**On the 55 live isolation failures — I could not run them, and here is what I could do.** Structurally
the claim holds: with `DEMO` pointing at a 2025 league that is no longer in the public catalog, and
A/B holding none of the fixture grants, every assertion resolves to *refused-what-was-expected-
readable*; a leaking failure would require a 404-expectation returning 200, which this configuration
cannot produce. Empirically, **the actual leak direction is the thing I checked myself and it is
closed.** I accept the claim.

**Not verifiable from the PM seat:** the per-table Postgres counts, the 4×/second watcher trace, and
the worker-side behaviour. Unchanged from every prior session.

## What this session did unusually well

**Two bugs that only a live run could find, and the fix for the first is structural.** The lease's
`RETURNING` never included the new columns, so the worker built the league, landed `ready`, and
**granted nobody anything** — no error in the table, the logs, or the screen. That is this project's
signature failure (*silent success*) in a new costume. The gate now derives the required columns from
**what `worker_loop` actually reads**, via the AST, so the next column is covered without anyone
remembering. That is a fix to the class, not the instance.

**It refused to let a broken instrument report a failure as a finding.** `check_queue --live` was
reporting failures of a working queue — the gate writes throwaway rows into the same `public.jobs` the
live worker drains, and the worker took them **0.12s** after the INSERT. Those legs are now
**UNEVALUATED — not a pass and not a failure** — with the count printed before the verdict so a green
line cannot be read as full coverage. **And the detector was proven to fire rather than assumed**, by
forcing the race. The stronger fix (an uncommitted transaction) is recorded and deferred to a session
that owns the file, which is the right call.

**It caught the prose-vs-statement trap in its own instrument again** — the finding-F ordering
assertion matched the *docstring* naming the constant rather than the code. **That is the sixth and
seventh time** this class has been caught inside the session that could have shipped it. It is now
being caught reflexively rather than discovered.

**The measurement is the right kind.** DoD 2 was proven by a watcher polling four times a second that
**observed the running states** — `queued`, `building`, `loading`, all with `grants=[]` — rather than
by seeing only the end state. The report says so explicitly: *"not the vacuous kind of proof."*

**The bulk-import argument got a number.** One handle returned **10 leagues, of which 1 qualified.**
That is the strongest possible form of the deviation I asked for — a blind "import everything" would
have enqueued nine jobs whose only outcome is a refusal.

**Discovery was deliberately not put under `/connect/`**, because `/api/connect/discover` would sit
beside `/api/connect/{job_id}` and depend on FastAPI's declaration order not to shadow it — *"correct
today, one reordered function from being wrong."* Nobody asked for that.

## My errors in the brief, for the record

1. **`_roster_for_owner` does not come free.** I said the worker fetches rosters anyway; it does not
   *retain* them — `fetch_teams` reads `/rosters` transiently and persists only the teams parquet, and
   on a `resume`/`reonboard` the fetch stage is skipped entirely. Code found the genuinely zero-call
   path (that parquet, which has carried `owner_id` since Session 3a) and used one `/rosters` GET only
   for the co-owner case the parquet cannot answer.
2. **I proposed a modal for progress; a banner is better** — `SessionLost`'s precedent, for its stated
   reason: the app underneath is working, on the demo, and a modal would claim otherwise. I flagged
   that comment as worth reading and Code read it.

## Carried forward — none of it reopens S4c

- **The pre-draft gap above** → S4d, or fix it now.
- **`check_ownership` / `check_isolation` live fixtures, stale since S2d.** Code left this as S2d's
  debt. **It needs an owner, and I would give it to S4d:** two gates that fail against production are
  gates nobody runs against production, which is the inverse of the reason S2b made them injectable
  in the first place. S4d enumerates connected leagues from the ownership table, so it has cause.
- **An account created unconfirmed can be permanently unable to sign in** (GoTrue reads the magic-link
  redemption as a signup and refuses it while platform signup is off). Hit on test account B. Not
  reachable through `signup.py`, which creates confirmed — but it is a real trap for any other route.
- **The S2c tripwire fired and the answer is still "not a defect"**, with the right nuance: an orphan
  confirmed account still holds no grants, but **the value of an account has changed** — a token now
  buys the ability to enqueue work onto a single-machine worker. That strengthens the case for
  rotating the access code if it spreads. Worth Will's attention before the cohort grows.
- **Test accounts A and B still own Rex Lumber** with seats 1 and 2, invisible on production. They are
  the per-user-seat evidence; `--revoke` when done.

## Verdict

**Endorsed. S4c closes.** `api/routes.py:102` said ownership was *"written by an operator rather than
inferred from a sign-in."* It is now inferred, that line is deleted, and a real account linked a real
league in a browser with no terminal and no `--grant`. The two-account seat proof — A at roster 1, B at
roster 2, signed-out seeing only the demo — is the designed multi-viewer case demonstrated rather than
argued.

**Fix the pre-draft rule before Will links LoRP 2026**, because that is the first thing he will do and
it is currently the untested path.
