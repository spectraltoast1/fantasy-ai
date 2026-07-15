"""
Check ADP-curve leakage — the HARD leak gate for the per-held-out-season §2 anchor (Session 2).

The §2 ROS bull/bear range is blended toward an empirical ADP rank→realized-points anchor
(`adp_points_curve`, weight ANCHOR_W). Persisted as ONE curve per held-out target season
(`derived/adp_points_curve/holdout_{S}.parquet`), fit on every season EXCEPT S. A multi-season corpus
that graded §2 on 2023 against a curve that had already SEEN 2023 would be optimistic and
unfalsifiable — the exact silent, invisible-in-the-output error class the whole improvement loop exists
to prevent. This gate makes that error impossible to ship.

Verdicts (exit 0 iff all pass), for EVERY fittable season S (both adp_preseason + nfl_stats present):

  1. **Present** — a holdout_{S} curve exists on disk for every fittable season.
  2. **Provenance honesty (the crux)** — every row carries holdout_season == S, and S ∉ train_seasons.
     The season a curve anchors can never appear in the seasons that fit it.
  3. **Train set is exactly the complement** — train_seasons == (all fittable seasons) ∖ {S}. No season
     is silently dropped from OR sneaked into the fit.
  4. **Recompute match** — independently re-run the shipped compute(S) and demand the persisted parquet
     matches frame-for-frame (the check_market_vor / backtest_production_vor idiom): what's gated is
     exactly what the band reads, not a re-derivation.

Usage:
    python3 -m application.data.transforms.check_adp_curve_leakage
"""

import argparse
import sys

from polars.testing import assert_frame_equal

from application.data import data_layer
from application.data.transforms import compute_adp_points_curve


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def check() -> bool:
    available = compute_adp_points_curve._available_seasons()
    print(f"  fittable seasons (adp_preseason ∩ nfl_stats): {available}")
    passed = True

    for s in available:
        # 1. Present
        if not data_layer.adp_points_curve_exists(holdout=s):
            passed = False
            _fail(f"holdout_{s}: curve missing on disk")
            continue
        curve = data_layer.read_adp_points_curve(holdout=s)

        # 2. Provenance honesty — the leak check itself.
        hs = curve["holdout_season"].unique().to_list()
        train = curve["train_seasons"][0].to_list()   # identical across rows (provenance)
        if hs != [s]:
            passed = False
            _fail(f"holdout_{s}: holdout_season column = {hs}, expected [{s}]")
        elif s in train:
            passed = False
            _fail(f"holdout_{s}: LEAK — season {s} is in its own train_seasons {train}")
        else:
            # 3. Train set is exactly the complement.
            expected_train = [x for x in available if x != s]
            if sorted(train) != expected_train:
                passed = False
                _fail(f"holdout_{s}: train_seasons {sorted(train)} ≠ complement {expected_train}")
            else:
                _ok(f"holdout_{s}: leak-free — fit on {sorted(train)}, season {s} held out")

        # 4. Recompute match — the persisted curve IS the shipped compute, not a re-derivation.
        recomputed = compute_adp_points_curve.compute(holdout=s)
        try:
            assert_frame_equal(
                curve.sort("position", "pos_ecr_rank"),
                recomputed.sort("position", "pos_ecr_rank"),
                check_row_order=False,
            )
        except AssertionError as e:
            passed = False
            _fail(f"holdout_{s}: persisted curve ≠ recompute(holdout={s}) — {str(e).splitlines()[0]}")

    return passed


def main() -> None:
    print("=== check_adp_curve_leakage ===")
    ok = check()
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    argparse.ArgumentParser(description="Hard leak gate for the per-holdout ADP anchor curve.").parse_args()
    main()
