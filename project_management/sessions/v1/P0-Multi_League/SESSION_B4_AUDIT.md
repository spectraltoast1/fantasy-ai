# Stage B Audit — B4 (parameterize the reads on `league_id`)

**Reviewed:** 2026-07-26 · **By:** PM (independent — live git on `main`, the B4 code diffs, the actual
derived parquet, and the live deployed app at fantasy-ai-api.fly.dev)
**Scope:** parameterize every `/api` read on an optional `league_id` (+`season`) defaulting to the is_mine
slice; close the two B3 carry-forward items (redeploy so `GET /api/leagues` goes live; make the ROS catalog
flag honest). Three commits (`7e34232`, `f802723`, `0ce6ac0`) + merge `40d24b1` on `main`, **fully pushed**
(local == origin). Filed under the new layout at `project_management/sessions/v1/`.

**Bottom line: clean — endorse, nothing to fix. Both B3 carry-forward items are closed and I verified them
on the live app: `/api/leagues` now returns 200 (was 404) with all 12 lineages and ROS off everywhere, and
the no-params app is byte-identical to before (independently re-checked against my B3 baseline). Code also
caught a real cross-league edge case my brief didn't anticipate — a playoff-week NULL `matchup_id` that
crashed corpus leagues — and fixed it in both code paths as a genuine no-op for the is_mine slice. The
design honored every call from the brief. Next is B5.**

> One process note worth recording: the file bridge served me a **stale `demo_manifest.parquet` snapshot with
> a *current* mtime** — it read `panels_ros=true` while the live DB read false. I only trusted the fix after
> triangulating the live DB + the commit timestamp + the code. Don't trust a single staged-parquet read for a
> value that matters; confirm against the live endpoint. (Details under "Catalog honesty.")

---

## Verified clean (I read the diffs, the data, and the live app — not the report)

**Git + scope faithful.** Three B4 commits land the exact three-part split (reads / catalog honesty /
redeploy+STATUS). The three commits *after* the merge (`f64b4a6`, `50fd60e`, `806f4eb`) are the
`project_management/` reorg **only** — I confirmed they touch **zero** `application/` code, so HEAD's app
code equals the deployed B4 image (no drift). Repo is fully synced with origin.

**Reads parameterized — every endpoint, defaulting to parity.** `routes.py` adds a `slice_params`
dependency (`?league_id=` + `?season=`) to **every** read route; `/leagues` is the one deliberately unscoped
catalog read. `reads.py` threads `league_id` through every `load_*`, resolving `None → settings.league_id()`
(so a no-param call binds exactly today's league — the parity default), and the shared `_params(lid=…)` does
the same. `projections.py` threads all three win-prob functions (`target_week_for`, `team_projections`,
`team_matchup_summary`) the same way. `season` is carried and validated but **never a SQL filter** — correct,
because a redraft `league_id` already pins one `(league, season)`. This matches the brief's decisions
1–4 to the letter.

**Unknown-league guard works — on the live app.** `slice_params` validates a non-None `league_id` against
the `demo_manifest` catalog via `reads.slice_exists()` and 404s an unknown slice. I hit
`/api/standings?league_id=999999999` on the deployed app → **404**. (Note: the default is_mine path passes
`league_id=None`, so it skips the validation lookup entirely — zero added cost to today's traffic.)

**Parity re-verified independently — the no-params app is unchanged.** I re-hit
`/api/standings?as_of_week=4` (no `league_id`) on the deployed app and compared to my B3 baseline: roster 8
"Tet Lasso" / spectraltoast1, 3–1, playoffPct **87.3**, oddsSeries **[31.8, 34.6, 86.7, 87.3]**; roster 4
"Bski" playoffPct **91.1** — **byte-identical**. B4 did not disturb the is_mine league.

**Multi-league is live and scopes correctly.** `GET /api/leagues` returns **200** (was 404 at B3) with all
**12 lineages**, is_mine first, `viewer_roster_id` 8, `weeks_available` [1–4] for lorp-2025, and
`panels.ros_synthesis` **false across every entry**. `?league_id=<Trap 2025>` returns a *different* 12-team
league ("IMG Academy" / dmorg14, not your league) — so the param genuinely re-scopes the read. (First
enumeration miscounted 11; a re-read listed all 12 by name — a reminder to not trust a single summary count.)

**The edge case Code caught is real, and the fix is right.** A corpus league's "next week" (`max_played+1`)
can be a **playoff week where `schedule.matchup_id` is NULL** — the is_mine mid-season slice never reaches it,
but hitting a corpus league by param crashed the matchups + team-detail paths. The fix adds
`AND matchup_id IS NOT NULL` to the schedule reads in **both** `load_matchups` (`reads.py`) **and**
`team_matchup_summary` (`projections.py`) — so the report's "matchups/team-detail path" claim is fully
covered. It's a true **no-op for is_mine** (its only reachable target week, 5, is regular-season with real
pairings), so parity holds; corpus leagues now return the real paired games or a clean empty state instead of
crashing. Good multi-league instinct — this is exactly the kind of per-league quirk B6 exists to shake out.

**Catalog honesty — correct and reproducible (this one took work to confirm).** `build_demo_manifest.py`
sets `panels_ros=False` (decoupled from `panels_market`, which stays on for lorp-2025) — a **one-cell** flip
(lorp-2025 True→False; every other slice was already False). `build_db.py --reload-manifest` is an **atomic
TRUNCATE+COPY of just the catalog table** (data slices untouched, no DROP/CREATE) — a genuinely safe,
well-scoped production write. The live `/api/leagues` shows ROS off everywhere, so the DB is correct.
*The catch:* a staged read of `demo_manifest.parquet` showed `panels_ros=true` for lorp-2025 — but that was a
**stale bridge snapshot** (it reported the file's current mtime yet served old bytes). The on-disk mtime
(14:13:20) sits ~2.5 min *before* the honesty commit (14:15:58), i.e. the parquet was regenerated by B4; and
since `reload_manifest` loads *that* parquet and the live DB reads false, the on-disk source is false too.
Source, DB, and code all agree — the fix is honest **and** reproducible (a future reload won't revert it).

---

## Notes / expected interim states (not findings — flagged so nothing surprises us in B5/B6)

- **Corpus "me" identity is absent by design until B5.** Hitting a corpus league by param resolves "isMe" via
  `MY_USERNAME`, which matches nobody in another league → no "me" highlight, personal panels empty. That's
  the intended B4 state; the `MY_USERNAME → viewer_roster_id` swap is B5. Code correctly left viewer identity
  untouched (brief decision 3).
- **Multi-league is reachable by param but not *exposed*.** No frontend selector yet (B5), so corpus leagues
  are only testable by direct URL param, and full click-through of every league × season is B6. The one NULL
  `matchup_id` quirk that surfaced this session is a hint B6 will find more per-league edge cases — expected.
- **`season` is cosmetic** (validated, never filtered). A deliberately mismatched `?season=` is ignored (the
  `league_id` wins). Harmless for the demo — the B5 catalog always passes matching `(league_id, season)`.

---

## Recommendation

**B4 is sound — endorse it, nothing to fix.** The read parameterization is faithful and parity-preserving,
both B3 carry-forward items are closed and verified on the live app, the ROS catalog is honest, and the
cross-league edge case was caught and fixed cleanly. This is the last backend step — the API is now
multi-league-ready.

**Next: B5** — the frontend selectors (`LeagueSwitcher` → real dropdown + `SeasonSwitcher`), `viewer_roster_id`
replaces `MY_USERNAME`, and `readiness.jsx` gates panels off the `panels` map (ROS panel gates off / shows an
explicit "no outlook yet"; remove the cross-time POC copy). Fold in the tiny landing-tab change
(`App.jsx` `useState('players') → 'league'`) and refresh the two stale "only Players is wired" comments while
that file is open. B6 is the full E2E across every league × season.
