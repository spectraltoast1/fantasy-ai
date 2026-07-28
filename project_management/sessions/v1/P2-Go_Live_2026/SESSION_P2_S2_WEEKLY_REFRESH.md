# V1 · Project 2 · Session S2 — The in-season weekly refresh + incremental loader — a brief for Code

**Last reviewed:** 2026-07-28 · **Status:** Ready to run · **Owner:** Code drives; Will confirms the
incremental-load strategy + eyeballs the parity proof. **Project:** `projects/v1/P2_GO_LIVE_2026.md` (S2 of 4).
**This is the single riskiest change in all of V1 — it touches the production loader. The byte-parity guard is
the whole safety net.**

> **What this session does:** build the **live cadence** — a per-league job that advances a league to the
> **current week** (pull its current Sleeper state + weekly stats → join → spine transforms → load), and
> change the loader from the all-or-nothing **DROP+CREATE of the whole DB** to a **per-league scoped reload**
> that updates one league without disturbing the others. This is what un-freezes the app from the 2025 replay.
> S1 gave 2026 a basis; S2 makes it *advance*. `P2_GO_LIVE_2026.md` S2.

## The timing reality that shapes verification (read first)
It's preseason — **2026 has no games played yet**, so there is nothing to "advance" on live 2026 data until
Week 1 (September). So S2 **builds and proves the machinery now against a season that HAS weeks** — replay the
is_mine **2025** league week-by-week (its data exists for all weeks) to prove the weekly-advance mechanics,
idempotency, and the parity guard. Once built and proven on 2025, it's ready to run on live 2026 the moment
games start. Don't wait for 2026 games to build this.

## Your part, Will (~5 min — one decision + the parity eyeball)
One call: the **incremental-load strategy** (below; I recommend the per-league scoped reload). Otherwise the
check that matters is the **parity proof** — that refreshing one league incrementally produces *exactly* what
a full rebuild of that league would, so nothing drifts.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Incremental load = a per-league *scoped reload*, not row-level upserts (recommended).** For a given
   `league_id`, recompute that league's derived slice and, in one transaction, **delete that league's rows and
   re-COPY them** across the tables — leaving every other league untouched. It's "incremental" at the
   **league grain**: it swaps out one league without the full DROP+CREATE, but each league is still a clean
   full recompute, so it's simple and trivially verifiable. This sidesteps the real danger of true row-level
   incremental (upsert conflicts, partial-week dedup, drift) while getting the essential property. *(The
   efficiency of appending just the new week is a later optimization — don't take that risk now.)*
2. **The parity guard is non-negotiable — this is the B3 lesson applied to the loader.** A per-league scoped
   reload of a league must be **byte-identical to what a full DROP+CREATE reload produces for that league** on
   its already-loaded weeks. Prove it: full-reload the DB, snapshot a league's rows; scoped-reload just that
   league; diff — identical. If it isn't identical, stop. This is the safety net that lets us change the
   production loader without fear.
3. **Idempotent + re-runnable.** Running the refresh twice must be a **no-op** the second time (same week, same
   data → same rows). Re-running after a partial failure must converge, not double-load.
4. **Prove it on 2025 first (the is_mine parity anchor); live-2026 rides the same path.** Build + verify the
   whole thing by advancing the is_mine 2025 league week-by-week (data exists). The is_mine slice is the parity
   anchor throughout. Do **not** try to onboard arbitrary user leagues here — connecting a user's own league is
   **P5**; S2 is the refresh *mechanism* for an already-loaded league.
5. **Cadence: reuse the P1 GitHub Actions scheduler; weekly, mid-week.** Once the refresh runs on-demand and
   parity holds, wire a weekly cron (Tue/Wed, after stat corrections settle — freshness vs stability) on the
   P1 hosted scheduler. On-demand `workflow_dispatch` first to prove a real run; the cron is a thin add. *(If
   the session is getting big, the cron wiring is the natural piece to land last or split — the loader change +
   orchestrator + parity is the core.)*
6. **Handle "no actuals yet" gracefully.** In preseason (and Weeks 0–early), the weekly fetch has rosters +
   projections but **no realized stats** — the refresh must advance cleanly on projections-only without
   fabricating results (consistent with S1's forward path; the early-week "too early" rendering is S4). Don't
   let an empty `nfl_stats` week crash the pipeline.
7. **Scope guard.** This session **does** touch `build_db.py` (the loader) — that's the point and the risk,
   guarded by parity. It does **not** touch the frontend (surfacing the honest band + the live market read is
   **S3**) or auth/onboarding (**P5**). Keep the loader change reversible (the full DROP+CREATE path stays
   available as the fallback + the parity oracle).

## The brief to paste to Code

```
Goal: V1 Project 2, Session S2 (projects/v1/P2_GO_LIVE_2026.md) — the in-season weekly refresh pipeline + the
loader change from full DROP+CREATE to a per-league scoped reload, so a league advances to the current week
without rebuilding the whole DB. Single riskiest V1 change — the byte-parity guard is non-negotiable. Depends
on S1 (2026 substrate) + P1 (collection). Preseason has no 2026 games yet, so BUILD + PROVE against a season
with weeks (replay is_mine 2025 week-by-week); it's ready for live 2026 once games start.

Part 1 — the weekly-refresh orchestrator (new):
- A per-league job: fetch the league's current Sleeper state (rosters/matchups/transactions) + nfl_stats
  weekly + Sleeper projections -> join_nfl_sleeper_weekly -> the spine transforms (compute_spine et al.) ->
  load, advancing as_of_week. Idempotent + re-runnable per league. Handle a week with no realized stats
  (preseason/early) gracefully — projections-only, no fabricated actuals, no crash.

Part 2 — the incremental loader (build_db.py — the risky change):
- Replace whole-DB DROP+CREATE with a per-league SCOPED RELOAD: for a league_id, recompute its derived slice
  and in ONE transaction delete that league's rows + re-COPY them across the tables; other leagues untouched.
  Keep the full DROP+CREATE path available (fallback + parity oracle).

PARITY GUARD (non-negotiable — do not skip):
- Prove a per-league scoped reload == a full DROP+CREATE reload for that league, byte-for-byte, on
  already-loaded weeks. (Full-reload, snapshot a league's rows; scoped-reload just that league; diff ==
  identical.) Prove idempotency: running the refresh twice is a no-op. Anchor on the is_mine 2025 league; a
  week-by-week replay advances it correctly (rosters/standings/matchups) and re-running any week is a no-op.

Cadence (thin, land last or split if big):
- Reuse the P1 GitHub Actions scheduler: a weekly cron (Tue/Wed after stat corrections settle) + on-demand
  workflow_dispatch to prove a real run.

Scope guard: touches build_db.py (guarded by parity). Does NOT touch the frontend (honest band + live market =
S3) or auth/onboarding (P5). Do NOT change Fly secrets.

Follow SESSION_GUIDE: fresh worktree, worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge, push.
Suggested commits: (1) the per-league scoped-reload loader change + the parity oracle/test; (2) the
weekly-refresh orchestrator + idempotency; (3) the 2025 week-by-week proof (+ the weekly cron if it fits) +
STATUS. Show me: the parity diff (scoped vs full reload, identical), and a 2025 league advancing week 4 -> 5
with a clean re-run no-op.

Close: update STATUS.md (P2/S2 done: per-league scoped-reload loader replaces DROP+CREATE, byte-parity proven;
weekly refresh advances a league idempotently; proven on 2025, ready for live 2026 at kickoff; next = P2/S3
surface honest band + live market). Merge/push.
```

## Definition of done (S2)
✅ A per-league weekly refresh advances a league to the current week (correct rosters/standings/matchups),
re-running is a **no-op**, and it is **not** a full DROP+CREATE. The loader does a **per-league scoped reload**
that is **byte-identical to a full reload for that league** on already-loaded weeks (parity proven). Proven by
replaying the is_mine 2025 league week-by-week; ready to run on live 2026 once games start. Preseason/no-actuals
weeks advance gracefully. Frontend + auth untouched. STATUS updated, S3 next.

## Notes / gotchas
- **This is the change to be careful with.** Everything else in V1 assumes the app can advance a league
  weekly without nuking the rest. The parity guard (scoped reload == full reload for that league) is exactly
  the discipline that made the B3 production reload safe — apply it here with the same seriousness.
- **Keep the full reload as the fallback + the oracle.** Don't delete the DROP+CREATE path; it's both the
  safety valve and the thing parity is measured against.
- **Preseason means "prove the mechanics, not the live feed."** 2026 has no games until September, so 2025 is
  the exercise track. When 2026 games start, the same job runs — no new code, just live data.
- **Source lag is real.** Stat corrections settle over a few days; the Tue/Wed cadence trades a little
  freshness for stability. Note it; don't chase Monday-night numbers that move.
- **The live market read still depends on P1.** S3 turns the market read live (2026 × 2026, no longer
  cross-time), and its quality rests on the daily collection the P1 soak is proving — so the honest gating
  (show the panel only when the collection is trustworthy) carries into S3.
- **Handoff to S3:** with 2026 advancing, S3 surfaces the honest band in the UI and converts the market read
  from cross-time POC to a live 2026 read. S2 makes the data move; S3 makes what the user sees true.
```
