# Stage B — Session B6: End-to-end verification across every league × season — a brief for Code

**Last reviewed:** 2026-07-26 · **Status:** Ready to run · **Owner:** Code drives (worktree preview + browser
automation); Will eyeballs the two proof screenshots. **Depends on:** B5 (selectors + viewer identity + panel
gating live — done). **This is the LAST Stage-B session — it closes the multi-league demo.**

> **What this session does:** actually *drive* the whole demo — click through **every one of the 12 leagues ×
> each of their seasons (31 slices) × a few sample weeks** — and prove each one renders correctly, honestly,
> and without errors. This is a **verification session**, not a feature build: the deliverable is a
> pass/fail **coverage matrix** over all 31 slices plus two contrasting proof screenshots, and any per-slice
> breakage gets fixed in-session or logged. Nothing new gets designed; B0–B5 built the machine, B6 confirms
> it works end to end. `MULTI_LEAGUE_STORE_MIGRATION.md` B6.

## Your part, Will (~10 min at the end)
This is the "does the whole thing actually work" session. When it's done you get a **matrix** — every league,
every season, green or red — and **two screenshots** that tell the story: your rich 15-week 2024 season next
to a sparse 12-team superflex corpus league, both rendering honestly (the corpus one gating its missing panels
instead of breaking). That's your proof Stage B is done.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Cover all 31 slices, sample the weeks.** Enumerate the full slate from `GET /api/leagues` (12 lineages →
   31 `(league_id, season)` slices). For each slice, check **3 sample weeks** — week 1, a mid week, and the
   latest available (from that slice's `weeks_available`) — not every week. ~31 slices × 3 weeks is the sweep;
   don't try to click all ~400 week-combinations.
2. **What to confirm per slice** (this is the matrix's columns):
   - **Renders** — the League/Players/Teams/Matchups surfaces load, no blank/crash, `read_console_messages`
     clean, `read_network_requests` shows `/api/*` **200s** carrying `league_id`+`season`(+`viewer_roster_id`).
   - **Identity** — the highlighted "me" is the slice's pinned `viewer_roster_id` (and leagues where the
     viewer isn't you still highlight the right roster, not a stale roster 8).
   - **Panel gating (honest, not broken)** — market shows only on lorp-2025 (elsewhere "Market VOR isn't
     available for this league"); ROS shows the "No rest-of-season outlook yet" empty state **everywhere**;
     dossiers render where present (the 11 computed slices) and "no intel" where sparse — no empty charts, no
     crashes.
   - **Week switcher bounded** — the week selector offers exactly that slice's `weeks_available` (a completed
     historical season runs its full slate 1..N; is_mine 2025 is 4).
3. **Two contrasting proof screenshots** (the migration-doc pair): **(a)** is_mine **2024** — a completed
   ~15-week season, dossiers present, market gated off; **(b)** a **12-team superflex/keeper** corpus slice
   (e.g. Winston Churchill Fan Club 2023 or Best Golden Balls) — empty dossiers ("no intel"), market + ROS
   gated off. Together they prove both the rich and the sparse ends render honestly.
4. **Bug policy — fix the small, log the large.** Per-league quirks *will* surface at scale (B4 already found
   one: a playoff-week NULL `matchup_id`). A small, contained render/gating bug: **fix it in-session** (you
   have the 3-commit cap). Anything structural or risky: **log it** in the verification report as a follow-up
   rather than forcing a fix into a QA session. Note whether each fix needs a redeploy.
5. **Where to run + parity anchor.** Sweep on the **worktree preview** (fast iteration if you're fixing), then
   a **final confirmation pass on the deployed app** (fantasy-ai-api.fly.dev) so the matrix reflects
   production; **redeploy** if any fix shipped, and re-confirm. Anchor: is_mine 2025 default still renders
   identically to today (the standing parity guard).

## The brief to paste to Code

```
Goal: Stage B, Session B6 (MULTI_LEAGUE_STORE_MIGRATION.md B6) — full end-to-end verification of the
multi-league demo across every league x season x sample weeks. This is a QA/verification session: produce a
pass/fail coverage matrix over all 31 slices + two contrasting proof screenshots; fix small per-slice bugs
in-session, log larger ones. Depends on B5 (selectors + viewer identity + panel gating, deployed).

Sweep:
- Enumerate all 31 slices from GET /api/leagues (12 lineages -> seasons). For EACH slice, drive the UI via the
  league+season selectors and check 3 sample weeks (1, a mid week, the latest in weeks_available).
- Per slice, record pass/fail for: (a) renders — League/Players/Teams/Matchups load, read_console_messages
  clean, read_network_requests shows /api/* 200s carrying league_id+season(+viewer_roster_id); (b) identity —
  the highlighted "me" is the slice's viewer_roster_id (null viewer -> no highlight, not a stale roster);
  (c) panel gating — market only on lorp-2025 else "not available"; ROS "No rest-of-season outlook yet"
  everywhere; dossiers present on the 11 computed slices, "no intel" where sparse; NO empty charts/crashes;
  (d) week switcher bounded to that slice's weeks_available.
- Watch for the per-league quirks that only appear at scale: playoff-week NULL matchup_id (B4 fixed matchups/
  team-detail — confirm no OTHER surface hits it), division-aware corpus leagues (teams.division), 8/10/12/14-
  team + superflex/keeper formats, completed-season full week slates vs the frozen is_mine 4 weeks.

Proof:
- Screenshot two contrasting slices: (a) is_mine 2024 (~15-week completed season, dossiers present, market
  off); (b) a 12-team superflex/keeper corpus slice (e.g. Winston Churchill Fan Club 2023 or Best Golden
  Balls — empty dossiers, market + ROS gated). Save both.

Bugs:
- Small contained render/gating bug -> fix in-session (3-commit cap), note if it needs a redeploy. Structural/
  risky -> log in the verification report as a follow-up, don't force it into QA.

Parity + deploy:
- Confirm the is_mine 2025 default still renders identically to today. Sweep on the worktree preview; then a
  final confirmation pass on the deployed app (fantasy-ai-api.fly.dev). If any fix shipped, redeploy and
  re-confirm the matrix + parity on the deployed app. Do NOT change Fly secrets.

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge,
push. Suggested commits: (1) any per-slice fixes found; (2) the verification report (coverage matrix + the two
screenshots + any logged follow-ups) + STATUS. If no bugs: just (1) the report + STATUS.
Show me: the coverage matrix (31 slices x the four checks) and the two screenshots.

Close: update STATUS.md — Stage B COMPLETE: all 31 slices verified end-to-end, panel gating honest, identity
correct, parity held; multi-league demo done. (Any logged follow-ups noted.) Merge/push.
```

## Definition of done
✅ A **coverage matrix** over all 31 slices (12 lineages × seasons) × sample weeks, pass/fail on: renders +
console/network clean, identity follows `viewer_roster_id`, panel gating honest (market/ROS/dossier), week
switcher bounded. **Two contrasting proof screenshots** (is_mine 2024 vs a 12-team SF/keeper corpus slice).
Any small per-slice bugs fixed (redeployed + re-confirmed if so); larger ones logged. is_mine 2025 default
parity confirmed. STATUS updated → **Stage B COMPLETE**.

## Notes / gotchas
- **This is QA, not a build.** The temptation will be to "improve" things mid-sweep — don't. Fix what's
  *broken*, log what's *missing*, and keep the scope to verification. New polish is post-Stage-B.
- **Verify in the browser, not via raw-API summaries.** (PM lesson from the B3–B5 audits: automated fetches of
  the JSON endpoints can serve stale/cached responses that look like real bugs — a corpus-league standings
  response got cached and masqueraded as a parity break. Drive the actual UI with `read_page`/screenshots and
  trust the rendered surface + `read_network_requests`, not a one-shot summary of an endpoint.)
- **The per-league quirks are the point.** At single-league scale everything looked clean; multi-league is
  where the NULL-matchup / division-column / rare-format edge cases live. Finding (and fixing/logging) them is
  the value of B6 — a matrix that's all-green on the first pass with zero notes probably didn't look hard
  enough.
- **Don't fold in the `projection_consensus *_ppr` naming wart** or other known-parked cleanups — log-only.
- **After B6, Stage B is done.** The multi-league browsable demo (12 leagues, honest panels, real identity) is
  the finish line the whole Stage-B plan was driving at.
```
