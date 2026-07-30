# V1 · P2 · Session S3b — Wire the honest band (dark until 2026) — REPORT

**Shipped:** 2026-07-30 · **Branch:** `claude/p2-s3b-honest-band` · **Commits:** 4 (cap raised for this
session) · **Status:** DONE — wire built end-to-end and deployed; **serves 0 rows by design.**
**Next:** P2/S4. Brief: `SESSION_P2_S3B_SURFACE_HONEST_BAND.md`.

## Headline

`ros_player_band` now has a path to the screen — loaded, selected, rendered — and the weekly refresh keeps
it in step with `production_vor` so the `CENTER_SHRINK` drift can't re-open. **It renders nothing today**,
on purpose: only seasons at or above `FIRST_HONEST_BAND_SEASON` (2026) may be served, and no 2026 league
exists yet. It lights up by itself when one is onboarded, with no code work at kickoff.

## The decision that shaped the session

The brief asked for a rebuild of the stale 2020–2025 band first. Exploration found that artifact does
**double duty**: it is both the substrate the app would serve *and* the frozen-corpus artifact the
**immutable L2 predictions ledger** was derived from — `check_predictions` §5 rebuilds band claims from it
and compares them to the ledger, and `constants_snapshot.frozen_era()` reverts constants but **not data**.
Rebuilding at the honest constants would have broken the ledger's reproducibility.

**Will's call: don't rebuild.** The frozen seasons keep the pre-8c band as the out-of-sample certification
baseline; a corpus re-backfill stays the annual pipeline's job. Only the honest 2026 substrate is served.
The accepted consequence — the panel is dark until a 2026 league lands — was taken knowingly over the two
alternatives (rebuild behind an epoch seam, or defer the whole session).

## What shipped

**1 · The loader, bounded by one named line** (`build_db.py`, commit `e3d073f`). `FIRST_HONEST_BAND_SEASON
= 2026` states the boundary once; `_honest_band_path` returns a deliberately-absent path below it, so the
existing skip-if-absent in `load()`/`load_league()`, `verify()`'s disk expectation and `--dry-run`'s plan
all inherit the rule rather than each special-casing it. `_band_ref_path` supplies `--emit`'s DDL from the
2026 file — the same decoupling `_ros_ref_path` already uses for `ros_synthesis` ("its file lives at a
season no slice has"). Applied **only this table's** CREATE + indexes to prod rather than the regenerated
`schema.sql` whole (it is `DROP TABLE … CASCADE` for all 14), so the live demo never saw a global DROP.

**2 · The API, pinned to the league's clock** (`reads.py`, commit `05914f9`). `load_player_card` returns
`rosRange` beside the existing `ros` block. The band is pinned to `production_vor`'s `as_of_week`, not its
own `max` — the band is NFL-global and runs the whole projected season (1..17) while `production_vor` stops
at the league's played weeks. Also surfaces `prod.rosPoints` from `production_vor.ros_value`, which was
selected into two CTEs and dropped — dead in both API and frontend. It is the same number as
`rosRange.center` by construction (the band imports `_ros_values` rather than re-deriving it), so surfacing
it makes that identity visible on the card instead of only provable in the data.

**3 · The panel** (`PlayerCard.jsx`, commit `fcbcc74`). Bear / center / bull tiles, a full-width
`RangeGauge` (whose CSS already lived in the player-card block), and the ±σ spread. **No confidence chip:**
the width *is* the confidence (law 2's wording), and the `ros_cv` the brief specified was measured
**INVERTED** in S5 and retired to an audit column in 8c — shipping it would have been the one dishonest
thing in an honesty session. Gauge domain starts at 0 because 0 is a real floor, so the tick's height reads
as "how much of the range is downside" — the 8c shape, not an artifact.

**4 · The cadence, guarded** (`weekly_refresh.py`, commit 4). A band rebuild between JOIN and SPINE, so it
advances *with* `production_vor` instead of freezing behind it. Placed in `refresh_league`, not
`compute_spine._compute_league` — that contract is league-keyed, and an NFL-global write there would fire
31 times to produce 12 files on a demo batch (221 on the corpus path). Runs unconditionally within the
guard: it is ~0.2 s and a byte-identical no-op when nothing moved (`FORM_ANCHOR_W=0` makes `recent_form` an
identity), and an existence check would be useless because `ros_player_band_exists` returns True for a
*stale* file — exactly the drift to catch.

## Verified

- **The frozen corpus was not touched.** The guard returns an absent path for all 12 frozen (season, key)
  pairs and the real file for 2026; a spy on the writer shows 2020/2023/2025 attempt **zero** band writes
  and 2026/2027 attempt one; a real `weekly_refresh --season 2025 --week 5` prints *"season 2025 < 2026 —
  frozen-corpus band left untouched"*. **0 of 62 band parquet mtimes changed**, and nothing under
  `derived/scoring` was modified all session.
- **Gate baseline, measured before and after** — identical verdicts on all four:
  `check_forward_substrate` PASS→PASS, `check_debias` PASS→PASS, `check_predictions` FAIL→FAIL (pre-existing:
  the is_mine **2024** slice is spined for the demo but was never backfilled into the ledger — the band-claims
  verdict itself passes, and keeps passing), `backtest_ros_player_band --season 2025` FAIL→FAIL (pre-existing:
  it grades the frozen pre-8c band, coverage 0.468 vs 0.80). *Worth noting: exploration asserted
  `check_debias` was already failing; measuring showed it green. The plan called for measuring rather than
  reasoning, and that was the right call.*
- **Loader:** `--dry-run` plans 0 slices for the band; the `--emit` diff is exactly the new table + 3
  indexes; `--verify` reconciles 0 vs 0; `check_scoped_reload --prove-bites` green — *"parity holds across
  all 14 tables"* — with **no oracle change**, since it enumerates `DATASETS`.
- **The pin, demonstrated not assumed.** Against a session-local shadow table (nothing written to prod):
  unpinned returns a week-17 centre of **12.4**; pinned returns **223.0** — exactly `prod.rosPoints` for
  that week. That is the identity the panel rests on.
- **Prod after deploy:** `rosRange: null`, `rosPoints: 223.0`, the honest absent-state renders beside the AI
  panel, console clean, and the S3 market gating is untouched.

## The one thing that is NOT proven

**The populated panel has never rendered from real band data.** It was screenshotted from a synthetic
payload stubbed into the *local* API process (centre 223.0, bear 136.6, bull 241.1 — reverted, not
committed, and the reverted diff was confirmed empty before the commit). That is a **render** proof: it
shows the layout, the gauge geometry and the honest asymmetry are right. It is **not** a data proof. The
session that loads the first 2026 league should verify this panel against live band data as part of its own
definition of done — it is logged in STATUS.

## Notes for the next session

- `FIRST_HONEST_BAND_SEASON` is the single place the frozen boundary lives. Lowering it is a corpus
  re-backfill: re-run the band under live constants, re-derive the ledger's band claims as a
  **new-`code_version` parallel population** (the ledger is append-only-of-new and already supports this),
  then lower the constant.
- **Worktree preview gotcha, sharper than recorded:** the preview tool resolves `.claude/launch.json` from
  the *main* checkout, and `npm --prefix` does **not** change a script's cwd — so both vite and uvicorn ran
  from main and served main's code. Fix that worked: point main's (gitignored) `launch.json` at the worktree
  via `/bin/sh -c "cd <worktree>/application/frontend && exec npm run dev:full"`, then restore it. Restored.
- `check_forward_substrate`'s output differs run-to-run in one printed block — `compute_projection_consensus`
  prints an **unsorted `.head(8)`** sample (`:323`), so which rows appear varies. Cosmetic; every verdict
  line and the exit code are stable.
