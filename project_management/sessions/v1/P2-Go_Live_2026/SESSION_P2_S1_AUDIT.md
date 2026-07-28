# P2 · S1 Audit — Build the 2026 preseason substrate

**Reviewed:** 2026-07-28 · **By:** PM (live git + the transforms diff + an independent read of the 2026
derived parquet). Three commits (`83372ad` forward path, `6f74955` gate, `ebf2b31` docs) + merge `5600c12` on
`main` — **pushed** (in sync with origin). Report: `sessions/v1/P2-Go_Live_2026/SESSION_P2_S1_REPORT.md`.

**Bottom line: clean and genuinely thoughtful — endorse. Code didn't just "re-run the builder"; it found a
real forward-season blocker (the engine had no cross-season prior, so a season with no games collapsed to a
NaN band) and fixed it additively — pooled positional priors when actuals are absent — proven a no-op on
2020–2025, plus a proper structural gate since the actuals-based backtests can't judge a forward season. Real
2026 ADP + projections were fetched; I independently confirmed the substrate is real and sanely shaped. It's
offline (derived parquet only), so zero live-app risk. Two honest findings worth your eye, neither a blocker.
Ready for S2.**

## Verified

- **Scope safe.** Only `compute_projection_consensus.py`, `compute_ros_player_band.py`, the new
  `check_forward_substrate.py`, and docs. `build_db.py`, the served Postgres, the app, and all live-cadence
  machinery are untouched — exactly right; that's S2.
- **Real 2026 inputs, not placeholders.** The report shows 2026 ADP (378 skill players, snapshot 2026-07-24)
  and Sleeper projections (54,630 rows × 18 weeks) were fetched — the nflverse/Sleeper feeds serve 2026 when
  the season is passed explicitly (their clock still says 2025). `nfl_stats_2026` is a 404 by design (no games
  yet).
- **The forward path is sound and safe.** When a season has no `nfl_stats`, the band sources its positional
  std/skew from residuals pooled over prior seasons — so every 2026 player's band collapses to the honest
  positional prior. Strictly additive: proven a **no-op on 2020–2025 × {ppr,half}** by code-diff isolation
  (stash → recompute baseline → restore → recompute → 24/24 slices value-identical). That's the right way to
  prove "I added a forward branch without disturbing history."
- **Independently confirmed the 2026 data is real + sane** (I read the parquet myself): consensus = 7,852 rows
  across weeks 1–18, non-null centers tracking 2025 (wk-1 max 23.8 = Burrow); the band is a **single constant
  per position** (WR 6.31 / TE 5.07 / RB 6.16 / QB 7.57 — the positional prior, exactly as designed and as
  Code reported); ROS band ordering (bear ≤ center ≤ bull) holds on 100% of rows. The structure is honest
  forward-prior, not a fabricated per-player signal.
- **A proper gate for a no-actuals season.** `check_forward_substrate.py` certifies what *can* be certified
  without actuals — schema parity, coverage, finiteness/ordering, the forward invariant, prior == pooled
  history, determinism — with `--prove-bites` showing the predicates actually fail when they should. Correctly
  replaces the backtest-vs-actuals gates, which are N/A until 2026 games exist.

## Two findings worth your eye (neither blocks S1)

1. **The 2025 demo is showing the *old* band, not the honest one.** Code found the persisted 2020–2025 band
   store is **stale at the pre-honest constant** (recompute at HEAD is exactly 0.8× the stored value — the
   honest "8c" `CENTER_SHRINK` shipped in the constants but the historical bands were never rebuilt).
   **2026 is built fresh under the honest constant, so the live product is honest from day one** — but the
   multi-league 2025 replay demo currently renders the *pre-honest* band. Not a V1 blocker (V1 is live-2026),
   but if you ever show the 2025 demo as representative of the engine, its bands aren't the honest ones. The
   fix is a one-command rebuild of 2020–2025 whenever the replay needs to match; I'd log it, not rush it.
2. **The 2026 ADP board is thin right now (by design).** 378 players vs 2025's post-draft 468, with ~66
   unmatched (likely rookies not yet in the id bridge). This is exactly the "build now, refresh near drafts"
   we agreed — the near-drafts rebuild firms it up, and it's now formalized as the preseason-freeze step in
   the Season Calendar. Also note `ANCHOR_W = 0.0` ships, so the ADP anchor is **evidence-only** (doesn't move
   band values today) — which is why the thin board doesn't compromise the current substrate.

*Transparency:* the file bridge served me a **stale** `adp_preseason` snapshot (0 rows for 2026 though the
on-disk file grew by ~378 rows' worth) — the same current-mtime/stale-bytes quirk that's bitten me before. So
I couldn't independently re-confirm the 2026 ADP rows through it; I take them as banked (the report is
specific, the build succeeded, and the file size grew by the right amount), and it's not load-bearing at
`ANCHOR_W=0` regardless.

## Recommendation

**Endorse S1.** 2026 now has an honest, real, sanely-shaped basis to reason from, built without touching any
live surface. The stale-historical-band note is a product flag to log; the thin ADP is the expected
build-now/refresh-at-drafts state. **S2 is next — and it's the one to be careful with:** the weekly refresh
plus the DROP+CREATE → incremental loader change, the single riskiest change in V1. Brief attached.
