# V1 · P5 · Session S4d — The weekly cadence, and the two defects Will's live test found

**Written 2026-08-15.** **Status: READY — paste-block below.** **Supersedes the 2026-08-14 draft**,
which was written before the live test.
**Prior:** `SESSION_P5_S4C_REPORT.md` + `SESSION_P5_S4C_AUDIT.md` · `SESSION_P5_S4B_REPORT.md` ·
`context/appendices/store-boundary.md`.
**Goal: the app stops being frozen in-season — and a league can be linked at Week 1 at all.**

> **Week-1 critical.** NFL Week 1 is **Thu 10 Sept 2026**. Two of the three things in this brief are
> on the path between a cohort member clicking Link and seeing their league.

---

## What Will's live test found, because it reframes this session

Will linked his real 2026 league from production and got:

```
Something went wrong linking that league.
FileNotFoundError: ... /snapshots/nfl_sleeper_weekly_joined/league/1389327290164314112/season_2026.parquet
```

**The blocker is not the draft. It is completed weeks.** `_pull_raw` fetches matchups via
`sleeper.backfill`, which writes only **completed** regular-season weeks;
`_determine_completed_weeks` returns **0** while `season_type == "pre"` and `leg - 1` during the
regular season. No matchups files → no join file → `compute_spine._compute_league` calls
`compute_production_vor` with **no guard on that file existing**.

Three consequences, and the second is the launch-relevant one:

1. **A drafted league fails identically today.** The pre-draft rule is real but treats a symptom.
2. **`completed = leg - 1` means the first completed week lands about a week AFTER Week 1.** `leg` is
   1 *during* Week 1 (Thu 10 Sept), so completed is still 0; the first arrives ~**17 Sept**. **As the
   code stands, a cohort member linking at launch hits this same error.**
3. **From now to 10 Sept no 2026 league can produce anything**, which is why holding a league as
   *pending* is **S4f** and not a nice-to-have. **S4d does not build that** — it makes the window
   smaller and the failure honest.

## 1 · The current-week fetch — the launch-path fix

**`sleeper.refresh()` already fetches the current week's matchups regardless of completion**
(`sleeper.py:718`). That is the projections-only path the architecture describes: the join zero-fills
actuals, nothing is fabricated, and P2/S4a's thin-data window honestly reports 0 weeks of results.
**The cold onboard chain simply does not use it** — it uses `backfill`, which waits for completion.

- **Teach the onboard fetch to pull the current in-progress week when there is one.** That is what
  makes linking work **at** Week 1 rather than a week later.
- **It does nothing before 10 Sept, and that is correct** — `leg` is 0 in the preseason, so there is
  no current week to fetch. Say so rather than implying this fixes August.
- **Do NOT assume the join is the only blocker.** `production_vor`, `true_rank`, `positional_depth`,
  `bracket_odds` (a Monte Carlo) and `player_signal` have **never run on a league with zero realized
  results**. **Determine what each does**, and if one of them cannot honestly produce a read on a
  zero-results league, say so — that is a finding about the thin-data window, not a bug to paper over.
- **A subtlety worth stating in the code:** the onboard's current-week snapshot is a **point in time**.
  On a re-run `_raw_present` is true and `_missing_raw_weeks` (bounded by *completed* weeks) reports
  nothing missing, so the stale in-progress week is not re-pulled. **That is the weekly cadence's job**
  — which is the other half of this session. Make the division of labour explicit.

## 2 · The error the user actually sees

The raw `FileNotFoundError`, **including an internal filesystem path**, was rendered straight into the
UI. S4c's rule — *"end the screen with whatever words the refusal already carries"* — is right for an
**authored `SystemExit`** and wrong for an **unhandled exception**. Today any crash anywhere in the
chain becomes user-facing text with our paths in it.

**The distinction to build on is the one the codebase already makes:** `SystemExit` is how
`onboard_league` signals a *deliberate, human-readable refusal*; anything else is a crash. The first
belongs on the screen. The second belongs in the job row and the logs, with something honest and
non-leaking on the screen. **`rejected` vs `failed` already encodes exactly this distinction** — use
it rather than inventing a second one.

**Also fix the retry semantics while you are here:** a deterministic refusal that retrying cannot
change should be `rejected` (terminal), not `failed` (retried to the cap). A league with no completed
weeks cannot succeed on attempt 2 or 3.

## 3 · Pre-draft: refuse for now, and build the DETECTION so S4f can reuse it

`platforms.classify` rules out non-current-season, non-redraft and an unsupported reception tier —
never whether the league has started. Sleeper's league objects carry **`status`** in the same
discovery response (verified 2026-08-14 across all seven of Will's leagues: `pre_draft`, `drafting`,
`in_season` all observed), so this is one more rule at zero API cost.

**Build it knowing S4f replaces the response, not the detection.** S4f holds a not-yet-ready league as
*pending*; S4d refuses it. **Same predicate, different branch** — so put the predicate somewhere S4f
can change the branch without re-deriving it. It is not throwaway work, and it should not be written
as though it is permanent either.

**Do NOT grey on "0 completed weeks"** — that is now true of *every* 2026 league until ~17 Sept and
would refuse the entire cohort. `status` is the discriminator for "no rosters exist"; completed weeks
is a different question that §1 handles.

## 4 · The cadence — the workflow should stop being a pipeline machine

S4b's `kind` column exists for this: `worker_loop._EXECUTORS` is `{"onboard": …}` and its own comment
says *"`kind` exists because S4d enqueues the weekly refresh."* Add `"refresh"`.

**The executor is `weekly_refresh.refresh_league(lid, season, live=True)`**, which already works on a
worker (S3 built its band-verify branch for this, `weekly_refresh.py:219`). And
`lid = lid or league_resolver.resolve_league_id(season)` means **a job carrying its own `league_id`
never touches the resolver** — which *retires* `MY_USERNAME`/`LEAGUE_ID` rather than relocating them.

**If the workflow only has to INSERT rows, it needs no Python, no pipeline and no checkout.**
Enumeration is a query — current-season leagues somebody owns, i.e. `user_leagues ⋈ league_catalog` —
and the whole job could be one `INSERT … SELECT` over the `DATABASE_URL` it already holds.
**Determine whether that is right rather than taking it from me**, and note two consequences if it is:

- **`weekly_refresh.yml` stops being a machine that can write the store**, so `STORE_ROLE=worker` goes
  with the pipeline logic. S3 added it reasoning *"three machines run this pipeline"*; after this,
  two do. **Update the ADR.**
- **While you are in there: `collectors.yml` has NO `STORE_ROLE` at all.** Same runner class, writes
  through `SNAPSHOT_BACKEND=supabase`. **Determine whether it can reach a laptop-owned writer.** A
  hole there has been open since S3 and nobody has looked. **Report it either way; fix it only if it
  is small.**

**Keep GitHub as the scheduler.** Free, reliable, already trusted for the collectors, Tue+Wed crons
and the catch-up pattern proven. Change *what* it runs, not *when*.

### The two traps specific to a cadence

**(a) The no-op trap INVERTS here.** Every prior session ran on *"a run that skips everything as
'already current' is not a proof."* For a **catch-up** cron a no-op is the **correct** outcome —
Wednesday should do nothing when Tuesday worked. So do not apply that rule blindly. The real
requirement is harder: **"already current" must be distinguishable from "did not run" and from
"failed", from outside, without reading worker logs.** `jobs` rows are how. Say how a person tells the
three apart.

**(b) The demo must not be enumerated.** `DEMO-2025` is synthetic and `weekly_refresh` **raises**
loudly on a synthetic league by design (S2d's producer-side rule). Enumerating from `user_leagues`
excludes it naturally — nobody owns the demo — while `league_catalog` would hit it **every week**.
State that as the *reason* for the source, not as a coincidence.

**Dedup is already built:** `jobs_active_league_idx` is UNIQUE on `(league_id, season)` **partial** on
non-terminal states. Decide what the Wednesday insert does when Tuesday's job is still active — the
index refuses it, refusing is right, and it must not be logged as a failure.

## Scope guard

Does **NOT**: build the pending/hold lifecycle (**S4f** — S4d refuses, S4f holds) · the Manager
Dossier executor or `panels_manager` (**S4e**) · S5's preflight or rejection copy · alerting for a
failed refresh (**P6**; the collectors' coverage-gate email is the precedent) · rewrite `check_queue`'s
live legs to use an uncommitted transaction (**S4b recorded it; it belongs to a session that owns that
file**) · `--emit`/`--load` against production · engine constants, any transform's maths, the corpus,
the frozen corpus manifest, or `demo_manifest.parquet`'s 31 rows.

**Named release valve:** the **stale live isolation fixtures** (`check_ownership` / `check_isolation`
hardcode `DEMO = "1182101676608823296"`, the id S2d replaced; 55 live failures, all in the
*refused-what-was-expected-readable* direction, **zero leaking**). Refresh them if there is room;
**if not, say so and they go to S4f**, which also needs the ownership table's gates to mean something.
**§§1–3 are NOT the valve** — they are the launch path.

---

## The brief to paste to Code — S4d

```
Goal: V1 Project 5, Session S4d — fix the two defects Will's live link test exposed, then make every
linked league advance a week unattended by enqueuing onto S4b's queue and gutting
.github/workflows/weekly_refresh.yml. WEEK-1 CRITICAL: NFL Week 1 is Thu 10 Sept 2026.

Read first: sessions/v1/P5-Self_Serve/SESSION_P5_S4D_WEEKLY_CADENCE.md (this brief),
SESSION_P5_S4C_REPORT.md + SESSION_P5_S4C_AUDIT.md, SESSION_P5_S4B_REPORT.md,
context/appendices/store-boundary.md, OPERATIONS.md, CODING_BIBLE.md, SESSION_GUIDE.md. CHECK THIS
BRIEF AGAINST OBSERVABLE REALITY BEFORE EXECUTING — it has been wrong in every session so far and you
have caught it every time.

WHAT THE LIVE TEST FOUND (this reframes the session). Will linked his real 2026 league from production
and got a raw FileNotFoundError on
.../nfl_sleeper_weekly_joined/league/1389327290164314112/season_2026.parquet.
THE BLOCKER IS NOT THE DRAFT — IT IS COMPLETED WEEKS. _pull_raw fetches matchups via sleeper.backfill,
which writes ONLY COMPLETED regular-season weeks; _determine_completed_weeks returns 0 while
season_type == "pre" and leg - 1 during the regular season. No matchups files -> no join file ->
compute_spine._compute_league calls compute_production_vor with NO GUARD on that file existing.
Consequences: (a) a DRAFTED league fails identically today; (b) `completed = leg - 1` means the first
completed week lands ~17 Sept, A WEEK AFTER Week 1 — so a cohort member linking at launch hits this
same error; (c) from now to 10 Sept no 2026 league can produce anything, which is why the pending/hold
state is S4f. S4d does not build S4f. It makes the window smaller and the failure honest.

1. THE CURRENT-WEEK FETCH — the launch-path fix.
   sleeper.refresh() ALREADY fetches the current week's matchups regardless of completion
   (sleeper.py:718) — the projections-only path the architecture describes, where the join zero-fills
   actuals and P2/S4a's thin-data window honestly reports 0 weeks of results. The cold onboard chain
   just does not use it; it uses backfill, which waits for completion.
   TEACH THE ONBOARD FETCH TO PULL THE CURRENT IN-PROGRESS WEEK WHEN THERE IS ONE. That is what makes
   linking work AT Week 1 rather than a week later.
   IT DOES NOTHING BEFORE 10 SEPT AND THAT IS CORRECT — leg is 0 in the preseason, so there is no
   current week. Say so rather than implying this fixes August.
   DO NOT ASSUME THE JOIN IS THE ONLY BLOCKER. production_vor, true_rank, positional_depth,
   bracket_odds (a Monte Carlo) and player_signal have NEVER run on a league with zero realized
   results. DETERMINE what each does. If one cannot honestly produce a read on a zero-results league,
   SAY SO — that is a finding about the thin-data window, not a bug to paper over.
   STATE THE DIVISION OF LABOUR IN THE CODE: the onboard's current-week snapshot is a POINT IN TIME.
   On a re-run _raw_present is true and _missing_raw_weeks (bounded by COMPLETED weeks) reports nothing
   missing, so the stale in-progress week is not re-pulled. Keeping it current is the CADENCE's job.

2. THE ERROR THE USER SEES.
   The raw FileNotFoundError, INCLUDING AN INTERNAL FILESYSTEM PATH, was rendered straight into the UI.
   S4c's rule "end the screen with whatever words the refusal already carries" is right for an AUTHORED
   SystemExit and wrong for an UNHANDLED EXCEPTION. Today any crash anywhere in the chain becomes
   user-facing text with our paths in it.
   USE THE DISTINCTION THE CODEBASE ALREADY MAKES: SystemExit = a deliberate, human-readable refusal
   (belongs on the screen); anything else = a crash (belongs in the job row and the logs, with
   something honest and non-leaking on screen). `rejected` vs `failed` ALREADY encodes this — use it
   rather than inventing a second mechanism.
   ALSO FIX THE RETRY SEMANTICS: a deterministic refusal that retrying cannot change should be
   `rejected` (terminal), not `failed` (retried to the cap). A league with no completed weeks cannot
   succeed on attempt 2 or 3.

3. PRE-DRAFT: REFUSE FOR NOW, BUT BUILD THE DETECTION SO S4f CAN REUSE IT.
   platforms.classify rules out non-current-season, non-redraft and an unsupported reception tier —
   never whether the league has STARTED. Sleeper's league objects carry `status` in the SAME discovery
   response (verified 2026-08-14 across Will's seven leagues: pre_draft, drafting, in_season all
   observed). One more rule, zero extra API calls.
   BUILD IT KNOWING S4f REPLACES THE RESPONSE, NOT THE DETECTION. S4f holds a not-yet-ready league as
   PENDING; S4d refuses it. Same predicate, different branch — so put the predicate where S4f can
   change the branch without re-deriving it.
   DO NOT GREY ON "0 COMPLETED WEEKS" — that is now true of EVERY 2026 league until ~17 Sept and would
   refuse the entire cohort. `status` is the discriminator for "no rosters exist"; completed weeks is a
   different question and §1 handles it.

4. THE CADENCE.
   worker_loop._EXECUTORS is {"onboard": ...} and its comment says "kind exists because S4d enqueues
   the weekly refresh." Add "refresh".
   THE EXECUTOR IS weekly_refresh.refresh_league(lid, season, live=True) — already works on a worker
   (S3's band-verify branch, weekly_refresh.py:219). And `lid = lid or
   league_resolver.resolve_league_id(season)` means A JOB CARRYING ITS OWN league_id NEVER TOUCHES THE
   RESOLVER, which RETIRES MY_USERNAME/LEAGUE_ID rather than relocating them.
   IF THE WORKFLOW ONLY HAS TO INSERT ROWS, IT NEEDS NO PYTHON, NO PIPELINE, NO CHECKOUT. Enumeration
   is a query — current-season leagues somebody owns, i.e. user_leagues JOIN league_catalog — and the
   job could be one INSERT ... SELECT over the DATABASE_URL it already holds. DETERMINE WHETHER THAT IS
   RIGHT rather than taking it from me. Two consequences if it is:
     - weekly_refresh.yml stops being a machine that can write the store, so STORE_ROLE=worker goes with
       the pipeline logic. S3 added it reasoning "three machines run this pipeline"; after this, two do.
       UPDATE THE ADR.
     - WHILE YOU ARE IN THERE: collectors.yml has NO STORE_ROLE at all. Same runner class, writes
       through SNAPSHOT_BACKEND=supabase. DETERMINE WHETHER IT CAN REACH A LAPTOP-OWNED WRITER. That
       hole has been open since S3 and nobody has looked. REPORT EITHER WAY; fix only if small.
   KEEP GITHUB AS THE SCHEDULER — change WHAT it runs, not WHEN.
   TRAP (a): THE NO-OP TRAP INVERTS HERE. For a CATCH-UP cron a no-op is the CORRECT outcome —
   Wednesday should do nothing when Tuesday worked. Do not apply the standing rule blindly. The real
   requirement is harder: "ALREADY CURRENT" MUST BE DISTINGUISHABLE FROM "DID NOT RUN" AND FROM
   "FAILED", from outside, WITHOUT reading worker logs. `jobs` rows are how. Say how a person tells
   the three apart.
   TRAP (b): THE DEMO MUST NOT BE ENUMERATED. DEMO-2025 is synthetic and weekly_refresh RAISES loudly
   on a synthetic league (S2d's producer-side rule). user_leagues excludes it naturally — nobody owns
   the demo — while league_catalog would hit it EVERY WEEK. State that as the REASON for the source.
   DEDUP IS ALREADY BUILT: jobs_active_league_idx is UNIQUE on (league_id, season) PARTIAL on
   non-terminal states. Decide what the Wednesday insert does when Tuesday's job is still active — the
   index refuses it, refusing is right, and it must not be logged as a failure.

PROVE IT.
 (1) A league linked with a CURRENT in-progress week builds and lands `ready` — or, if a spine read
     cannot honestly produce on zero results, it refuses with a reason and that is REPORTED as a
     finding. Either outcome is acceptable; silence is not.
 (2) A crash renders NO internal path to the user, and an authored refusal still shows its own words.
     Show both on screen.
 (3) A deterministic refusal lands `rejected` (terminal), not `failed` retried to the cap.
 (4) A pre_draft league is refused at discovery WITH A REASON.
 (5) EVERY LINKED LEAGUE ADVANCES A WEEK UNATTENDED, on the worker, triggered the way the cron will
     trigger it — not by hand. Show the jobs rows.
 (6) A SECOND RUN IS A CLEAN, LEGIBLE NO-OP: state which of "already current" / "did not run" /
     "failed" a reader sees and how they tell them apart.
 (7) MY_USERNAME and LEAGUE_ID are GONE from weekly_refresh.yml.
 (8) NOTHING ELSE MOVED: signed-out live prod returns EXACTLY the demo; league_catalog unchanged; the
     served tables move only for leagues that actually advanced, by count.
 VERIFY THE INSTRUMENT — but see trap (a): here a no-op is legitimate, so prove the DISTINCTION is
 visible, not that work happened every time. This project's signature failure has been caught SEVEN
 times, twice inside S4c alone.

Scope guard — does NOT: build the pending/hold lifecycle (S4f — S4d refuses, S4f holds); the Manager
Dossier executor or panels_manager (S4e); S5's preflight or rejection copy; alerting for a failed
refresh (P6); rewrite check_queue's live legs (S4b recorded it, it belongs to a session that owns that
file); run --emit or --load against production; touch engine constants, any transform's maths, the
corpus, the frozen corpus manifest, or demo_manifest.parquet's 31 rows.

Release valve: the STALE LIVE ISOLATION FIXTURES (check_ownership/check_isolation hardcode
DEMO = "1182101676608823296", the id S2d replaced; 55 live failures, ALL in the
refused-what-was-expected-readable direction, ZERO leaking). Refresh them if there is room; if not,
SAY SO and they go to S4f. §§1-3 ARE NOT THE VALVE — they are the launch path.

Suggested commit map (3): (1) the current-week fetch + the pre-draft detection/refusal + the worker
refusal for a rosterless league; (2) the error/retry semantics + the `refresh` job class + executor +
enumeration; (3) gut the workflow, the proving run, the ADR + docs.

Follow SESSION_GUIDE.md: fresh worktree, <=3 commits, update STATUS.md + ARCHITECTURE.md per §7
(REPLACE, don't append), OPERATIONS.md and the ADR (the machine count changes). §§1-3 change SERVED
code so the API needs a REDEPLOY; §4 changes the worker. Say which you deployed. A CHANGED BEHAVIOUR
RETURNING THE EXPECTED RESULT ON THE LIVE HOST IS THE PROOF THE IMAGE SHIPPED — S4c used 401-not-404
for exactly this. An appended cache-buster does NOT bust WebFetch's cache; reorder the params or use
the second hostname. Sweep .git for stale locks at closedown AND AGAIN AFTER COMMITTING.
```

## Will's checks after

1. **Try to link LoRP 2026 again.** It should refuse you politely with a reason — not a stack trace,
   and not a filesystem path.
2. **Ask what happens on 10 Sept vs 17 Sept.** The answer should be "it works on the 10th", and if it
   is not, that is the thing to know before the cohort arrives.
3. **Look at the `jobs` table on a week when nothing needed doing** — you should be able to tell
   "already current" from "never ran" without asking anybody.
4. **Both deploys** — `fly status -a fantasy-ai-api` and `-a fantasy-ai-worker`.
