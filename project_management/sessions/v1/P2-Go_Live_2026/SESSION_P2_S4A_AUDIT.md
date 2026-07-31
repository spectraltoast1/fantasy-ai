# P2 · S4a Audit — Early-season readiness (the honest thin-data window)

**Reviewed:** 2026-07-31 · **By:** PM (live git + the reads/transforms diffs + independent defensive-guard &
push checks). Commits `53dc7cf` (no-crash guard), `be99fa9` (results-based clock), `4dd9134` (state sample /
withhold claims), doc `7e5ec1b`, merge `67ba230` on `main`. Report: `SESSION_P2_S4A_REPORT.md`.

**Bottom line: endorse — a clean, honest session that also fixed two real bugs my brief mis-scoped.** The
thin-data window now tells the truth: one results-based depth clock, claims withheld below the sample that can
carry them, numbers still shown but flagged. The three answers we gave held — played-ness from points (Q1),
the no-crash guard as a sanctioned defensive change (Q2), data-depth honesty with no invented tier (Q3) — and
Code caught that two of the four "silent reads" I named weren't as I described, shipping the treatment only
where it isn't backwards. **Pushed and in sync with origin** (the report's "4 ahead" was a point-in-time
snapshot). One honest caveat, by design: the preseason (0-games) *rendered* state is still unproven — no
0-games league exists yet.

## Verified (independently)

- **The clock now counts results, not loaded weeks (Q1 landed).** `load_weeks` returns both `weeks` (loaded)
  and `played` — `played` counts a week only if `max(coalesce(roster_total_points,0)) > 0`. A projections-only
  week is zero-*filled* (not null), which is exactly why the old `DISTINCT week` clock lied "1 week of data"
  for a zero-game league. Proven against a shadow projections-only week 6: old clock 6, new 5. Serve-side, no
  data change.
- **The no-crash guard is genuinely defensive — no-op on populated data (Q2 landed, correctly).** The
  `_nfl_stats_path(season).exists()` predicate is homed once in `data_layer` (better than my "copy to three
  callers"); `compute_production_vor` skips `realized_pts` when absent (→ identity, the S1 pattern), declares
  a **typed empty frame** so a no-rows preseason league doesn't `ColumnNotFoundError` downstream, and replaces
  a cryptic `int(None)` with `max() or 0` + a **named** RuntimeError diagnosing the degenerate case. Every one
  of these is inert when the stats file exists — the "Week 5 nothing changed" parity line, confirmed by the
  diff being absent-data-only.
- **Silent-reads honesty, shipped only where not backwards (Q3 landed).** `regression_risk` is nulled when
  `thin` — because with no realized points it computes to 0.0, which under `strength:"neg"` would read as
  *maximum* confidence. `bracket_odds.proj_wins` turned out to reach no client at all (a non-issue, not a
  silent read). No low/med/high tier was invented; the real measured-confidence work stayed logged as the
  post-V1 engine item. Exactly the ros_cv discipline.
- **Scope held.** Display (`reads` + frontend) + the sanctioned `data_layer` guard and its callers. No
  `build_db`/loader, no market change, no auth, no band constants. The tie bug and any confidence tier stayed
  out and are logged in STATUS with their reasons — including that the depth clock reads points, not W/L, so
  it's unaffected by the tie bug.

## Two honest flags

- **The preseason (0-games) rendered state is unproven** — the clock returns 0 and the ladder covers it, but,
  like S3b's band panel, its first real render is the 2026-league load. **One specific thing to watch at that
  load:** a freshly-drafted preseason league must flow through the new guards *without* tripping the
  `max_roster_week < 1` RuntimeError (it shouldn't — projections weeks create joined weeks — but that's the
  edge to confirm on the day). Logged in STATUS as owed verification.
- **Deploy gotcha worth putting in the runbook:** the first `fly deploy` shipped the API but served a **stale
  SPA bundle** (prod kept S3b's `index-*.js`), so the page rendered old behavior while the API returned new
  fields — it looks *exactly* like a broken change. Caught by reading the served script hash; `--no-cache`
  fixed it. Check the served hash after any frontend deploy. (Note for our own method: this is why we verify
  against the API/code, not the rendered page — a stale bundle would have mid-led an eyeball audit.)

## Where this leaves us

**This functionally closes P2 (Go-Live 2026).** S1 (substrate) → S2 (weekly refresh + scoped loader) → S3
(retire cross-time market) → S3b (wire honest band) → S4a (early-season readiness) are all in and deployed.
Everything is *built* for live 2026; three things are **ready but dark**, all queued behind the first 2026
league load (Gate A, ~late Aug): the ROS band panel's real render, S4a's preseason regime, and — deferred
post-launch — S4b (turn the live market on). **Next:** start P5 (auth + self-serve onboarding + the cloud/Fly
refactor) building against replay during the preseason runway, and load Will's league at the draft to
data-prove the dark work.
