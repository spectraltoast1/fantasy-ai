# P5 · S0 Audit — the cold-league latency spike

**Reviewed:** 2026-07-31 · **By:** PM, against live code + the merged diff (commits `1baf625`, `e12a6ae`,
`016f255` + merge `da7e6d3` on `main`, 4 ahead of origin — **not yet pushed**).
**Report:** `SESSION_P5_S0_REPORT.md`.

**Bottom line: endorse it — this is the best-evidenced session report the project has produced, and its
central finding is real. I independently confirmed all three code findings and the scope guard. The headline
"connecting a league is cheap, the dossier is not" holds, and it is actually *stronger* than the report
claims: the dossier fan-out is documented in its own source as a once-per-season operation, so treating it as
part of connect was never the design. Two things to correct — one derived number is presented as if measured,
and the "$7/month" is worker cost, not product cost. Neither changes the verdict. S4 has grown; say so out
loud rather than discovering it mid-session.**

## Verified independently (not taken from the report)

- **Scope guard held exactly.** `git diff e1828a5..HEAD` = one new file (`bench_cold_league.py`, 446 lines),
  `STATUS.md`, the P5 project brief, and the three session docs. **No pipeline, transform, loader, engine
  constant, corpus, or ledger file touched** — grep for `corpus|ledger|_constants` across the diff returns
  nothing. A measurement session that measured and nothing else.
- **Finding 2 confirmed — and it is a live-path correctness bug.** `weekly_refresh._resolve_scoring_key`
  (weekly_refresh.py:42) scans `demo_manifest` slices and, on no match,
  `return data_layer._active_league(season)[1]` — **the owner's** scoring key. Every user league is absent
  from `demo_manifest` until S4 catalogs it, so a stranger's half-PPR league would be scored as PPR silently.
  Not a crash, not a visible error — a **wrong number with no signal**, which is the worst failure class this
  project has. Must land in S4/S5.
- **Finding 3 confirmed.** `build_db.load_league` (build_db.py:433) raises `SystemExit` when the league isn't
  a `demo_manifest` slice, with a comment that says cataloging a brand-new league "is onboarding/P5." So the
  ordering constraint is real: **catalog row first, then load.** No unload path exists.
- **Finding 1 confirmed.** `weekly_refresh`'s fetch stage calls only `sleeper.refresh` and `sleeper.backfill`
  (lines 113, 115) — no `fetch_league_config`, `fetch_roster_positions`, `derive_lineup_slots`, or
  `fetch_teams`. There is genuinely **no cold-onboard entry point**; the pipeline only knows how to *advance*
  a league that already exists.
- **The dossier claim is confirmed and understated.** `fetch_manager_activity` carries
  `throttle: float = 0.2` and a docstring stating "hundreds per full run" and **"run at most once/season."**
  `write_manager_dossiers.run` refuses to re-run: *"already exist — run once per season."* Model is
  `claude-haiku-4-5`, one call per manager, zero-signal managers skipped. **Two independent places in the
  source declare this a seasonal operation.** The report treats it as a slow step in onboarding; it is better
  understood as a **different cadence entirely** (see below).
- **The cold/warm evidence is real.** The report's re-run with `--allow-warm` gave fetch 0.00s / join 0.00s
  against 6.97s / 0.25s cold. That is the exact trap the brief warned about, and it was demonstrated rather
  than avoided. Both new guards were shown to bite.

## Two corrections

1. **The ~3.8s Week-1 figure is derived, not measured — and the verdict paragraph doesn't say so.** The two
   measured totals are **10.35s** and **8.43s**. The 3.8s is reconstructed from the per-call log after
   subtracting a fetch that `sleeper.backfill` didn't actually cap (finding 4). The report *is* honest about
   this in the body — "derived from the per-call log, not assumed" — but the one-paragraph verdict leads with
   "10.3 seconds ... or ~3.8 seconds," which reads as two measurements. **The defensible claim is "the
   measured floor is 8.4s and the modeled Week-1 case is ~4s once the week cap is fixed."** Same conclusion —
   both are comfortably inside spinner territory — so nothing downstream changes. Flagged because a modeled
   number presented as a measured one is precisely how an unearned number enters the record, and this project
   has a rule about that.
2. **"$7/month flat at 200 leagues" is *worker* cost, not *product* cost.** It's right about Fly, and the
   reasoning is sound (a singleton machine's duty cycle swamps the work). But the per-league cost that
   actually scales is metered per token, not per second: **12 Haiku calls per league at dossier time**, plus
   P4's ROS synthesis, which is roster-wide per league and explicitly **unmeasured**. The honest headline is
   *"Fly is a rounding error; the AI line is the one to watch, and P4 is where it gets measured."*
   Also: **248 calls is a sample, not a constant** — the fan-out is up to 5 comparable leagues per manager
   across 3 seasons, so it scales with league size and how much fantasy the managers play. Set caps against a
   range, not against 248.

## The finding that changes the plan — and Will's read on it is right

Will's instinct after skimming the results: *the instant/queue split isn't about the league as a whole, it's
about splitting the dossier out.* **That is correct, and the source supports it more strongly than the report
does.** The dossier is not "the slow part of onboarding" — it is a **once-per-season, manager-keyed
enrichment** that was never designed to run per connect. So the right shape isn't "defer the slow step," it's:

- **Connect = the fast path.** Fetch → join → spine → schedule → load. ~4s at Week 1, ~10s mid-season, four of
  five surfaces live. A spinner, honestly.
- **Manager profiling = a separate job class on its own cadence.** Connect *enqueues* it; a background drain
  works it off. The Dossier surface shows an honest "still gathering manager history" state meanwhile — which
  the app already knows how to do (it has "no intel" / "no dossier" states from B6).
- **And because the work is keyed to *managers*, not leagues, it dedupes.** The same manager appearing in two
  connected leagues, or two users in one league, is one profiling job, not two. That is a real efficiency the
  per-league framing hides.

**One thing to resist:** 50 of the 80 seconds is the self-imposed 0.2s politeness throttle. It will be
tempting to turn it down. Don't — Sleeper is a free public API this entire product depends on, and buying 50
seconds by being rude to it is penny-wise. **Deferring the work is free; speeding it up spends goodwill.**

**One thing to clarify with Will:** he said the dossier should run *"locally by queue instead of going through
the cloud worker."* If "locally" means *on his laptop*, that reintroduces the laptop as production
infrastructure — the exact thing S3 exists to eliminate, and it would mean a user's dossier silently never
arrives whenever his machine is off. If it means *a separate deferred queue rather than inline in the connect
job*, that's right. Assume the latter unless he says otherwise.

## What this does to the session map

**S4 grew, and it grew for good reasons.** It now carries:

- **two job classes** with different cadences (league build; manager profiling), not one queue;
- **a cold-onboard entry point that does not exist yet** (finding 1) — the cold half currently lives in
  `corpus/harvest._pull_raw`, a corpus-batch module. The harness composes the right steps in the right order
  and is the best available spec for it;
- **the catalog-row-before-load ordering** (finding 3), plus a teardown path S6 needs;
- **the scoring-key fix** (finding 2) — arguably S5's, since it's league-shape resolution, but it must not
  fall between the two;
- **the `sleeper.backfill` week cap** (finding 4) — trivial, real, and it's what makes the ~4s Week-1 number
  true rather than modeled.

That's still one session's worth, but it is no longer the small one the map implied. **S3 is unchanged and
gets easier** — finding 5 confirms the pipeline cone imports without `config.py`, so no config plumbing on the
worker.

## Minor

- **The 2026 `projection_consensus` row-order churn is correctly diagnosed and correctly parked** —
  sorted-equal on a unique key, `ros_player_band` byte-identical downstream, `check_forward_substrate` green.
  The S3 consequence is right: a checksum sync will re-upload 110KB it didn't need to. Compare sorted content
  or accept it. Not worth a fix.
- **Main is 4 commits ahead of origin — push it.** S2's report once claimed "4 ahead" when git said otherwise;
  this time git says ahead and it's real.
