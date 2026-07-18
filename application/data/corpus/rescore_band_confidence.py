"""rescore_band_confidence.py — Session 8, the confidence-honesty re-score (SHADOW, propose-only).

The ROS band's stated confidence signal is `ros_cv` (= σ/centre, a *percentage* dispersion). Session 5 found
it INVERTED: the frozen scorecard's `conf_monotonicity` for ros_player_band is POSITIVE (+0.49..+0.69,
mean ~0.58) with a NEGATIVE low−high tier gap — its narrowest-% "most confident" bands (the high-projection
stars) miss by the MOST in raw points. The honest signal is the raw-points spread `ros_sigma` (σ in points):
a wider raw interval should read as LESS confident.

This module DEMONSTRATES the fix without shipping it (Will's ruling: changing what "confident" means is
user-facing behaviour → it is PROPOSED and human-promoted, exactly like the S8 dial values). It recomputes
the L3 confidence-honesty verdict TWO ways off the FROZEN ledger's EXISTING columns — `confidence` (= ros_cv,
today's signal) and `sigma` (= ros_sigma, the proposed signal) — using the SAME transform the scorer uses
(`compute_engine_scorecard.enrich` / `_confidence_honesty`): conf_strength = −signal (strength "neg"), the
honesty primitive = |centre − truth| (abs_error), the tertile gap, and Spearman(conf_strength, error)
[≤ −margin honest]. It reproduces the frozen ros_cv numbers (a method check) and shows ros_sigma flips honest.

SHADOW ONLY — reads the frozen predictions/resolutions; writes NOTHING (no predictions/outcomes/resolutions/
engine_scorecard mutation, std instr 8). The scorer registry, the ledger mapping, and the band read are
UNTOUCHED. `check_band_honesty` gates that this DEMONSTRATES the flip — not that the shipped signal is swapped.

Run: python3 -m application.data.corpus.rescore_band_confidence [--seasons 2020 2021 2022 2023 2024 2025]
"""
import argparse

import polars as pl

from application.data import data_layer
from application.data.corpus import scorecard_registry as reg

# The band's two candidate confidence signals, both with strength "neg" (↑ signal → LESS confident):
#   current  — `confidence` column (= ros_cv, the percentage dispersion), INVERTED per S5
#   proposed — `sigma` column (= ros_sigma, the raw-points spread), the honest signal
CURRENT_SIGNAL = "confidence"     # ros_cv
PROPOSED_SIGNAL = "sigma"         # ros_sigma
CORPUS_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)


def _band_pool(season: int) -> pl.DataFrame:
    """The band's resolved ∧ inputs_ok claims for one season — the SAME pool `compute_engine_scorecard`
    scores (predictions ⋈ resolutions on prediction_id), with `value` (= ros_centre), `truth` (realised
    ROS), and both candidate signals (`confidence` = ros_cv, `sigma` = ros_sigma). Read-only."""
    preds = data_layer.read_predictions(season).filter(
        (pl.col("read") == "ros_player_band") & (pl.col("claim_type") == "interval")
    ).select("prediction_id", "value", "confidence", "sigma", "inputs_ok")
    res = data_layer.read_resolutions(season).select("prediction_id", "truth", "resolved")
    pool = preds.join(res, on="prediction_id", how="inner").filter(
        pl.col("resolved") & pl.col("inputs_ok")
        & pl.col("truth").is_not_null() & pl.col("value").is_not_null()
    )
    return pool.with_columns((pl.col("value") - pl.col("truth")).abs().alias("_conf_err"))


def _honesty(pool: pl.DataFrame, signal_col: str) -> dict:
    """Confidence-honesty for one signal, mirroring `compute_engine_scorecard._confidence_honesty` exactly:
    conf_strength = −signal (strength "neg"); Spearman(conf_strength, |centre−truth|) [≤ −margin honest];
    tertile low−high error gap [≥0 honest]. Single group-free reductions on the stable frame → deterministic.
    Returns {n, spearman, top_minus_bottom, honest, low_err, high_err}."""
    cf = pool.filter(pl.col(signal_col).is_not_null() & pl.col("_conf_err").is_not_null())
    n = cf.height
    if n < 3:
        return {"n": n, "spearman": None, "top_minus_bottom": None, "honest": False,
                "low_err": None, "high_err": None}
    cf = cf.with_columns((-pl.col(signal_col)).alias("_strength"))
    m = cf.select(pl.corr("_strength", "_conf_err", method="spearman")).item()
    m = None if (m is None or m != m) else float(m)
    e1 = cf.select(pl.col("_strength").quantile(reg.TIER_QUANTILES[0])).item()
    e2 = cf.select(pl.col("_strength").quantile(reg.TIER_QUANTILES[1])).item()
    cf = cf.with_columns(
        pl.when(pl.col("_strength") <= e1).then(pl.lit(reg.TIER_LABELS[0]))
          .when(pl.col("_strength") <= e2).then(pl.lit(reg.TIER_LABELS[1]))
          .otherwise(pl.lit(reg.TIER_LABELS[2])).alias("_tier"))
    te = {r["_tier"]: r["err"] for r in
          cf.group_by("_tier").agg(err=pl.col("_conf_err").mean()).to_dicts()}
    lo, hi = te.get(reg.TIER_LABELS[0]), te.get(reg.TIER_LABELS[2])
    tmb = (lo - hi) if (lo is not None and hi is not None) else None
    honest = (m is not None and m <= -reg.CONF_MONO_MARGIN and tmb is not None and tmb >= 0.0)
    return {"n": n, "spearman": m, "top_minus_bottom": tmb, "honest": honest, "low_err": lo, "high_err": hi}


def run(seasons=None) -> dict:
    """Re-score the band's confidence-honesty for both signals, per season + pooled. Returns
    {per_season, pooled} — each a {signal: honesty-dict}. Prints the before/after table. SHADOW: no writes."""
    seasons = tuple(seasons) if seasons else CORPUS_SEASONS
    pools = {}
    for s in seasons:
        try:
            pools[s] = _band_pool(s)
        except FileNotFoundError:
            pass
    per_season = {s: {sig: _honesty(p, sig) for sig in (CURRENT_SIGNAL, PROPOSED_SIGNAL)}
                  for s, p in pools.items()}
    pooled_df = pl.concat(list(pools.values()), how="vertical") if pools else pl.DataFrame()
    pooled = {sig: _honesty(pooled_df, sig) for sig in (CURRENT_SIGNAL, PROPOSED_SIGNAL)} if pools else {}

    mar = reg.CONF_MONO_MARGIN
    print(f"\n=== Band confidence-honesty re-score (SHADOW) — current ros_cv vs proposed ros_sigma ===")
    print(f"  honest = Spearman(−signal, |centre−truth|) ≤ −{mar} AND low−high tier gap ≥ 0")
    print(f"  {'season':>8} {'signal':>10} {'n':>7} {'spearman':>10} {'lo−hi gap':>11} {'honest':>7}")
    for s in sorted(per_season):
        for sig, name in ((CURRENT_SIGNAL, "ros_cv"), (PROPOSED_SIGNAL, "ros_sigma")):
            h = per_season[s][sig]
            sp = "n/a" if h["spearman"] is None else f"{h['spearman']:+.4f}"
            tmb = "n/a" if h["top_minus_bottom"] is None else f"{h['top_minus_bottom']:+.2f}"
            print(f"  {s:>8} {name:>10} {h['n']:>7} {sp:>10} {tmb:>11} {str(h['honest']):>7}")
    if pooled:
        print(f"  {'-'*56}")
        for sig, name in ((CURRENT_SIGNAL, "ros_cv"), (PROPOSED_SIGNAL, "ros_sigma")):
            h = pooled[sig]
            sp = "n/a" if h["spearman"] is None else f"{h['spearman']:+.4f}"
            tmb = "n/a" if h["top_minus_bottom"] is None else f"{h['top_minus_bottom']:+.2f}"
            print(f"  {'POOLED':>8} {name:>10} {h['n']:>7} {sp:>10} {tmb:>11} {str(h['honest']):>7}")
        cur, prop = pooled[CURRENT_SIGNAL], pooled[PROPOSED_SIGNAL]
        print(f"\n  FINDING: ros_cv Spearman {cur['spearman']:+.3f} (INVERTED — narrow-% stars miss most) "
              f"→ ros_sigma {prop['spearman']:+.3f} "
              f"({'HONEST' if prop['honest'] else 'not yet honest'} — wider raw σ ↔ more error). "
              f"Proposal: swap the band's confidence signal ros_cv → ros_sigma. SHADOW — nothing shipped.")
    return {"per_season": per_season, "pooled": pooled}


def __main():
    ap = argparse.ArgumentParser(description="Band confidence-honesty re-score (shadow, Session 8).")
    ap.add_argument("--seasons", type=int, nargs="*", default=None)
    run(ap.parse_args().seasons)


if __name__ == "__main__":
    __main()
