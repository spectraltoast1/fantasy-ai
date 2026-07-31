# V1 · P2 · Session S4a — Early-season readiness — REPORT

**Shipped:** 2026-07-31 · **Branch:** `claude/p2-s4a-early-season` · **Commits:** 3 · **Status:** DONE —
deployed and verifiable today on the demo. **Next:** load the first real 2026 league.
Brief: `SESSION_P2_S4A_EARLY_SEASON_READINESS.md`.

## Headline

The thin-data window is honest. Below three weeks of results the app states its sample and **withholds the
claims the sample can't carry**; the numbers themselves still show, flagged. At ≥3 weeks nothing changed —
that's the parity line, and it holds.

Measured on prod before: at Week 1 — **one game** — the app said **87.8%** playoff chance to a decimal,
labelled teams **"Riding luck"**, gave a magic number, and called a player's trend a confident **"Steady"**.
After: the depth note leads, the playoff % stays (rounded, flagged), and posture / magic / posture-map /
trend are absent because one game can't support them.

## Three findings that reshaped the brief

**1. The clock lied.** Every cue keyed off `asOfWeek` → `load_weeks` → `SELECT DISTINCT week FROM season`,
which counts **loaded** weeks. A projections-only week is joined with `sleeper_points` zero-*filled* rather
than null, so a league with zero games would have reported *"Early read — 1 week of data so far"*. Part 1 of
the brief was therefore not a refactor but a correctness fix.

**2. "No-crash" was a bug, not a verification.** There is no `nfl_stats_2026.parquet`, and three callers read
it unguarded, so kickoff week 2026 before nflreadpy publishes would have raised `FileNotFoundError` — before
any display honesty mattered. S2's "advances on projections-only" was documented but never exercised; its
proof was the 2025 wk4→5 advance, which had real data. S1 had already written the guard in
`compute_ros_player_band`; it just never propagated.

**3. Two of the four "silent reads" aren't what the brief described.** `bracket_odds.proj_wins` reaches no
client at all, and `regression_risk` — the one player_signal confidence the trust report grades honest —
computes to `0.0` with no realized points, which under `strength: "neg"` reads as *maximum* confidence.
Surfacing it naively early would have stated the opposite of the truth.

## What shipped

**1 · The guards** (commit `53dc7cf`). `data_layer.read_nfl_stats_or_empty` returns the season's stats or an
empty frame carrying the **real** column set (borrowed from the newest banked season — a schema-less frame
breaks the join's left-join and every downstream filter). Used by `join_nfl_sleeper_weekly` (whole-season
absence; the existing zero-fill only covered a player missing from a week) and `compute_player_signal`'s
positional baseline. `compute_production_vor`'s recent-form anchor takes the same `exists()` guard. The
`int(frame["week"].max())` casts in production_vor / player_signal / bracket_sim now `or 0` first and land in
a **named diagnosis** — `compute_bracket_sim`'s own idiom, which its existing check couldn't reach because
the cast came first.

**2 · One honest clock** (commit `be99fa9`). `load_weeks` also returns `played` — weeks where somebody
actually scored (`max(coalesce(roster_total_points,0)) > 0`). `readiness.weeksOfData(played, asOfWeek)` is
the single clock, threaded as `weeks` from `App` to all eight views; the three `Gate` call sites read it
instead of the week ordinal. Deriving depth from *points* also makes the signal immune to the
`_derive_matchup_result` tie bug. Absent data returns 0 — unknown depth is shallow, never deep.

**3 · Honest states** (commit 3). Withholding what the sample can't support, reusing the engine's **own**
thresholds rather than inventing any:
- `trustDir` → null when the engine's `low_sample` is set. `_direction` returns a confident `"steady"` at
  n<2 with no null option of its own, and it's in `NO_CONFIDENCE_FAMILIES` so nothing flagged it.
- `games` now ships — the sample as a fact. `Dossier`'s `.dos-counts` was the precedent for stating N.
- `regressionRisk` ships **only** when the sample isn't thin, for the inversion above.
- Posture chip, clinch magic number and the whole posture map gate on `hasShape(weeks)` — they compare a
  standing to an all-play record, so on one game the comparison is between two numbers that don't mean
  anything yet, and at zero games all-play is 0/0 coerced to 0, which makes "Riding luck" fall out of
  nothing. The posture map now uses `Gate` at `REGIME.TREND` — the first time that regime has ever rendered.
- `Sparkline` says **"one week"** instead of returning an empty `<svg>`; ten blank boxes read as broken.
- `read` was leaking the raw enum `too_early` at exactly the moment it fires.
- The ROS range gains an "early season: leaning on the positional baseline" caption — *provenance*, not a
  confidence chip, so it doesn't contradict S3b's deliberate refusal of one.

## Verified

- **The clock:** is_mine 2025 reports `played [1..5] == weeks`. Against a session-local shadow of `season`
  carrying a projections-only week 6, the old clock says **6** weeks of data and the new one says **5**.
  That divergence is the fix.
- **The guards, both halves:** `production_vor` and `player_signal` recompute **byte-identical** to the
  persisted 2025 frames (806 / 830 rows) — the guards are a no-op where data exists; and the 2026 path (no
  stats file at all) yields an empty-but-typed 166-column frame and an unmeasurable baseline instead of
  raising. The before-state was confirmed too: `read_nfl_stats(2026)` → `FileNotFoundError`.
- **Browser, Week 1 vs Week 5:** Week 1 — depth note, 32% shown, no posture, no magic, "one week" trend
  chips, posture map "TOO EARLY", player card TRUST `—` and "· 1 game — too thin to read a trend". Week 5 —
  posture chips back, magic numbers back, sparklines drawing, no depth note. Console clean.

## Scope held, and why

Will's rule set the boundary: **does it change measured data, or assert an unmeasured claim?** Neither → in
scope. So the defensive guards and points-based played-ness are here; two things deliberately are not:

- **The `_derive_matchup_result` tie bug** — no tie branch, so a 0-0 unplayed matchup *and* a genuine
  real-life tie both mint a phantom W/L by sort order, disagreeing with the sim's own 0.5/0.5. Changes data,
  only takes effect on a re-join, needs its own parity check. Logged in STATUS for its own session, worth
  doing before the season runs deep.
- **A low/med/high confidence tier** — asserts a confidence the engine has never measured, which is exactly
  how `ros_cv` shipped inverted. The *measured* silent-reads signal stays the post-V1 registry item; writing
  a confidence into the ledger for a `NO_CONFIDENCE_FAMILIES` read would also turn `check_registry` red.

## Notes

- **`fly deploy` shipped the API but served a stale SPA bundle.** The first deploy left prod on S3b's
  `index-Cq3iwMnP.js` while the Python changes went live — so `/api` returned the new fields and the page
  still rendered the old behaviour, which looks exactly like "the change didn't work". Caught by reading the
  served `<script src>` and recognising the hash. `fly deploy --no-cache` rebuilt stage 1 and shipped
  `index-Doimm2UB.js`. **Check the bundle hash after any deploy whose frontend changed**, and prefer
  `--no-cache` when only `frontend/src` moved.
- Also removed `Gate`'s catalog arm. No call site ever passed `panel`/`panels` — **my own S3 commit message
  claimed it "activated" that path and was wrong.** S3 actually added a parallel `marketOn`/`MarketOff`
  path. Catalog gating is per-element (a column, half a toggle), which a wrap-children component can't
  express, so `Gate` is readiness-only and the third idiom is gone.
- `matchup_win_probs` returns 50/50 whenever both σ are 0 regardless of μ, disagreeing with the sim's
  `_win_prob` (1.0/0.0). Only reachable on a week with no projections at all; logged, not fixed.
- The preseason (0-results) *rendered* state still can't be exercised end-to-end — no 0-games league exists.
  The clock returns 0 for it and the ladder's `tooEarly` branch covers it, but like S3b's band panel its
  first real render is the 2026-league load.
