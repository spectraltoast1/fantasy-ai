"""rescore_center_shrink.py — the center-shrink re-score (SHADOW, propose-only).

Session 8 showed the projection centre sits at the ~98th percentile of realised ROS, which forced the honest
band into an all-downside shape (`BULL_Z→0`, `BEAR_Z→3.5`). This measures the flat systematic-shrink lever
S7 parked: does a multiplicative `CENTER_SHRINK` toward the realised median (a) drop centre-MAE out-of-sample,
(b) re-symmetrise the band (re-fit `BULL_Z`/`BEAR_Z` at the shrunk centre → both positive, `BULL_Z≈BEAR_Z`,
instead of the all-downside fit), and (c) leave ranking/discrimination untouched (a positive scalar is
rank-preserving). The whole point is (b): an honest centre → a natural range.

SHADOW ONLY — reads the frozen substrate (consensus + canonical outcomes + the manifest); recomputes the
centre + the band IN MEMORY at candidate dials; writes NOTHING to the frozen corpus. The dials stay at their
identity defaults; nothing is promoted.

Run: python3 -m application.data.corpus.rescore_center_shrink
"""
import argparse
import itertools

import polars as pl

from application.data.transforms import backtest_production_vor as bpv
from application.data.transforms import backtest_ros_player_band as bt
from application.data.transforms._constants import REGISTRY

TRAIN = (2020, 2021, 2022, 2023)
DEV = 2024
TEST = 2025
SHRINK_GRID = REGISTRY["CENTER_SHRINK"].grid
_BAND_GRIDS = (REGISTRY["BULL_Z"].grid, REGISTRY["BEAR_Z"].grid, REGISTRY["ANCHOR_W"].grid)


def _center_mae(season: int, shrink: float) -> float | None:
    """Mean per-scoring-key centre-MAE at `shrink` (reuses the shipped objective, which recomputes the centre
    in memory via _ros_values at CENTER_SHRINK — never the frozen parquet). None if not computable."""
    try:
        return bpv.objective(season, {"CENTER_SHRINK": shrink})
    except (FileNotFoundError, ValueError):
        return None


def _band_objective(ing: pl.DataFrame, bull_z: float, bear_z: float, anchor_w: float) -> float:
    """The Session-8 band objective on materialized ingredients: mean over scoring keys of
    |coverage−TARGET| + |below-bear − above-bull|."""
    pk = bt._score_per_key(bt._apply_dials(ing, bull_z, bear_z, anchor_w))
    return float(((pk["cov"] - bt.TARGET_COVERAGE).abs() + (pk["below"] - pk["above"]).abs()).mean())


def _shrunk_ingredients(season: int, shrink: float, strata=("matched",)) -> pl.DataFrame:
    """The band's dial-independent ingredients with the centre scaled by `shrink` (round6, matching
    _ros_values) — i.e. the band as it would be built on the shrunk centre. Frozen reads only."""
    ing = bt._corpus_ingredients(season, strata=strata)
    if shrink != 1.0:
        ing = ing.with_columns((pl.col("center") * shrink).round(6).alias("center"))
    return ing


def _fit_band_at_shrink(shrink: float, train_ing: dict) -> tuple:
    """Joint TRAIN fit of BULL_Z×BEAR_Z×ANCHOR_W at the shrunk centre (mean objective across TRAIN seasons).
    Returns (best_combo, best_obj). `train_ing` maps season → UNSHRUNK ingredients (scaled here per shrink)."""
    scaled = {s: (ing if shrink == 1.0 else ing.with_columns((pl.col("center") * shrink).round(6).alias("center")))
              for s, ing in train_ing.items()}
    best, best_obj = None, None
    for bull_z, bear_z, anchor_w in itertools.product(*_BAND_GRIDS):
        vals = [_band_objective(ing, bull_z, bear_z, anchor_w) for ing in scaled.values()]
        obj = sum(vals) / len(vals)
        if best_obj is None or obj < best_obj:
            best_obj, best = obj, (bull_z, bear_z, anchor_w)
    return best, best_obj


def _coverage(season: int, shrink: float, combo: tuple, strata=("matched",)):
    """(cov, below, above) mean over scoring keys for the band at (shrunk centre, `combo`)."""
    ing = _shrunk_ingredients(season, shrink, strata=strata)
    pk = bt._score_per_key(bt._apply_dials(ing, *combo))
    return (float(pk["cov"].mean()), float(pk["below"].mean()), float(pk["above"].mean()))


def _effective_widths(season: int, shrink: float, combo: tuple) -> tuple:
    """The band's EFFECTIVE up/down half-widths at the fitted combo — mean(bull − centre) vs mean(centre −
    bear) over the calibrated players. This is the honest symmetry measure (the range the user sees), which
    the raw BULL_Z/BEAR_Z dials obscure once the ADP anchor (ANCHOR_W>0) blends the extremes. Returns
    (up_width, down_width, up/down ratio) on the shrunk centre."""
    ing = _shrunk_ingredients(season, shrink)
    g = bt._apply_dials(ing, *combo)
    # round6: the pool-mean is a multi-threaded polars reduction whose accumulation order flakes at the ULP
    # run-to-run; 6 dp collapses the flake so the reported widths are deterministic (far below display need).
    up = round(float((g["bull"] - g["center"]).mean()), 6)
    down = round(float((g["center"] - g["bear"]).mean()), 6)
    return (up, down, round(up / down, 6) if down else float("nan"))


def _discrimination(season: int, shrink: float) -> tuple:
    """Spearman(centre, realised) at shrink=1 vs the shrunk centre — a positive scalar is rank-preserving,
    so these are exactly equal (the empirical cross-check for the analytic invariance)."""
    ing = bt._corpus_ingredients(season)
    d0 = ing.select(pl.corr("center", "actual", method="spearman")).item()
    d1 = ing.with_columns((pl.col("center") * shrink).alias("center")).select(
        pl.corr("center", "actual", method="spearman")).item()
    return (float(d0), float(d1))


def run(seasons=None, shrink=None) -> dict:
    """Re-score the center-shrink: (a) centre-MAE across the grid, (b) band re-fit at SHRINK*, (c) ranking
    invariance. Prints the report; returns structured results. SHADOW: no writes."""
    # (a) centre-MAE across the shrink grid, TRAIN mean + DEV + TEST
    train_mae = {s: [m for m in (_center_mae(yr, s) for yr in TRAIN) if m is not None] for s in SHRINK_GRID}
    mae_a = {s: {"train": (sum(v) / len(v) if v else None),
                 "dev": _center_mae(DEV, s), "test": _center_mae(TEST, s)} for s, v in train_mae.items()}
    computable = {s: r["train"] for s, r in mae_a.items() if r["train"] is not None}
    shrink_star = shrink if shrink is not None else min(computable, key=computable.get)

    print("\n=== Center-shrink re-score (SHADOW) — the flat systematic centre shrink ===")
    print("  (a) centre-MAE(shrunk centre, realised ROS canonical) — LOWER better:")
    print(f"  {'shrink':>7} {'TRAIN':>9} {'DEV 2024':>9} {'TEST 2025':>10}")
    for s in SHRINK_GRID:
        r = mae_a[s]
        star = "  ←TRAIN-best" if s == shrink_star else ""
        def f(x):
            return "n/a" if x is None else f"{x:.3f}"
        print(f"  {s:>7} {f(r['train']):>9} {f(r['dev']):>9} {f(r['test']):>10}{star}")
    dev_drop = mae_a[1.0]["dev"] - mae_a[shrink_star]["dev"] if mae_a[shrink_star]["dev"] else None
    print(f"  → SHRINK* = {shrink_star}; DEV centre-MAE {mae_a[1.0]['dev']:.3f} → "
          f"{mae_a[shrink_star]['dev']:.3f} (drop {dev_drop:.3f})")

    # (b) THE HEADLINE — re-fit the band jointly at the unshrunk vs the shrunk centre
    print("\n  (b) band re-fit (BULL_Z×BEAR_Z×ANCHOR_W joint, TRAIN) — does the shrunk centre symmetrise it?")
    train_ing = {yr: bt._corpus_ingredients(yr) for yr in TRAIN}
    fit_1, _ = _fit_band_at_shrink(1.0, train_ing)
    fit_s, _ = _fit_band_at_shrink(shrink_star, train_ing)
    print(f"    unshrunk (shrink=1.0): BULL_Z={fit_1[0]}  BEAR_Z={fit_1[1]}  ANCHOR_W={fit_1[2]}   "
          f"(S8's all-downside band)")
    print(f"    shrunk   (shrink={shrink_star}): BULL_Z={fit_s[0]}  BEAR_Z={fit_s[1]}  ANCHOR_W={fit_s[2]}")
    # The honest symmetry measure is the EFFECTIVE up/down half-widths (raw dials are muddied by the anchor).
    up1, dn1, r1 = _effective_widths(DEV, 1.0, fit_1)
    ups, dns, rs = _effective_widths(DEV, shrink_star, fit_s)
    print(f"    effective half-widths (DEV, mean bull−centre / centre−bear):")
    print(f"      unshrunk: up {up1:.1f} / down {dn1:.1f}  (up:down {r1:.2f}) — all-downside")
    print(f"      shrunk:   up {ups:.1f} / down {dns:.1f}  (up:down {rs:.2f})")
    deskewed = fit_s[0] > fit_1[0] and rs > r1        # BULL_Z off the floor AND the range less lopsided
    symmetric = 0.5 <= rs <= 2.0                        # effective up:down within 2× either way
    print(f"    → DE-SKEWED (BULL_Z off the floor, range less lopsided): {deskewed};  "
          f"near-symmetric (up:down in [0.5, 2.0]): {symmetric}")
    print("    coverage at the shrunk-centre fit (cov / below-bear / above-bull):")
    cover = {}
    for season, stratum, tag in ((DEV, "matched", "DEV 2024"), (TEST, "matched", "TEST 2025 (sealed)"),
                                 (TEST, "generalization", "generalization 2025 (holdout)")):
        try:
            c = _coverage(season, shrink_star, fit_s, strata=(stratum,))
        except (FileNotFoundError, ValueError):
            continue
        cover[(season, stratum)] = c
        print(f"      {tag:<34}: {c[0]:.3f} / {c[1]:.3f} / {c[2]:.3f}")

    # (c) ranking/discrimination invariance
    d0, d1 = _discrimination(DEV, shrink_star)
    print(f"\n  (c) ranking invariance — a positive scalar is rank-preserving (Spearman(centre, realised)):")
    print(f"      shrink=1.0 → {d0:+.6f}   shrink={shrink_star} → {d1:+.6f}   identical: {d0 == d1}")

    print("\n  SHADOW — the frozen corpus + the shipped dials are untouched; the proposal is the tuner's.")
    return {"shrink_star": shrink_star, "mae": mae_a, "fit_unshrunk": fit_1, "fit_shrunk": fit_s,
            "eff_unshrunk": (up1, dn1, r1), "eff_shrunk": (ups, dns, rs), "deskewed": deskewed,
            "symmetric": symmetric, "coverage": cover, "discrimination": (d0, d1)}


def __main():
    ap = argparse.ArgumentParser(description="Center-shrink re-score (shadow).")
    ap.add_argument("--shrink", type=float, default=None, help="override SHRINK* (default: the TRAIN argmin)")
    run(shrink=ap.parse_args().shrink)


if __name__ == "__main__":
    __main()
