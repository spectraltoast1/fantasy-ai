"""rescore_band_coverage.py — Session 8, the band-honesty WIN re-score (SHADOW, propose-only).

The headline of the session: at the PROPOSED joint dials (BULL_Z / BEAR_Z / ANCHOR_W from the L4 tuner),
does the ROS band's coverage climb from ~0.55 toward ~0.80 with balanced tails — and does it hold on the
UNSEEN seasons (TEST 2025) and the league-wise GENERALIZATION holdout, not just the fit window (std instr 6)?

It recomputes coverage / below-bear / above-bull at the CURRENT vs the PROPOSED dials, per (season, stratum),
reusing the shipped band math (`backtest_ros_player_band._corpus_ingredients` / `_apply_dials` — the same
vectorised mirror the objective uses, proven == `_blended_band`). The proposed dials are read from the live
tuner run (`tuner.build_proposals`), so this can never drift from what was actually proposed. Canonical
answer key, across the season's as-of weeks.

SHADOW ONLY — reads the frozen corpus (manifest + production_vor + projection_consensus + canonical
outcomes); writes NOTHING (no predictions/outcomes/resolutions/engine_scorecard mutation, std instr 8). The
dials stay at their current values in `_constants.py`; nothing is promoted.

Run: python3 -m application.data.corpus.rescore_band_coverage
"""
import argparse

import polars as pl

from application.data.corpus import tuner
from application.data.transforms import backtest_ros_player_band as bt
from application.data.transforms._constants import ANCHOR_W, BEAR_Z, BULL_Z

CORPUS_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)
ROS_DIALS = ("BULL_Z", "BEAR_Z", "ANCHOR_W")


def _split_label(season: int) -> str:
    if season in tuner.TRAIN_SEASONS:
        return "TRAIN"
    if season in tuner.DEV_SEASONS:
        return "DEV"
    if season in tuner.TEST_SEASONS:
        return "TEST"
    return "?"


def proposed_dials() -> dict:
    """The ros-band dials' PROPOSED values from the live tuner run (RECOMMEND → proposed; else current)."""
    ordered, _ = tuner.build_proposals()
    by = {p.constant: p for p in ordered}
    cur = {"BULL_Z": BULL_Z, "BEAR_Z": BEAR_Z, "ANCHOR_W": ANCHOR_W}
    out = {}
    for n in ROS_DIALS:
        p = by.get(n)
        out[n] = float(p.proposed) if (p is not None and isinstance(p.proposed, (int, float))) else cur[n]
    return out


def _coverage(season: int, stratum: str, dials: dict):
    """(cov, below, above) mean over scoring keys for one (season, stratum) at `dials`, or None if empty."""
    try:
        ing = bt._corpus_ingredients(season, strata=(stratum,))
    except (FileNotFoundError, ValueError):
        return None
    pk = bt._score_per_key(bt._apply_dials(ing, dials["BULL_Z"], dials["BEAR_Z"], dials["ANCHOR_W"]))
    return (float(pk["cov"].mean()), float(pk["below"].mean()), float(pk["above"].mean()))


def run(seasons=None) -> dict:
    """Re-score band coverage current vs proposed, per (season, stratum). Returns the structured result;
    prints the before/after table. SHADOW: no writes."""
    seasons = tuple(seasons) if seasons else CORPUS_SEASONS
    cur = {"BULL_Z": BULL_Z, "BEAR_Z": BEAR_Z, "ANCHOR_W": ANCHOR_W}
    prop = proposed_dials()
    print(f"\n=== Band-honesty WIN re-score (SHADOW) — coverage at current vs PROPOSED dials ===")
    print(f"  current  BULL_Z={cur['BULL_Z']} BEAR_Z={cur['BEAR_Z']} ANCHOR_W={cur['ANCHOR_W']}")
    print(f"  proposed BULL_Z={prop['BULL_Z']} BEAR_Z={prop['BEAR_Z']} ANCHOR_W={prop['ANCHOR_W']}  "
          f"(target coverage {bt.TARGET_COVERAGE:.2f})")
    print(f"  {'season':>8} {'split':>6} {'stratum':>15} "
          f"{'cov→':>18} {'below-bear→':>18} {'above-bull→':>18}")
    result = {}
    for stratum in ("matched", "generalization"):
        for s in sorted(seasons):
            c0 = _coverage(s, stratum, cur)
            c1 = _coverage(s, stratum, prop)
            if c0 is None or c1 is None:
                continue
            result[(s, stratum)] = {"current": c0, "proposed": c1}
            print(f"  {s:>8} {_split_label(s):>6} {stratum:>15} "
                  f"{c0[0]:.3f}→{c1[0]:.3f}     {c0[1]:.3f}→{c1[1]:.3f}     {c0[2]:.3f}→{c1[2]:.3f}")
    # headline: pooled DEV/TEST + generalization
    print()
    for s, stratum, tag in ((tuner.DEV_SEASONS[0], "matched", "DEV 2024 (certify)"),
                            (tuner.TEST_SEASONS[0], "matched", "TEST 2025 (sealed)"),
                            (tuner.TEST_SEASONS[0], "generalization", "generalization 2025 (league holdout)")):
        r = result.get((s, stratum))
        if r:
            c0, c1 = r["current"], r["proposed"]
            print(f"  {tag:<40}: coverage {c0[0]:.3f} → {c1[0]:.3f}   "
                  f"tails below/above {c1[1]:.3f}/{c1[2]:.3f}")
    print("\n  SHADOW — the frozen corpus + the shipped dials are untouched; the proposal is the tuner's.")
    return {"current": cur, "proposed": prop, "by_season_stratum": result}


def __main():
    ap = argparse.ArgumentParser(description="Band-honesty win re-score (shadow, Session 8).")
    ap.add_argument("--seasons", type=int, nargs="*", default=None)
    run(ap.parse_args().seasons)


if __name__ == "__main__":
    __main()
