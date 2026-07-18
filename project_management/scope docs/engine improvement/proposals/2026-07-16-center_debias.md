# Tuner proposal — `center_debias` (LEAD)

**as-of:** 2026-07-16  ·  **rank:** 1  ·  **module:** `projection_consensus/production_vor`  ·  **scope:** scoring

**baseline (frozen L3):** code_version `6dfcab270ee0` · constants_hash `a3d01b8e5f4d5131`

## Verdict: LEAD (top-ranked)

TOP LEAD — de-bias the center was tried (Session 7) and did NOT fix the optimism. FORM_ANCHOR_W (recent-form second anchor) was built + tuned on the split: λ*=0.1, DEV effect 0.20 < floor → HELD, and the shadow re-score (rescore_debias) shows de-biasing the center does NOT recover band coverage at the frozen dials (~0.57, flat/declining; the ~0.43 below-bear low-miss tail is unmoved). The honest, leak-safe recent form doesn't beat the borrowed center (the scorer's naive used a hindsight forward-week count). MECHANISM: the under-coverage is a band-WIDTH problem, not center height (miss is ~0.43 below-bear vs ~0.00 above-bull). SESSION 8 is the lever — re-tune BULL_Z (widen + low-skew) on the corpus objective; SKEW_GAIN still moves 1.5→1.0. center_gap delta-tracking (+~30 pts/season) is the substrate for a future SYSTEMATIC-shrink de-bias, not recent form.
