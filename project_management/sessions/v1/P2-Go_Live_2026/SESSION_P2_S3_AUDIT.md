# P2 · S3 Audit — Retire the cross-time market honestly

**Reviewed:** 2026-07-30 · **By:** PM (live git + the gate diff + an independent read of the deployed
`/api/leagues`). Commits `cc6b255` (gate + check + compute), `3b39a4e` (four frontend surfaces), `aa71911`
(redeploy + docs), doc-only `c755a42`, merge `00a2b8a` on `main` — pushed. Report: `SESSION_P2_S3_REPORT.md`.

**Bottom line: endorse — clean and honest.** Code held to the market-only scope we cut it to, gated the
cross-time market off across **all four** surfaces on the read's OWN `is_cross_time` flag (so a live 2026
league re-activates it by itself — better than the brief asked), left the store untouched (no data risk),
redeployed, and I independently confirmed **0 of all slices render the market on** the live app. The session's
real value is the finding it forced into the open — the honest band was never wired — now documented and
scoped as S3b rather than papered over.

## Verified

- **Scope held — the scary-titled commit is a false alarm.** `c755a42` ("surface the honest band and retire
  the cross-time market") touches only two doc files (the briefs) — zero code. The code commits are
  market-lane only: `reads.py` / `compute_market_vor.py` / `check_market_vor.py` (the gate) and the four
  frontend surfaces. **No `build_db.py`, no `ros_player_band`, no loader, no auth.** Exactly the cut we asked.
- **The gate is correct and self-activating.** Server: `panels.market = panels_market (structural) AND NOT
  is_cross_time`, with NULL provenance coalescing to cross-time so "unknown" never gates *on*; a slice with
  the flag but no market rows also gates off. Frontend: all four market surfaces (Players MKT column, team
  PROD/MKT toggle, player-card sparkline + BUY/SELL lean, League positional talent) hide when
  `panels.market === false`. `is_cross_time = (market_season != season)`, so 2026×2026 → false → the panels
  return by themselves. No hardcoded season anywhere.
- **Contemporaneous-ready, proven without a 2026 league.** `check_market_vor --prove-bites` shows a
  same-season frame passes as `contemporaneous`, and the predicates bite on a flipped flag / half-fused frame
  / mis-pinned mode. That's the readiness proof, and it needed no live 2026 data (there is none —
  `_active_league(2026)` raises).
- **Live-corroborated.** I read the deployed `/api/leagues`: **0 slices market-on** (every slice
  `market:false`), while the manifest's structural `panels_market` stays true — so the honesty AND is doing
  the work, not a blanket flag flip. The redeploy took.
- **No data risk by construction.** No rebuild, no reload — the store is untouched. Non-market surfaces
  (incl. Matchups' "Score Range · 25–75") unchanged; switching leagues renders normally; console clean,
  `/api` 200s.

## The visible effect (so you're not surprised)

The market / BUY–SELL surfaces are now **gone from the entire demo** — all slices, not just the is_mine one —
replaced by a "not a live read" note. The corpus leagues were cross-time too, and preseason has no
contemporaneous 2026 market, so *everything* honestly gates off. The demo now shows **production VOR only**.
That's the intended honest state; just know the demo lost a visible panel until a live 2026 league exists.

## Two honest open items Code surfaced (neither blocks S3; both logged in STATUS)

1. **`market_vor` has no refresh cadence.** Nothing recomputes it — the weekly refresh rebuilds the spine but
   not the market read — so it trails the raw LeagueLogs series and `check_market_vor`'s recompute verdict is
   RED (pre-existing). **Harmless while the panel is off**, but a real dependency for when the live 2026
   market turns on (S4): the market needs a refresh cadence tied to P1's daily LeagueLogs collection. Code
   correctly did NOT fix it here (would add a store write to a switch-off session). Logged for S4.
2. **`concurrently` devDependency was missing** from node_modules (dev-only; `dev:full` couldn't start) —
   fixed via `npm install` from the lockfile. Immaterial to prod.

## The one thing S3b MUST carry (correctness, not cleanup)

The store drift is now pinned precisely: `production_vor.ros_value` (served, honest) is exactly `0.8×` the
same-week `ros_player_band.ros_center` (stale at pre-8c `1.0`). So when S3b wires `ros_player_band`, the
rebuild-at-0.8 is **mandatory** — wiring the stale band would put a ROS-range center ~1.25× above the
production VOR already on the *same card*, a visible self-contradiction. And because the weekly refresh
advances production_vor but not the band, S3b also has to fold the band into the cadence so it stays honest
week over week. Both are in the S3b brief.

## Recommendation

**Endorse S3.** The cross-time dishonesty is retired, the gate is honest and self-activating, nothing in the
store moved, and it's verified live. The market's live quality (cadence, `MARKET_PROFILE`, week-replay) is
correctly deferred to S4. **S3b is next — the honesty payoff finally reaches the screen.** Brief attached
(`SESSION_P2_S3B_SURFACE_HONEST_BAND.md`).
