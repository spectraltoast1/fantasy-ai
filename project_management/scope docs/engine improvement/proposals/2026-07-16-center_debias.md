# Tuner proposal — `center_debias` (LEAD)

**as-of:** 2026-07-16  ·  **rank:** 1  ·  **module:** `projection_consensus/production_vor`  ·  **scope:** scoring

**baseline (frozen L3):** code_version `6dfcab270ee0` · constants_hash `a3d01b8e5f4d5131`

## Verdict: LEAD (top-ranked)

TOP LEAD — de-bias the projection center before touching any band constant. L3 measured the center optimistic (production_vor loses to carry-recent-form every season; the band covers ~0.55 vs its 0.80 target). Every band dial (BAND_Z / SKEW_GAIN / BULL_Z / ANCHOR_W) sits downstream of it, so this session HOLDS them all — and SKEW_GAIN's OOS fit even moves 1.5→1.0 (toward 0, as pre-registered), confirming the skew is compensating for the center bias, not a real ROS property. Session 7 adds a recent-form shrinkage dial to the center, tuned THROUGH this harness on the same split; re-fit the band dials only after (Session 8).
