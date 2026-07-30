# V1 · Project 2 · Session S3 — Surface the honest band + retire the cross-time market — a brief for Code

**Last reviewed:** 2026-07-28 · **Status:** Ready to run · **Owner:** Code drives; Will confirms the two forks
+ eyeballs the honest band on the live demo. **Project:** `projects/v1/P2_GO_LIVE_2026.md` (S3 of 4). **The
"what the user sees is true" session — the payoff of the honest-engine work.**

> **What this session does:** make the app *show* the honest engine. Two parts: (1) **surface the honest
> band** — the honest (8c: lower center, wider two-sided) confidence band is live in the engine's constants
> and baked into the 2026 substrate, but the app still renders the **stale pre-honest band** because the stored
> historical band was never rebuilt (the S1 finding). Rebuild it and reload so the app renders the honest band
> — verifiable *now* on the 2025 demo. (2) **Retire the cross-time market honestly** — the market read is still
> a cross-time POC (2025 production × 2026 prices, `is_cross_time=true`); make the read contemporaneous-ready
> for a live 2026 league and stop showing a cross-time number as if it were a live call. `P2_GO_LIVE_2026.md` S3.

> **Preseason reality (shapes scope):** a *fully live* 2026 market read needs 2026 production, which needs a
> 2026 league loaded — and 2026 hasn't drafted yet. So S3 banks the **honest band** (fully doable + verifiable
> now) and makes the **market read honest** (contemporaneous-ready + no misleading cross-time display);
> turning the live-2026 market panel *on* in-app happens once a 2026 league is live (S4/later).

## Your part, Will (~5 min — two forks + the eyeball)
Two calls below (I recommend both). Then the check that matters: on the live demo, a player's confidence band
should visibly widen/lower to the honest one, and the market panel should no longer present a cross-time number
as a live read.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Rebuild the historical band under the honest constants + reload (recommended — this IS "surface the
   honest band").** The stored 2020–2025 `ros_player_band` / consensus band is stale at the pre-8c constant
   (S1: HEAD recompute is exactly 0.8× the stored center). Re-run the substrate band build for 2020–2025 under
   the current honest constants and reload the demo, so the app renders the honest band everywhere — the 2026
   substrate is already honest, so this makes the **demo** honest too and removes the inconsistency. Verify the
   display path carries the **stored** honest band end-to-end (API → frontend) and doesn't re-derive/narrow it
   client-side. *(This is a deliberate, honest data change — the band gets wider/lower on purpose; every other
   surface stays identical, that's the parity line.)*
2. **Gate the demo's cross-time market panel OFF — never show cross-time as a live call (recommended).** The
   lorp-2025 demo's market is cross-time (2025 production × 2026 prices); B5 removed the POC *caption* but the
   underlying number is still cross-time. Per the locked policy ("never show the old cross-time POC; gate the
   panel unless there's a trustworthy live read"), gate the market panel **off** wherever the read is
   cross-time, so the demo stops presenting a cross-time value as first-class. Keep `compute_market_vor`'s
   `is_cross_time` flag as the gate signal. *(For a live 2026 league — 2026 production × 2026 market —
   `is_cross_time=false`, and the panel turns on, gated additionally on the P1 collection being trustworthy.)*
3. **Make the market read contemporaneous-ready, don't fake it live now.** Confirm `compute_market_vor`
   produces a non-cross-time read when production and market are the same season (2026 × 2026) — i.e. the code
   path is ready — without inventing a live 2026 market panel in preseason. The live panel turns on when a 2026
   league is loaded (S4/later); S3 just ensures it'll be honest when it does and isn't dishonest now.
4. **Scope guard.** Touches: the substrate band rebuild (existing builders) + a reload (the S2 per-league
   scoped reload or full `--load`, run **locally** — no cloud execution needed), `compute_market_vor` (the
   contemporaneous/flag path), and the frontend (band display verification + the market-panel gate) → a
   **redeploy** to surface the frontend change (like B4/B5). Does **not** touch the loader mechanics (S2 done),
   auth (P5), or the cloud-execution work (deferred). Fly secrets unchanged.

## The brief to paste to Code

```
Goal: V1 Project 2, Session S3 (projects/v1/P2_GO_LIVE_2026.md) — surface the honest engine in the app.
(1) Rebuild the stale historical confidence band under the honest (8c) constants + reload so the app renders
the honest band (the 2026 substrate is already honest; this makes the 2025 demo honest too). (2) Retire the
cross-time market honestly: gate the market panel off wherever is_cross_time=true (never show cross-time as a
live call), and confirm compute_market_vor yields a non-cross-time read for a same-season (2026×2026) league.
Runs locally (no cloud execution). Redeploy to surface the frontend change.

Part 1 — surface the honest band:
- Rebuild ros_player_band (+ the consensus band) for 2020-2025 x {ppr,half} under the current honest constants
  (the persisted store is stale at pre-8c CENTER_SHRINK — S1 finding: HEAD recompute == 0.8x stored center).
  Determinism-check recompute==intended. Reload the demo (S2 scoped reload per league, or full --load).
- Verify the DISPLAY PATH renders the stored honest band end-to-end (API reads.py -> frontend PlayerCard /
  wherever the band/sigma is shown); ensure the frontend uses the stored band, not a re-derived/old-width one.
  On the live demo, a player's band should visibly widen/lower to the honest one.

Part 2 — retire the cross-time market honestly:
- Gate the market panel OFF wherever the read is cross-time (is_cross_time=true) — the lorp-2025 demo included
  — so no cross-time number renders as a live call. Use is_cross_time as the gate signal (readiness/panels).
- Confirm compute_market_vor produces is_cross_time=false when production season == market season (2026x2026);
  don't fabricate a live 2026 market panel now (needs a 2026 league loaded — S4/later). Just make it honest:
  off when cross-time, ready to turn on when contemporaneous + the P1 collection is trustworthy.

Parity line: only the confidence band (intentionally, to the honest values) and the market panel's gating
change. Standings/matchups/players otherwise identical on the demo.

Follow SESSION_GUIDE: fresh worktree, worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge, push.
Suggested commits: (1) rebuild historical honest band + determinism check + reload; (2) market panel honest
gating (off when cross-time) + compute_market_vor contemporaneous-ready; (3) redeploy + live verify (honest
band renders; no cross-time-as-live) + STATUS. Show me: a player's band before/after (wider/lower = honest),
and the market panel gated off on the cross-time demo.

Close: update STATUS.md (P2/S3 done: honest band surfaced app-wide incl. the demo; cross-time market retired /
gated off, contemporaneous-ready for live 2026; live 2026 market panel turns on when a 2026 league is loaded;
next = P2/S4 early-season readiness). Merge/push.
```

## Definition of done (S3)
✅ The app renders the **honest (8c) confidence band** — the historical band store rebuilt under the current
constants + reloaded, verified on the live demo (band visibly honest; display path carries the stored band,
not a re-derived one). The **cross-time market is retired honestly**: the panel gates **off** wherever the read
is cross-time (no cross-time value shown as a live call), and `compute_market_vor` yields a non-cross-time read
for a same-season league (ready for live 2026). Only the band + market gating change on the demo; everything
else identical. Redeployed + verified live. STATUS updated, S4 next.

## Notes / gotchas
- **This is the honesty payoff — verify it by eye.** The whole engine was tuned to be honest (wider/lower);
  S3 is where that finally reaches the screen. The before/after on a player's band is the proof.
- **Runs locally — no cloud-execution dependency.** The rebuild + reload run where the store lives (like S1),
  writing to prod Postgres; the deferred cloud refactor doesn't block this.
- **Don't fake a live 2026 market in preseason.** There's no 2026 league loaded yet, so a "live 2026 market
  panel" has nothing to show. S3's honest move is to *stop showing cross-time as live* and make the read
  ready; turning the panel on is a live-2026 step (S4/later).
- **The market's live quality still depends on P1.** When the live 2026 panel does turn on, gate it on the P1
  collection being trustworthy (the soak) + data freshness — a live trade lean is only as good as the daily
  market collection under it.
- **Handoff to S4:** early-season readiness — how Weeks 0–3 of a live 2026 league degrade gracefully (the
  "too early" regimes), and where the live 2026 market panel turns on once a league is loaded.
```
