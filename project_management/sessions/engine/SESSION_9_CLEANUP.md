# Session 9 — Cleanup Pass: pay down the parking lot

**Hand this file to Claude Code as the session brief.**

**Type:** cleanup / correctness paydown — batch the accumulated loose threads, then triage what remains · **Commits:** 3
**Reads first:** `CLAUDE.md` · `SESSION_5_L3_SCORER.md` (the naive baselines + the Trust Report this corrects) · the 6b / 7 re-score proposals (where the two correctness threads were surfaced)
**Prior:** Session 8c shipped the honest engine (center 0.8×, two-sided band). This clears the measurement-layer debt that ride-along'd the calibration work.
**Two kinds of change, kept separate:** **(A) correctness fixes** that change displayed numbers *by design* (bounded + explained + twice-run-identical) and **(B) pure cleanups** that move **no** live number. Do not mix them in a commit.

---

## Why this exists

The engine-improvement sessions surfaced real issues that were correctly deferred rather than papered over — a leaky measurement baseline, a scoring-basis mismatch, and a handful of naming/stale-comment warts. None blocked the calibration work, but they're genuine correctness debt in the measurement layer, and the honest move is to clear them in one bounded pass before the live track leans on these numbers. This session fixes the known items, sweeps for anything else the code has flagged, and hands back a triaged list of what still needs its own session.

### The known items (verified in-code)

- **Leaky Session-5 naive.** The scorer's `production_vor` naive (`recent_ppg_forward` in `scorecard_registry`) multiplies recent ppg by the **realized** forward-week count — hindsight a leak-safe forecast can't use. It made "`production_vor` loses to recent form every season" too harsh. Fix: use the **scheduled** remaining-week count; re-score; the `production_vor` skill in the Trust Report will soften (expect the "loses every season" narrative to weaken).
- **Raw-PPR grading basis.** `backtest_production_vor`, `backtest_ros_player_band._actual_weekly`, and `compute_player_signal` grade realized points against raw `nfl_stats.fantasy_points_ppr` — a fixed-PPR yardstick that mis-scores non-PPR corpus keys by up to ~7 pts/wk. Switch these to the **canonical** per-key answer key (`player_weekly_pts_canonical`). **No live number moves for is_mine** (it's PPR); the fix corrects non-PPR corpus grades.
- **The `*_ppr` naming wart** (`compute_projection_consensus` + others): columns suffixed `_ppr` now hold league points — a rename deferred. Pure rename; prove value-identical.
- **The two-way duplicate-rows bug** `check_debias` caught in the S7 blend: confirm it doesn't survive in other consumers of the two-way stat path.
- **Stale latent comments** (e.g. `sleeper.py` "follow-up when a real division league lands", the `compute_bracket_sim` "latent fixed here" notes): verify each is resolved and remove the stale marker.

---

## Commit 1 — Correctness fixes (type A: change numbers by design, bounded + explained)

- **Fix the leaky naive** → scheduled remaining weeks; re-score `production_vor` skill; update the Trust Report narrative. **Name exactly what moves** (the `production_vor` skill slices; nothing else) and prove twice-run-identical.
- **Switch the raw-PPR grades to canonical** in the three reads; prove **is_mine (PPR) numbers unchanged** and report the non-PPR corpus deltas corrected.

## Commit 2 — Pure cleanups (type B: move no live number)

- **Rename the `*_ppr` wart** through the `data_layer` seam; every consumer updated; prove every value identical.
- **Two-way duplicate-rows check** across the other consumers; fix if it leaks, prove no shipped number moves.
- **Retire stale latent comments** after verifying each is resolved (comment-only; prove no code/number moved).

## Commit 3 — Triage the rest + gate + docs

- **Sweep** for remaining deferred markers (`TODO` / `latent` / `revisit` / `deferred` / `for now`), classify each **quick-fix vs needs-own-session**, and record the residual list in STATUS (a short "parking lot" section) — naming the big out-of-scope items: the **silent-reads confidence** work, the **`is_mine`→multi-tenant** un-hardcoding (`MY_USERNAME`/`SLEEPER_LEAGUE_ID`), and the **live/AI track**.
- **Gate:** the type-A fixes carry their bounded-change proof; the type-B cleanups prove identical numbers; determinism value-identical. **Docs** updated.

---

## Acceptance gates

1. **Type A is bounded + explained** — the leaky-naive and PPR-basis fixes name exactly which numbers move (Trust Report `production_vor` skill; non-PPR corpus grades), prove is_mine unchanged, and re-run identical.
2. **Type B moves nothing** — the rename, the two-way check, and the comment retirement prove every live value identical.
3. **The parking lot is triaged, not silently dropped** — a residual list exists in STATUS with quick-fix-vs-own-session labels; the three big out-of-scope items are named.
4. **Determinism + seam** — twice-run value-identical; `queries.js` / views untouched.

---

## Out of scope (needs its own session — name them, don't start them)

- **Silent-reads confidence** — giving `production_vor` + the other no-confidence reads a signal so law-2 becomes measurable for them. A real read-improvement, not a quick fix.
- **`is_mine` → multi-tenant** — killing the `MY_USERNAME` / `SLEEPER_LEAGUE_ID` hardcodes so "my league" means the current user. An onboarding/auth project.
- **The live-season track** — `data_health`, `served=true` writes, AI eval, the weekly Proposer.

---

## Definition of done

- The leaky naive and the raw-PPR basis are fixed (bounded, explained, is_mine unchanged); the Trust Report reflects the honest `production_vor` skill.
- The naming wart, two-way check, and stale comments are cleaned with **zero** live-number movement.
- A triaged parking-lot list is recorded, with the three big items named as future sessions.
- Gates green with teeth; seam held.

---

> ## Standing instructions
> 1. **A suspiciously clean value is a bug until proven otherwise.**
> 2. **A refactor that changes a number is a bug** — prove equivalence. *(Every type-B cleanup; the type-A fixes prove is_mine unchanged.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.**
> 4. **Report, don't overreach** — a cleanup pass fixes what's flagged; it lists the big out-of-scope items, doesn't start them.
> 5. **Deleting dead code / renaming must not move a live number** — the whole point of type B.
> 6. **A plausible explanation is not a diagnosis** — for each stale comment, confirm the latent is *actually* resolved before retiring it; if unsure, keep it and list it.
> 7. **"The artifact exists" and "the consumer uses it" are two different gates** — the rename must update every consumer, not just the producer.
> 8. **Persist the substrate; never re-derive from a moving source** — re-scores are additive + provenanced; the frozen corpus stays the baseline.
