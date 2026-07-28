# V1 · P2 · Session S1 — Build the 2026 preseason substrate — REPORT

**Shipped:** 2026-07-28 · **Branch:** `claude/p2-project-kickoff-a460a7` · **Commits:** 2 code (+ offline
data build) · **Status:** DONE — offline, zero production surface touched. **Next:** P2/S2 (weekly
refresh + incremental loader). Brief: `SESSION_P2_S1_BUILD_2026_SUBSTRATE.md`.

## What shipped
The engine now has a **2026 basis to reason from.** Banked the 2026 preseason inputs and ran the
`build_substrate` chain for season 2026 on **ppr + half**, producing `projection_consensus_2026` +
`ros_player_band_2026` under the current honest constants. Offline / derived-parquet only — `build_db.py`,
the served Postgres, the app, and all live-cadence machinery untouched (that's S2). Nothing a user sees
changed yet.

## The real work: a forward-season path (S1 was NOT just "re-run the builder")
The brief framed S1 as running existing builders. Exploration found a genuine blocker: a *forward*
season with no games has no actuals, and `compute_projection_consensus` sourced its **positional
residual prior from the target season's own actuals** (`read_nfl_stats(season)`), with **no cross-season
prior anywhere**. For 2026 that path raises `FileNotFoundError` / collapses to a NaN band.

**Fix (commit `83372ad`, strictly additive):**
- `compute_projection_consensus.py` — when `_nfl_stats_path(season)` is absent, source the positional
  std/skew priors from residuals **pooled over prior seasons `[2020, season)`** (scoring-key-scoped,
  equal-weighted) via a new `_pooled_residuals` helper; the per-player history stays on the (empty)
  `matched` frame, so every player takes the `<2-residual` fallback → the whole band collapses to the
  honest positional prior. `_read_actuals` factored out so target + pool share one expression.
- `compute_ros_player_band.py` — guard the eager `realized_pts` read (S7 de-bias input) behind the same
  predicate; `None` → `recent_form=None` → identity, exactly the shipped `FORM_ANCHOR_W=0.0` behaviour.

**Parity — proven a no-op on 2020–2025** (both consensus and band) via **code-diff isolation**: git-stash
the two edits → recompute the 2020–2025 × {ppr,half} matrix (baseline) → restore → recompute (changed) →
`assert_frame_equal(check_row_order=False)`. 24/24 slices value-identical.

## Steps
- **Step 0 — inputs banked.** `fetchers.adp backfill 2026` → 2026 ADP board (378 skill players, snapshot
  `2026-07-24`, clears the 150-player gate). `fetchers.sleeper projections 2026` → `projections_2026`
  (54,630 rows × 18 weeks). `nfl_stats_2026` is a 404 by design (no games). Note `nflreadpy
  .get_current_season()` returns 2025 (real-world clock), but passing `2026` explicitly bypasses it and
  the nflverse rankings/projections feeds *do* serve 2026 (scrape dates to `2026-07-24`).
- **Step 1 — built.** `compute_adp_points_curve --holdout 2026` (full-history anchor, 240 rows, no
  leakage — 2026 auto-excludes for lacking actuals) + `build_substrate --seasons 2026 --scoring-keys ppr
  half` → four derived parquet. 462 players.
- **Step 2 — gated (commit `6f74955`).** New `check_forward_substrate.py` (structural, since `backtest_*`
  grade against absent actuals): schema==2025, coverage, non-null/ordered/floored/finite, the **forward
  invariant** (`n_resid==0`, `band_ppr==resid_std_pos` = one constant per position), prior==pooled
  2020–2025 std, anchor honesty, determinism, consensus historical parity. `--prove-bites` green.

## Findings / flags for later
- **The persisted 2020–2025 substrate *band* store is STALE at pre-8c `CENTER_SHRINK=1.0`.** Recompute at
  HEAD is exactly 0.8× the stored `ros_center` — the honest 8c constant shipped but the substrate band was
  never rebuilt (matches STATUS: "honest band live in constants, not yet surfaced"). **2026 was built
  fresh under the honest `0.8`, so it is honest from day one**; the historical replay bands remain stale
  (accepted — V1 is live-2026). If/when the 2025 replay must show the honest band, rebuild 2020–2025.
- **`ANCHOR_W = 0.0`** ships → the ADP anchor curve is **evidence-only** (populates
  `anchor_floor`/`anchor_ceiling` for schema parity but `anchor_applied=False` for all). `holdout_2026`
  was built for evidence-column consistency + future-promotion symmetry, not because it moves values.
- **Planned near-drafts refresh (feature, not rework).** The 2026 July ADP board is thin (378 vs 2025's
  post-draft 468; 66 unmatched, likely rookies not yet in the id bridge). Re-running the *same* commands
  on the post-draft board (late Aug) firms it up — a free refresh (Will confirmed build-now + refresh).

## Eyeball (sanity)
2026 wk-1 ppr centers track 2025: Burrow 23.8 (vs 22.9), Gibbs 20.6 (vs 19.0), Chase 19.6 (vs 20.4);
`band_ppr` constant per position (QB 7.57 / RB 6.16 / WR 6.31 / TE 5.07) ≈ 2025 single-season prior. ROS
band honestly asymmetric (Allen: bear 227 / center 303 / bull 319).

## Handoff to S2
The offline half is done; 2026 has a basis to refresh *onto*. S2 builds the live cadence — the per-league
weekly refresh + the DROP+CREATE → incremental loader change (the single riskiest V1 change, with its own
byte-parity guard).
