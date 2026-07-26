# Session 8c — Ship the Honest Engine (promote the center-shrink + two-sided band)

**Hand this file to Claude Code as the session brief.**

**Type:** promotion — the human-promotes step; changes shipped behavior BY DESIGN · **Commits:** 3
**Reads first:** `CLAUDE.md` · the proposals being promoted (`proposals/2026-07-16-CENTER_SHRINK.md`, `…-BULL_Z/BEAR_Z/ANCHOR_W.md`, `…-band_confidence_ros_sigma.md`) · `SESSION_8_BAND_HONESTY.md` + the center-shrink summary
**Prior:** the center-shrink test (8b) confirmed S7's parked lever — the projection center was ~43% too high; a flat shrink makes it honest and turns the band two-sided with rankings preserved. **Will's decision: promote honest-and-lower.**
**Blocks:** Session 9 (cleanup) rides on the shipped honest engine.
**This session SHIPS.** Every prior session was propose-only; this one edits `_constants.py`, the shipped reads, and (minimally) the front end — the reviewed promotion the autonomy contract always pointed to. The equivalence discipline binds what must NOT move.

---

## The decision (recorded)

- **Path: honest-and-lower** — shrink the projection center to an honest midpoint; the band becomes a natural two-sided range. The market-matching alternative (S8's all-downside band at the optimistic center) is **not** promoted.
- **`CENTER_SHRINK = 0.8`** — the out-of-sample-safe value (TRAIN-best was 0.7, but DEV/TEST bottom nearer 0.8).
- **Re-fit the band at 0.8** — 8b's band consequence was measured at 0.7; the promoted band dials must be the re-fit **at 0.8**.
- **Swap the band confidence to `ros_sigma`** (raw points); the proven-inverted `ros_cv` retires to an audit column.
- **Parked (not this session):** showing the consensus/optimistic number alongside the honest one (a display-design choice, for later).

## The equivalence spine (why this ships less than it sounds)

A uniform positive scalar on the center is **rank-preserving** (Spearman unchanged) — and `production_vor`'s VOR is `(ros_value − waiver)/(pool_top − waiver)`, so a uniform scale **cancels in the ratio**: VOR is *invariant*. Playoff odds and true-rank are rank-based, so they're invariant too. **The only things that change are the displayed projected points (~0.8×) and the band shape.** Start/sit, waivers, and odds are the same advice. Prove this; don't assume it.

---

## Commit 1 — Re-fit the band at `CENTER_SHRINK=0.8`

- Through the Session-6 harness, at the 0.8-shrunk center, re-fit `BULL_Z`/`BEAR_Z`/`ANCHOR_W` on the corpus objective (across-season, canonical, TEST + generalization sealed). Expect a genuine two-sided band (a mild residual down-skew is real — busts happen — not an artifact). Record the fitted values + holdout coverage/tail-balance.

## Commit 2 — Promote into the shipped engine (the actual ship)

- Apply to `_constants.py` / the reads: **`CENTER_SHRINK=0.8`**, the **0.8 band dials**, and the **`ros_sigma`** confidence (keep `ros_cv` as audit; leave `FORM_ANCHOR_W=0`; do **not** promote S8's `BULL_Z=0` all-downside band).
- **Recompute the displayed `is_mine` reads** at the promoted constants so the app shows the honest numbers.
- **Confirm the front end renders correctly** — the two-sided band + the raw-points confidence. Touch `queries.js`/views **only** if they hard-coded a symmetric band or the `ros_cv` label; keep it minimal. *(The one sanctioned seam touch — a promotion that changes user-facing output.)*
- **Prove the bounded change (name exactly what moves):** projected points scale ~0.8× and the band goes two-sided + `ros_sigma` confidence; **VOR, true-rank, and playoff odds value-identical** (prove Spearman + the bracket/odds read unchanged — the diligence the coupled gates hadn't covered). Twice-run identical.

## Commit 3 — Post-promotion re-score + gates + docs

- **Re-score the shipped engine** to confirm honesty landed: center-MAE down, band coverage ~0.80 two-sided with balanced tails, confidence honest — as a new, distinguishable `constants_hash` population; **the frozen corpus is never overwritten** (it stays the historical baseline).
- **Gates:** `check_center_shrink` / `check_band_honesty` / `check_tuner` green post-promotion; the invariance proof (VOR/rank/odds unchanged) bites; determinism value-identical.
- **Docs:** STATUS / TECH_ARCH / IMPROVEMENT_LOOP record the ship (honest center 0.8×, two-sided band, `ros_sigma` confidence; VOR/rankings/odds unchanged). Note the parked consensus-alongside display.

---

## Acceptance gates

1. **The shrink is contained** — after promotion, `production_vor` VOR, `true_rank`, and playoff odds are **value-identical**; only projected points (~0.8×) and the band change. Proven, not asserted.
2. **The band is honestly two-sided** — re-fit at 0.8, coverage ~0.80 with balanced tails on DEV / sealed TEST / generalization; `ros_sigma` confidence honest (error monotone).
3. **The ship is deliberate + minimal** — `_constants.py` carries `CENTER_SHRINK=0.8` + the 0.8 band + `ros_sigma`; displayed reads recomputed; any view change minimal and only where an assumption was hard-coded.
4. **Determinism + baseline** — twice-run value-identical; the frozen corpus is never overwritten (a re-measure is a new provenanced population).

---

## Out of scope

- **Consensus-alongside display** — the optimistic/market number next to the honest one. Will parked it; a later display-design pass.
- **The Session 9 cleanup** (leaky naive, raw-PPR→canonical, cosmetics) — separate session, after this ships.
- **S8's all-downside band, waking `FORM_ANCHOR_W`, the silent-reads confidence, multi-tenant, the live track.**

---

## Definition of done

- The honest engine ships: center 0.8×, a two-sided band, `ros_sigma` confidence — with **VOR, rankings, and playoff odds provably unchanged** and the displayed reads recomputed; S8's all-downside band and `FORM_ANCHOR_W` not promoted.
- The post-promotion re-score confirms honesty on unseen seasons; the frozen corpus is intact.
- Gates green with teeth; the view renders the new band/confidence; docs updated; consensus-alongside noted as parked.

---

> ## Standing instructions
> 1. **A suspiciously clean value is a bug until proven otherwise.** *(The band re-fit at 0.8, the confidence flip, and especially the "VOR/odds unchanged" proof — interrogate each.)*
> 2. **A refactor that changes a number is a bug** — here numbers change BY DESIGN, so **name exactly which** (projected points, band, confidence) and **prove the rest identical** (VOR, rank, odds).
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked** — **except** this sanctioned promotion touch (rendering the new band/confidence); make it minimal and only where an assumption was hard-coded.
> 4. **Report, don't overreach** — promote exactly the decided set (0.8 center + 0.8 band + `ros_sigma`); do not also promote S8's all-downside band or wake `FORM_ANCHOR_W`.
> 6. **A plausible explanation is not a diagnosis** — prove VOR/odds invariance and the band's two-sidedness on unseen seasons; don't assert them.
> 7. **"The artifact exists" and "the consumer uses it" are two different gates** — gate that the shipped reads AND the displayed app actually consume the new center / band / confidence.
> 8. **Persist the substrate; never re-derive from a moving source** — the frozen corpus stays the baseline; a re-measure is a new provenanced population, not an overwrite.
