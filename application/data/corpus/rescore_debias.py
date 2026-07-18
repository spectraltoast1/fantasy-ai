"""rescore_debias.py — the Session 7 de-bias RE-SCORE (a SHADOW measurement, never a mutation).

Measures whether the second anchor (FORM_ANCHOR_W = λ, the recent-form de-bias of the borrowed ROS centre)
recovers the engine's three optimism symptoms — WITHOUT promoting λ and WITHOUT overwriting the frozen
`predictions`/`resolutions`/`engine_scorecard` (standing instr 8). It re-derives the de-biased band IN
MEMORY, at frozen band dials, and re-grades it against the corpus CANONICAL answer key:

  (b) HEADLINE — band coverage at the FROZEN BULL_Z=1.44 / ANCHOR_W=0.25: does fixing the centre recover
      coverage toward the 0.80 target WITHOUT re-widening the band? If yes, the Session-6 entanglement
      (the band widened to compensate for an over-high centre) is CONFIRMED at the dials themselves — the
      cleanest possible test that the centre was the cause (std instr 6).
  (c) the low miss-tail — the below-bear mass (realised falling under an over-high centre's bear). It should
      fall as the centre is de-biased down.
  (a) the centre's own MAE vs the realised canonical ROS (from backtest_production_vor.objective) — does the
      de-bias reduce it, and by how much (the honest, leak-safe number, not the scorer's hindsight naive).

Grades the shipped band's `in_calibrated_pool` (the decision-relevant subset the width was fit on) at the
band's GRADE_WEEK, per scoring_key across the matched cohort, for each λ on a coarse grid. READ-ONLY: it
flips the in-process dial, recomputes the band in memory, and reads only frozen substrate + the canonical
answer key. Nothing is written; the frozen corpus stays the baseline.

Run: python3 -m application.data.corpus.rescore_debias [--seasons 2025 ...] [--lambdas 0.0 0.1 0.25 0.5 1.0]
"""
import argparse
import contextlib
import io

import polars as pl

from application.data import data_layer
from application.data.transforms import compute_production_vor as pv
from application.data.transforms import compute_ros_player_band as band
from application.data.transforms import backtest_production_vor as bt
from application.data.transforms.backtest_ros_player_band import (
    GRADE_WEEK, TARGET_COVERAGE, _canonical_actual,
)
from application.data.transforms._constants import BULL_Z, ANCHOR_W

DEFAULT_LAMBDAS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)


def _quiet(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


def _coverage_at(season: int, sk: str, lam: float, truth: dict, max_proj_week: int) -> tuple:
    """(n_pool, coverage, below_bear, above_bull) for scoring_key `sk` at the band's GRADE_WEEK, over the
    shipped in_calibrated_pool, with the centre DE-BIASED at λ and the band at its FROZEN BULL_Z/ANCHOR_W.
    Recomputes the shipped band in memory (it inherits the de-bias via _ros_values), then re-grades the
    freeze slice against the scoring-scoped CANONICAL answer key over the SAME remaining weeks the centre
    summed (GRADE_WEEK+1 .. max_proj_week — matching _band_as_of), NOT n_weeks (which can be non-contiguous)."""
    pv.FORM_ANCHOR_W = lam
    try:
        b = _quiet(lambda: band.compute(season, scoring_key=sk))
    finally:
        pv.FORM_ANCHOR_W = 0.0
    fz = b.filter((pl.col("as_of_week") == GRADE_WEEK) & pl.col("in_calibrated_pool"))
    if not fz.height:
        return (0, None, None, None)
    remaining = range(GRADE_WEEK + 1, max_proj_week + 1)
    cov = below = above = n = 0
    for r in fz.iter_rows(named=True):
        pid = r["sleeper_player_id"]
        actual = sum(truth.get((pid, wk), 0.0) for wk in remaining)
        n += 1
        if actual < r["ros_bear"]:
            below += 1
        elif actual > r["ros_bull"]:
            above += 1
        else:
            cov += 1
    return (n, cov / n, below / n, above / n)


def rescore(season: int, lambdas=DEFAULT_LAMBDAS) -> pl.DataFrame:
    """The three-symptom shadow table for one season, across λ. Coverage/tails are the mean across the
    season's matched scoring_keys (each regime's band should hit 0.80); centre-MAE is
    backtest_production_vor.objective at λ. Returns the table; prints it."""
    manifest = data_layer.read_corpus_manifest()
    keys = (manifest.filter((pl.col("stratum") == "matched") & (pl.col("season") == season))
            ["scoring_key"].unique().to_list())
    print(f"\n=== RE-SCORE (shadow) season={season} — frozen BULL_Z={BULL_Z} ANCHOR_W={ANCHOR_W}, "
          f"in_calibrated_pool @ week {GRADE_WEEK}, canonical answer key, keys={sorted(keys)} ===")
    print(f"  {'λ':>5} {'centre-MAE':>11} {'coverage':>9} {'below-bear':>11} {'above-bull':>11}   "
          f"(target coverage {TARGET_COVERAGE:.2f}; below = the low miss-tail)")
    # truth + horizon are λ-independent — compute once per key.
    per_key = {}
    for sk in keys:
        cons = data_layer.read_projection_consensus(season, scoring_key=sk)
        per_key[sk] = (_canonical_actual(season, sk), int(cons["week"].max()))
    rows = []
    for lam in lambdas:
        mae = bt.objective(season, {"FORM_ANCHOR_W": lam})
        covs, belows, aboves, ns = [], [], [], []
        for sk in keys:
            truth, max_proj_week = per_key[sk]
            n, cov, below, above = _coverage_at(season, sk, lam, truth, max_proj_week)
            if cov is not None:
                covs.append(cov); belows.append(below); aboves.append(above); ns.append(n)
        cov_m = sum(covs) / len(covs) if covs else float("nan")
        below_m = sum(belows) / len(belows) if belows else float("nan")
        above_m = sum(aboves) / len(aboves) if aboves else float("nan")
        rows.append({"season": season, "lambda": lam, "centre_mae": mae, "coverage": cov_m,
                     "below_bear": below_m, "above_bull": above_m, "n_pool": sum(ns)})
        print(f"  {lam:>5.2f} {mae:>11.3f} {cov_m:>9.3f} {below_m:>11.3f} {above_m:>11.3f}   (n={sum(ns)})")
    return pl.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description="Session 7 de-bias re-score (shadow measurement).")
    ap.add_argument("--seasons", nargs="+", type=int, default=[2025],
                    help="seasons to re-score (default: 2025, the freshest TEST season)")
    ap.add_argument("--lambdas", nargs="+", type=float, default=list(DEFAULT_LAMBDAS))
    a = ap.parse_args()
    for s in a.seasons:
        rescore(s, a.lambdas)
    print("\n  (shadow only — no predictions/resolutions/scorecard written; the frozen corpus is the baseline.)")


if __name__ == "__main__":
    main()
