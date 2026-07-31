# P2 · S3b Audit — Wire the honest band (2026-only; frozen corpus untouched)

**Reviewed:** 2026-07-30 · **By:** PM (live git + the loader/reads diffs + independent mtime/branch checks).
Commits `e3d073f` (loader, frozen-corpus-bounded), `05914f9` (API, week-pinned), `fcbcc74` (panel),
`6c02252` (cadence + redeploy + docs), doc `9d6d38c`, merge `94d0a67` on `main` — pushed. Report:
`SESSION_P2_S3B_REPORT.md`.

**Bottom line: endorse — clean, and the integrity call held.** The honest band is wired end-to-end
(load → select → render) and deployed, the weekly refresh keeps it in step with production_vor so the
CENTER_SHRINK drift can't re-open, and — the part that mattered most — the **frozen certification corpus and
its immutable ledger were verifiably not touched**. `ros_cv` was correctly left retired. The one honest
caveat is by design: it **serves 0 rows and the populated panel has never rendered from real data**, because
we chose the 2026-only path and no 2026 league exists yet. It lights up when one is loaded.

## Verified (independently, not just the report)

- **Frozen corpus untouched — the whole Q1 resolution held.** The S3b branch diff (`00a2b8a…94d0a67`)
  changed **none** of `corpus/`, the `ledger`, `_constants.py`, `compute_ros_player_band.py`, or
  `check_predictions`/`check_debias`. **Zero** files under `derived/scoring` have today's mtime. The loader
  states the boundary once — `FIRST_HONEST_BAND_SEASON = 2026`, `_honest_band_path` returns a deliberately
  absent path below it — so `load()`/`load_league()`/`verify()`/`--dry-run` all inherit "the frozen corpus
  never loads" rather than each special-casing it. Exactly the clean path we agreed.
- **`ros_cv` retired, not surfaced (Q3 fix landed).** In both `reads.py` and `PlayerCard.jsx`, `ros_cv`
  appears **only in a comment** explaining why it's omitted — the band's width is the confidence (law 2), and
  the retired-as-inverted `ros_cv` would have been the one dishonest thing on the card. The only `confidence`
  chip left on the card is the pre-existing **AI** `ros_synthesis` panel's — a different object, correctly
  untouched.
- **New table wired + parity intact.** `ros_player_band` is in `schema.sql` (CREATE at L440) + `build_db`
  DATASETS; `check_scoped_reload --prove-bites` is green across all 14 tables with **no oracle change** (it
  enumerates DATASETS). Code applied only the new table's CREATE + indexes to prod, not the whole regenerated
  `schema.sql` (which is DROP CASCADE for all tables) — so the live DB never saw a global DROP.
- **Week-pinned, demonstrated not assumed.** The band is NFL-global (as_of 1..17); it's pinned to
  `production_vor`'s `as_of_week`, not its own max. Proven against a shadow table: unpinned week-17 centre
  12.4 vs pinned 223.0 = `prod.rosPoints` for that week — the identity the panel rests on. (Code also surfaced
  `prod.rosPoints` from `production_vor.ros_value`, which was selected then dropped — making the
  band-center == production-VOR identity visible on the card.)
- **Prod after deploy:** `rosRange: null`, `rosPoints: 223.0`, the honest absent-state renders beside the AI
  panel, console clean, S3 market gating untouched.

## The honest caveat (by design, worth stating plainly)

**The populated panel has never rendered from real band data.** Code screenshotted it from a *synthetic*
stubbed payload (reverted, uncommitted, diff confirmed empty) — a **render** proof (layout, gauge geometry,
honest downside asymmetry are right), not a **data** proof. This is unavoidable under the 2026-only path:
there's no 2026 league to serve, so the wire is dark. The first session/step that loads a real 2026 league
must data-prove this panel as part of its done — logged in STATUS.

## Two expected reds (NOT regressions — measured FAIL→FAIL, pre-existing)

- `backtest_ros_player_band --season 2025` FAILs (coverage 0.468 vs 0.80) because it grades the **frozen
  pre-8c band** — which we deliberately keep as the certification baseline. This red **persists by design**;
  the honest 2026 band's calibration proof lives in the 8c tuning certification, re-runnable only via the
  annual re-tune pipeline, not from the current frozen store. Not a S3b defect.
- `check_predictions` FAILs on a pre-existing data gap (the is_mine **2024** slice is spined for the demo but
  was never backfilled into the ledger); the band-claims verdict itself passes. Unrelated to S3b.
  *(Good process note: exploration had assumed `check_debias` was already failing; Code measured and it was
  green. Measuring beat reasoning — the right instinct.)*

## Recommendation

**Endorse S3b.** The honest engine now has a true path to the screen, built without disturbing the frozen
certification record, `ros_cv` correctly retired, parity green, deployed. It is **ready but dark** — which,
with S3's market panel (contemporaneous-ready but off) and S2's weekly refresh (proven on 2025, ready for
live), means three capabilities are now queued behind the same event: **loading the first real 2026 league.**
That's the natural next milestone (Will's own league, once it drafts ~late Aug), and it's a manual admin load
— it does NOT require P5 self-serve. S4 (early-season readiness) is next; planning notes separate.
