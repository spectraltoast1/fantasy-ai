# Session 7 — De-bias the projection center (the de-bias read-improvement)

> **SCOPING STUB — drafted in the Session 6 (L4 Tuner) closedown, 2026-07-17. Expand/adjust before running.
> DO NOT treat as final; the Tuner brief authored this only to hand the next session the right first move.**

**Type:** read-improvement (the first behavior change the loop proposes) — tuned THROUGH the L4 harness ·
**Prior:** Session 6 (the Tuner — `_constants.py` dials registry + `corpus/tuner.py` split-aware sweep +
`check_tuner`; merged). **Reads first:** the Session-6 proposals (`proposals/2026-07-16-*.md`, esp.
`center_debias` and `SKEW_GAIN`), `IMPROVEMENT_LOOP.md` §L4, `SESSION_5_L3_SCORER.md` findings.

## Why this is next (the Tuner's top LEAD)

L3 measured the projection **center** optimistic and stable: `production_vor` loses to "carry recent form
forward" every season (skill −0.16…−0.39 though it ranks well, Spearman ~0.88); the band under-covers
(~0.55 vs 0.80). The L4 first run confirmed every **band** dial is downstream of that center — it HELD all
four (`BAND_Z`/`SKEW_GAIN`/`BULL_Z`/`ANCHOR_W`), and `SKEW_GAIN`'s OOS fit even moved 1.5→1.0 (toward 0),
i.e. the skew term is compensating for the center bias. **Fix the center first; the band dials re-fit after
(Session 8).**

## The change (decision-layer, not a new projection engine — "borrow the substrate; build the layer")

Add a **recent-form shrinkage dial** to the projection center: a *second anchor* toward recent form (the
engine already anchors toward preseason ADP; the scorer showed recent-form is beating the raw projection).
A single new tunable (e.g. `RECENT_FORM_W` in `compute_projection_consensus` / `compute_production_vor`),
declared in the **dials registry** and tuned THROUGH the Session-6 harness on the same split (TRAIN 2020–23
/ DEV 2024 / TEST 2025). This is the harness's first *real* RECOMMEND path (Session 6 produced zero — the
constants were already fit except where entangled).

## Deliverables (sketch)

1. The recent-form anchor in the center read + its dial in `_constants.py` (equivalence: the un-tuned value
   reproduces today's center — no silent behavior change until the tune is promoted).
2. Tune it via `corpus/tuner.py` → a RECOMMEND proposal if it clears the four guardrails on the DEV holdout
   (this is the RECOMMEND path the Session-6 first run never exercised).
3. **Delta-tracking** for a future seasonal auto-update of the dial.
4. Re-score (L3) to measure the win across the three optimism symptoms (VOR skill, band coverage, the
   inverted `ros_cv`). Then the band dials are UN-entangled → **Session 8** re-fits them (expect
   `SKEW_GAIN`→0; swap the band's confidence signal from `ros_cv` to the raw-points spread).

## Guardrails / discipline (unchanged from L4)

Split is structural (peeking fails `check_tuner`); auto-tune, human promotes (the tuner proposes, a human
merges in a normal worktree session); no `queries.js`/view leak; report-don't-overreach. The
`BULL_Z`/`ANCHOR_W` corpus-wide per-league ROS-band objective (deferred in Session 6 as is_mine-scoped) is
the moment the **league-wise holdout becomes load-bearing** — build it here.
