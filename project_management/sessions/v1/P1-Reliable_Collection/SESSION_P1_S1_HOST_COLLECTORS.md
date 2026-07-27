# V1 · Project 1 · Session S1 — Host the daily collectors off-laptop — a brief for Code

**Last reviewed:** 2026-07-27 · **Status:** Ready to run (pending Will's storage-target confirm — see the
Decision) · **Owner:** Code drives; Will confirms the one fork + holds the CI secrets. **Project:**
`projects/v1/P1_RELIABLE_COLLECTION.md` (S1 of 2). **First session of V1 after Stage B — start now:
every day the laptop is the scheduler is a permanent hole in the 2026 series.**

> **What this session does:** move the two **banked daily collectors** — LeagueLogs market values (~4am ET)
> and NFL team-news RSS (~5am ET) — off Will's Mac (macOS `launchd`, ~63–71% coverage) onto a **hosted
> scheduler** that calls the *same* dispatcher the code already exposes, writing their raw output to a
> **durable store** a diskless runner can use. This is pure collection plumbing: it does **not** touch the
> live app, the served Postgres, or any transform. It just makes the 2026 market + news history start banking
> reliably — the prerequisite for the live trade read (P2) and live AI outlook (P4). `P1_RELIABLE_COLLECTION.md`.

## Your part, Will (~15 min + secrets)
Two things only. **(1) Confirm the storage target** (the Decision below — I recommend a Supabase Storage
bucket). **(2) Provide the CI secrets** (LeagueLogs access + the store-write credentials) — these go into the
scheduler's secret store, never the repo. After that it runs unattended. Your "looks right": both collectors
fire on schedule in the runner and land a fresh day's data in the store, and a manual re-run works.

## The one real decision — where does a diskless runner write? (confirm before build)

The collectors today write parquet to the local `snapshots/` tree via `data_layer`. A CI runner has **no
persistent disk**, so S1 has to point their output somewhere durable. Three options, with downstream effects
on P2 (which reads this raw data in the weekly transform):

- **(a) Commit snapshots into the repo** — dead simple + versioned, but a daily market/news series bloats git
  history and repo size over a season. *Not recommended.*
- **(b) A durable object store — a Supabase Storage bucket** *(recommended)*. You're already on Supabase; a
  bucket is a natural durable home, it keeps raw collection **decoupled from both git and the served schema**,
  and P2's transform reads parquet from it the same way it reads local parquet today. The clean seam.
- **(c) A Postgres "raw snapshots" table** — queryable, but it couples raw collection into the served DB
  (schema churn, mixes raw with served). *Not recommended.*

**Recommendation: (b) Supabase Storage.** It's the smallest blast radius and the most natural fit for P2. I'm
flagging it for your explicit confirm because it also shapes how P2 reads — but I'd proceed on (b) unless you
say otherwise. **Scheduler platform:** GitHub Actions is the lead (free scheduled cron, first-class secrets);
a Fly scheduled machine is a viable alternative since you're already on Fly — Code should pick whichever it
can stand up cleanly, Actions first.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Call the existing dispatcher — don't rebuild collection.** The scheduler's only job is to invoke
   `python3 -m application.data.fetchers.run leaguelogs` and `... run news` on schedule (the `run.py`
   dispatcher already wraps each collect + a post-run freshness check; its docstring anticipates exactly this
   launchd→Actions move). Do **not** reimplement the fetchers — this session is hosting + a storage seam, not
   new collection logic.
2. **Add a storage backend seam in `data_layer`, don't fork the fetchers.** The fetchers write via
   `data_layer`; add a backend switch (local FS ↔ the durable store) chosen by env/config, so the *same*
   fetcher code writes to the bucket in CI and to local `snapshots/` when run on a laptop. One seam, both
   environments — no divergent code paths.
3. **Independent schedules, in UTC.** Keep the two collectors on separate times (they don't overlap today:
   4am + 5am ET). Cron in CI is UTC — convert from ET and accept the ±1h DST drift (or handle it), and
   document it. These are daily banks; a few minutes' jitter is fine.
4. **Retire the launchd plists as part of cutover** — but only once the hosted runs are proven landing data,
   so there's no gap. Leave a short note in `scheduler/` pointing at the workflow that replaced them.
5. **Verify the runner environment EARLY** (biggest likely surprise): the fetchers were built for Will's Mac —
   confirm the CI runner has network egress to LeagueLogs + the 96 RSS feeds and can install the fetcher deps
   (`nflreadpy` isn't needed for these two, but RSS/HTTP libs are). Prove one real end-to-end run before
   wiring the schedule.
6. **Scope guard — do NOT touch** the served Postgres, the app, any transform, or `sleeper`/`nfl_stats`
   (those are on-demand in P2, not banked dailies). The `metadata.json` fetch-timestamp sidecar, retry/backoff,
   the coverage alert, and the 2-week soak are **S2** — unless the metadata timestamp is trivial to write while
   you're already touching the write path, in which case folding it in is welcome (note it if you do).

## The brief to paste to Code

```
Goal: V1 Project 1, Session S1 (projects/v1/P1_RELIABLE_COLLECTION.md) — host the two banked daily collectors
(leaguelogs market values, team-news RSS) off Will's laptop on a hosted scheduler, writing to a durable store
a diskless runner can use. Collection plumbing only: do NOT touch the live app, served Postgres, transforms, or
the on-demand sleeper/nfl_stats fetchers. Storage target: Supabase Storage bucket (Will-confirmed) unless told
otherwise. Scheduler: GitHub Actions (lead) or a Fly scheduled machine — whichever stands up cleanly.

Part 1 — storage seam:
- Add a data_layer storage-backend switch (local FS <-> the durable store) chosen by env/config, so the SAME
  leaguelogs.py/news.py fetchers write to the bucket in CI and to local snapshots/ on a laptop. Don't fork the
  fetchers; don't change what they collect.

Part 2 — host the scheduler:
- A hosted scheduler invokes the existing dispatcher: `python -m application.data.fetchers.run leaguelogs` and
  `... run news`, on independent daily schedules (today 4am + 5am ET; cron is UTC — convert + document DST).
- Secrets (LeagueLogs access + store-write creds) live in the scheduler's secret store, never the repo.
- Verify the runner FIRST: network egress to LeagueLogs + the 96 RSS feeds, deps install, one real end-to-end
  run landing data in the store. Then wire the schedule. A manual re-run (workflow_dispatch or equiv) must work.
- Retire the launchd plists only AFTER hosted runs are proven landing data (no collection gap); leave a pointer
  note in application/data/fetchers/scheduler/.

Out of scope (S2): metadata.json fetch-timestamp sidecar, retry/backoff, the coverage-check alert, the 2-week
soak. (If writing the fetch timestamp is trivial while you're in the write path, folding it in is fine — note it.)

Follow SESSION_GUIDE: fresh worktree, worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge, push.
Suggested commits: (1) data_layer storage-backend seam; (2) the CI workflow + secrets wiring + docs; (3) prove
one real hosted run landed data + retire/point-away the plists + STATUS. Show me: a successful scheduled (or
dispatched) run's log landing a fresh leaguelogs + news day in the store, and the manual re-run working.

Close: update STATUS.md (P1/S1 done: collectors hosted off-laptop, writing to <store>; next = P1/S2 —
metadata timestamps + retry + coverage alert + 2-week soak to prove >=95%). Merge/push.
```

## Definition of done (S1)
✅ Both daily collectors run **on a hosted scheduler** (not the laptop), invoking the existing
`run.py` dispatcher, and land fresh LeagueLogs + news data in the confirmed durable store; secrets are in CI,
not the repo; a manual re-run works; the launchd plists are retired only after hosted runs are proven (no gap);
the live app / served Postgres / transforms are untouched. STATUS updated, P1/S2 next.

## Notes / gotchas
- **This is the "bank it or lose it" clock.** The whole reason P1 is first is that missed days are permanent.
  Prioritize getting *a real hosted run landing data* over polish — S2 does the reliability hardening.
- **CI env drift is the likely S1 surprise** — verify network egress + deps in the runner before trusting the
  schedule. A collector that imports fine locally can fail on a runner's egress rules.
- **Keep the local path working.** The storage seam must not break running the collectors (or the P2 transform)
  on a laptop — env-selected backend, same code.
- **Don't bank into the served DB.** Raw collection lands in the durable store; the served Postgres only
  changes via the P2 weekly transform. Keeping those separate is the point of the (b) recommendation.
- **P2 depends on this store choice** — once (b) is live, P2's weekly refresh reads the bucket. That coupling
  is why the storage target is Will's to confirm now, not a silent default.
```
