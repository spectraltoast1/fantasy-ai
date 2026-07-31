# V1 · Project 5 · Session S0 — The cold-league latency spike — a brief for Code

**Last reviewed:** 2026-07-31 · **Status:** Ready to run · **Owner:** Code drives end to end; Will reads a
one-page verdict and supplies a non-demo Sleeper `league_id` if he has one handy.
**Project:** `projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md` (S0 of P5). **The first session of P5.**

> **What this session does:** find out what "connect your league" actually costs — in wall-clock time, in
> memory, in disk, and in Sleeper API calls — by timing the existing pipeline on a league the store has
> **never seen**. It writes almost no product code. Its output is a **number, a per-step breakdown, and three
> recommendations**: how big the Fly worker needs to be, whether the connect flow is a spinner or an email,
> and where to set the compute caps that keep the bill bounded.

> **Why it runs first:** three later sessions are about to be built on top of an unmeasured assumption. If a
> cold league takes ~4 minutes, self-serve-instant is real and S4's connect flow is a progress spinner. If it
> takes ~40, "instant" was never on the table, the UX is a notification, and S3 may need to pre-warm work that
> nobody has budgeted. Learning that *now* costs one short session. Learning it in S4 costs a redesign.

---

## The timing reality

Nothing here needs a 2026 league or a played game — it needs a league the derived store has never processed,
which is available today. This session is fully executable and fully conclusive right now.

---

## Your part, Will (~5 min)

**One optional input:** if you have a Sleeper `league_id` for a real, in-scope league (redraft, PPR or half,
1QB or superflex) that is **not** one of the 12 demo lineages, hand it over — a real stranger-shaped league is
the most honest test. If you don't, Code will find a public one. Either is fine.

**Then read the verdict**, which will be one page: how long, which step dominates, how big a machine, spinner
or email, and what the caps should be. No forks for you unless the numbers surprise us — if they do, the
surprise itself is the finding and we'll talk before S1.

---

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **It must be a genuinely COLD league.** The pipeline has per-step on-disk gates (that's what makes
   `weekly_refresh` idempotent) — so timing a league that's already been processed measures the *gates*, not
   the *work*, and will look impossibly fast. Use a `league_id` that does not exist anywhere in the derived
   store or the catalog. Do **not** get a cold league by deleting an existing one's artifacts; that risks the
   frozen corpus and the demo slate for no benefit.

2. **Measure the whole chain, but report it by step.** `fetch → join → spine → band → load`. The split matters
   more than the total, because each step has a different fix. Fetch-dominated means parallelism and caching.
   Spine-dominated means CPU and RAM. Load-dominated means the database. A single total number tells us which
   machine to rent and nothing else.

3. **Answer the shared-substrate question explicitly — it is the biggest unknown in the total.** The claim in
   the P5 brief is that the 2026 ppr/half substrate is *shared* across leagues, so a new league on an existing
   scoring key should reuse it rather than rebuild it. **Verify that, don't assume it.** Then report both
   numbers: cold-with-substrate-reuse (the normal case) and cold-including-a-substrate-build (the first league
   on a new scoring key). If those differ by an order of magnitude, that gap is a product decision waiting to
   happen, and S4 needs to know.

4. **Capture the resource ceilings, not just the clock.** Peak RSS, peak temp-disk, and the net disk the store
   grows by for one added league. RAM is the dominant cost driver on Fly (~$5/GB/month), so this is what
   actually sizes the machine and the volume. Also note whether the heavy step is CPU-bound or I/O-bound — if
   it's I/O-bound, a bigger machine buys nothing and we shouldn't pay for one.

5. **Count the Sleeper API calls for one cold league.** This sets the rate limit in S5 and tells us whether a
   burst of simultaneous connects would trip Sleeper before it troubles Fly.

6. **Convert the measurements into the three recommendations — that's the actual deliverable.**
   - **Machine size** for the S3 worker (RAM, CPU, volume), with the reasoning.
   - **Spinner or email**, against these thresholds: **under ~90s** → a spinner the user waits on;
     **~90s to ~10 min** → a progress screen they can leave and return to; **over ~10 min** → a notification
     is mandatory and the UX must not pretend otherwise.
   - **The compute caps** (Will's bill-anxiety guardrail, settled 2026-07-31): a per-user connected-league cap,
     a daily global job ceiling, and the estimated **$/month at 10, 50, and 200 connected leagues** on a
     single always-available worker. Ground every number in what you measured. If the honest answer is "this
     is a rounding error until several hundred leagues," say that plainly — that is a useful finding.

7. **A spike measures; it does not change behavior.** No product code, no tuning, no constants. The one thing
   worth *keeping* is the timing harness itself as a small committed script, because **S3 will re-run the exact
   same measurement on the Fly worker** and we want the two numbers to be comparable. Build it to be re-runnable
   elsewhere.

8. **Leave the store exactly as you found it.** Timing the load step means additively loading one scratch
   league into Postgres (safe — `load_league` is scoped to one `league_id` and proven byte-parity). Then remove
   it and **prove** the store is back: per-table row counts and the `demo_manifest` catalog identical to
   before. Capture the "before" counts first so the comparison is real rather than remembered.

---

## The brief to paste to Code

```
Goal: V1 Project 5, Session S0 (projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md) — the cold-league latency
spike. Measure what "connect your league" actually costs, so S3 can size the Fly worker, S4 can choose
spinner-vs-notification, and we can set compute caps. This is a MEASUREMENT session: no product code, no
tuning, no constants changed.

Read first: context/STATUS.md, CODING_BIBLE.md, SESSION_GUIDE.md, ARCHITECTURE.md ("Data flow" +
"In-season refresh"), and application/data/serve/weekly_refresh.py.

Setup:
- Pick a league_id for a REAL, in-scope league (redraft, ppr or half, 1QB or SF) that does NOT exist anywhere
  in the derived store or the demo_manifest catalog. Will may supply one; otherwise find a public one.
- It MUST be cold. The pipeline's per-step on-disk gates make an already-processed league measure the gates
  instead of the work. Do NOT create a cold league by deleting an existing one's artifacts — that risks the
  frozen corpus and the demo slate.
- Capture BEFORE state first: per-table row counts + the demo_manifest catalog.

Measure, end to end, for that cold league:
1. Wall-clock per step: fetch / join / spine / band / load, plus the total.
2. Peak RSS and peak temp-disk during the run; the net bytes the derived store grows by for one league.
3. Whether the dominant step is CPU-bound or I/O-bound (if I/O-bound, a bigger machine buys nothing).
4. The number of Sleeper API calls made for one cold league.
5. SHARED SUBSTRATE — verify, don't assume: does a new league on an EXISTING scoring key reuse the 2026
   ppr/half substrate, or rebuild it? Report BOTH totals: cold-with-reuse (the normal case) and
   cold-including-a-substrate-build (first league on a new key). If they differ by an order of magnitude,
   call that out loudly — it changes S4's design.

Keep: a small re-runnable timing harness as a committed script. S3 will run the SAME harness on the Fly
worker so the two environments are directly comparable. Build it for that.

Clean up and prove it: remove the scratch league, then show per-table row counts + the catalog are IDENTICAL
to the before-state. Not "looks fine" — the actual comparison.

Deliver a ONE-PAGE verdict (a _REPORT.md in project_management/sessions/v1/P5-Self_Serve/) with:
- the per-step table and the totals;
- MACHINE SIZE recommendation for the S3 Fly worker (RAM / CPU / volume) with reasoning;
- SPINNER OR EMAIL, against these thresholds: <~90s = a spinner; ~90s-10min = a progress screen the user can
  leave and return to; >~10min = notification mandatory;
- COMPUTE CAPS: a recommended per-user connected-league cap, a daily global job ceiling, and estimated
  $/month at 10 / 50 / 200 connected leagues on ONE always-available worker (Fly: ~$5/GB RAM/month,
  $0.15/GB/month volume). If the honest answer is "a rounding error until several hundred leagues," say so.
- STATE PLAINLY that this was measured on a laptop: it licenses an order of magnitude and the SHAPE of the
  split, not a number that transfers to Fly. S3 re-measures on the real hardware.

Scope guard — does NOT: change any pipeline, transform, loader, or engine constant; touch the frozen corpus;
touch auth, the connect flow, the worker, or the demo slate; leave anything behind in the store.

Follow SESSION_GUIDE.md: fresh worktree + scripts/worktree-setup.sh, <=3 commits (this should need 1-2),
update context/STATUS.md per the anti-bloat rule, then scripts/worktree-close.sh --merge and push. No
redeploy needed — nothing user-facing changed.
```

---

## Definition of done

1. A **cold** league — one the store has never seen — was processed end to end and timed.
2. A **per-step table** (fetch / join / spine / band / load) plus totals, not just a grand total.
3. **Peak RSS, peak temp-disk, net store growth per league**, and a CPU-bound vs I/O-bound call.
4. **Sleeper API call count** for one cold league.
5. The **shared-substrate question answered with evidence**, with both totals reported.
6. The **three recommendations** — machine size, spinner-vs-notification, compute caps + $/month at 10/50/200.
7. The scratch league is **removed and the store proven identical** to its before-state by actual comparison.
8. A **re-runnable timing harness** committed, built so S3 can run it unchanged on the Fly worker.
9. The report **states its own limits**: laptop-measured, so an order of magnitude and a shape, not a
   transferable number.

## Scope guard

Touches: a timing harness script · a report · `STATUS.md`. Additively loads and then removes **one** scratch
league.

Does **not** touch: any pipeline, transform, loader, or engine constant · the frozen corpus · auth · the
connect flow · the worker · the demo slate · anything user-facing (so no redeploy).

## Notes / gotchas

- **The most likely way this session produces a wrong answer is a not-actually-cold league.** If the total
  comes back implausibly fast, suspect the per-step gates before believing it. A suspiciously clean value is a
  bug until proven otherwise (standing rule 1).
- **The second most likely is measuring the substrate build as if it were per-league cost** — which would
  overstate the per-user price by a lot and could push us into buying a machine we don't need. Hence the
  both-numbers requirement.
- **`load_league` is safe to use additively** — it's scoped to one `league_id` in one transaction and was
  proven byte-parity-identical to a full load in P2/S2 (`serve/check_scoped_reload.py`). That's why timing the
  real load step is acceptable here rather than estimated.
- **Sleeper may rate-limit or throttle** a cold pull of a full season. If that happens, that *is* a finding —
  report it, don't work around it silently; it directly shapes S5's preflight and the connect-burst behavior.
- **This number feeds a product decision, not just an ops one.** If the cold build is slow, the honest
  response is a notification UX — not a spinner that lies about how long it will take. The north star applies
  to loading states too.
