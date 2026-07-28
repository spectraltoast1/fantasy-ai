# V1 · Project 2 · Session S1 — Build the 2026 preseason substrate — a brief for Code

**Last reviewed:** 2026-07-28 · **Status:** Ready to run (offline — touches no live surface) · **Owner:** Code
drives; Will confirms the timing fork. **Project:** `projects/v1/P2_GO_LIVE_2026.md` (S1 of 4 — the foundation
the rest of P2 sits on). **First session of P2, the un-freeze.**

> **What this session does:** give the engine a **2026 basis to reason from.** Today the served data is a
> 2025-Week-4 replay and there is **no 2026 substrate at all**. This session fetches the 2026 preseason inputs
> and runs the *existing* `build_substrate` chain for **season 2026** on **ppr + half**, producing the
> forward-prior reads (`projection_consensus` + `ros_player_band`) under the current honest constants. It's
> **offline and deterministic** — derived parquet only, exactly like the Stage-B B2 compute session. It does
> **not** touch the app, the served Postgres, or the loader (that's S2's weekly-refresh work). Nothing a user
> sees changes yet. `P2_GO_LIVE_2026.md` S1.

## The reality that shapes this session (read first)
Two things make a **forward** season different from the 2020–2025 backfill the builder was written for:
1. **The 2026 inputs aren't banked yet.** The store's `adp_preseason` (and the projection inputs) run only
   **through 2025** — I checked. They exist upstream (it's mid-preseason) but must be **fetched first**. So
   step 0 of this session is banking the 2026 preseason ADP + projections, then building on them.
2. **There are no 2026 actuals yet.** The band's residual width is normally learned from realized
   `actual − projection`; with zero 2026 games played it **leans entirely on the positional prior** (this is
   the builder's existing early-season behavior — honest, not a bug: 2026 bands will be wide and
   position-typical, sharpening once games are played in S2's weekly refresh). And the `backtest_*` gates
   grade against actuals — which **don't exist for 2026** — so the gate here is a **structural / sanity**
   check (a real 2026 player resolves a sane center + band; the distributions track the historical shape),
   **not** a backtest score.

## Your part, Will (~2 min — one fork)
One call: the **timing** of this build (below). Otherwise it runs offline and there's nothing to eyeball on
the live site — the "looks right" is a green build + a couple of 2026 players resolving sane bands, which I'll
verify in the audit.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Build now — and plan one cheap refresh near drafts (the timing fork).** Preseason ADP and projections in
   late July are **early** and will move as drafts happen (late August). Two honest options: (a) wait until
   post-draft to build once on final numbers, or (b) **build now** on current preseason data — proving the
   whole season-2026 path end-to-end and giving an early basis — then **re-run the same one command near
   drafts** when the inputs firm up. **Recommend (b):** it de-risks the pipeline now (while there's runway)
   and the refresh is free (same builder, new data). *(Recommend: build now, refresh at drafts.)*
2. **Forward-season anchor = full history, not a leave-one-out holdout.** The band's `adp_points_curve` anchor
   used per-season **holdout** curves (fit excluding season S) to avoid leakage when *grading* historical
   seasons. 2026 has nothing to leave out, so its anchor should be fit on **all** available history
   (2020–2025). Confirm `build_substrate`/`compute_ros_player_band` resolve a forward season to the
   full-history curve (or adapt them to) — don't accidentally require a `holdout_2026` that can't exist.
3. **Superflex is covered at the substrate level — nothing extra here.** The substrate is **scoring-scoped**
   (ppr/half); superflex is a roster *shape*, not a scoring change, so the scoring-scoped consensus + band
   already serve SF leagues. The one SF-specific caveat (the market-VOR QB pool) lives downstream in the
   market read, not the substrate — out of scope for S1.
4. **Scope guard — offline compute only.** Produce derived parquet under `derived/scoring/{ppr,half}/` (and
   the `adp_points_curve`/inputs it needs). Do **NOT** touch `build_db.py`/the served Postgres, the app, or
   any live-cadence machinery — the incremental loader + weekly refresh are **S2**. Zero production risk this
   session.

## The brief to paste to Code

```
Goal: V1 Project 2, Session S1 (projects/v1/P2_GO_LIVE_2026.md) — build the 2026 preseason substrate (ppr +
half) by fetching the 2026 preseason inputs and running the existing build_substrate chain for season 2026.
Offline / derived-parquet only — do NOT touch build_db.py, the served Postgres, the app, or any live-cadence
machinery (that's S2). Analogous to the Stage-B B2 compute session.

Step 0 — bank the 2026 preseason inputs (they stop at 2025 today):
- Fetch 2026 preseason ADP (fetchers/adp.py for 2026) and the 2026 projection inputs the consensus reads
  (Sleeper/nflreadpy on-demand pulls, per the collection architecture — these are re-fetchable, not the P1
  banked dailies). CONFIRM the sources actually serve 2026 preseason data; if a source lags, bank what's
  available and note the gap. Land them in the same snapshots tree the builder reads.

Step 1 — run the substrate for 2026:
- python -m application.data.transforms.build_substrate --seasons 2026 --scoring-keys ppr half
  → compute_projection_consensus + compute_ros_player_band for {ppr,half} × 2026.
- Forward-season handling: the adp_points_curve anchor for 2026 uses FULL history (2020-2025), NOT a
  holdout_2026 (nothing to leave out). Ensure the chain resolves a forward season correctly (adapt if it
  assumes a per-season holdout). With no 2026 actuals, the band leans on the positional prior — expected.

Step 2 — gate (sanity, not backtest-vs-actuals):
- The backtest_* checks grade against actuals, which 2026 lacks. Instead verify STRUCTURE: derived/scoring/
  {ppr,half}/projection_consensus_2026.parquet + ros_player_band_2026.parquet exist and are well-formed; a
  handful of real 2026 players (e.g. a top RB/WR/QB) resolve a sane center + a plausible, position-typical
  band; no nulls/blowups; distributions track the 2020-2025 shape. Run any backtest_* that CAN run
  structurally (schema/coverage) and note which are N/A until 2026 games exist.

Follow SESSION_GUIDE: fresh worktree, worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge, push.
Suggested commits: (1) fetch/bank 2026 preseason ADP + projections; (2) build_substrate 2026 (ppr+half) +
any forward-season handling; (3) structural gate results + STATUS. Show me: the build log, and a few 2026
players' resolved center+band vs a 2025 comparison, so we can eyeball that the forward prior is sane.

Close: update STATUS.md (P2/S1 done: 2026 preseason substrate built for ppr+half, forward-prior/positional
band, structural gates pass; note a planned refresh near drafts; next = P2/S2 weekly refresh). Merge/push.
```

## Definition of done (S1)
✅ 2026 preseason ADP + projection inputs are banked; `derived/scoring/{ppr,half}/` has 2026
`projection_consensus` + `ros_player_band` built under the current honest constants; the forward-season anchor
uses full history (no phantom `holdout_2026`); a few real 2026 players resolve sane center + position-typical
bands; structural/sanity gates pass (backtest-vs-actuals correctly deferred until 2026 games exist); nothing
outside the derived store touched. STATUS updated with the planned near-drafts refresh; P2/S2 next.

## Notes / gotchas
- **This is a data-basis build, not a live change.** Like B2, it produces derived parquet and touches no
  production surface — so it's low-risk and can run fully in parallel with the P1 soak. The *visible*
  un-freeze (weekly refresh + loader change) is S2, the riskiest session of V1 — keep this one clean and
  contained so S2 starts from a solid basis.
- **2026 bands will look "prior-shaped" (wide, position-typical) — that's correct.** With no games played, the
  honest preseason band *is* mostly the positional prior; it sharpens per-player as 2026 weeks land. Don't let
  the sanity check mistake honest preseason width for a bug.
- **Refresh cadence is a feature, not rework.** Building now proves the path; re-running near drafts on final
  ADP/projections is the same one command. Note the intended refresh in STATUS so it isn't forgotten.
- **Source-lag fallback:** if a 2026 projection or ADP source isn't serving yet, bank what exists, build on
  it, and flag the thinness — don't block the whole session on one lagging feed (the near-drafts refresh
  catches it up).
- **Handoff to S2:** the substrate is the *offline* half; S2 builds the *live cadence* — the per-league weekly
  refresh + the incremental loader change (the DROP+CREATE → incremental move, the single riskiest change in
  V1, with its own byte-parity guard). S1 just makes sure 2026 has a basis to refresh *onto*.
```
