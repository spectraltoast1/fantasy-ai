"""backfill_center_gap.py — Session 7 (the de-bias) seasonal center-gap delta-tracking.

Persists, per (season, scoring_key), the SYSTEMATIC optimism magnitude of the borrowed ROS centre: the
mean predicted centre vs the mean realised canonical ROS over the decision-relevant pool at the band's
GRADE_WEEK. gap = predicted − realised; positive = the centre runs high (the optimism L3 flagged). This is
the substrate for a future SEASONAL auto-update of FORM_ANCHOR_W (re-fit the dial when a season resolves —
the optimism is a slow structural bias, so a season-cadence re-fit, not a twitchy weekly one; the loop
itself stays propose-and-Will-promotes).

Read-only over the FROZEN substrate + canonical answer key; append-only to the ledger (idempotent by
`gap_id` = season|scoring_key|as_of_week|code_version). Provenanced to the frozen L3 baseline (std instr 8)
— a measurement, never a fit; nothing is re-scored, no live number moves (the centre is read at λ=0).

Run: python3 -m application.data.corpus.backfill_center_gap [--seasons 2020 ... 2025]
"""
import argparse
import contextlib
import hashlib
import io

import polars as pl

from application.data import data_layer
from application.data.transforms import compute_ros_player_band as band
from application.data.transforms.backtest_ros_player_band import GRADE_WEEK, _canonical_actual
from application.data.corpus.tuner import baseline_provenance


def _quiet(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


def _gap_id(season: int, sk: str, as_of_week: int, code_version: str) -> str:
    return hashlib.sha1(f"{season}|{sk}|{as_of_week}|{code_version}".encode()).hexdigest()[:16]


def _season_gaps(season: int, prov: dict) -> list:
    """Per scoring_key of the matched cohort: mean borrowed centre (λ=0) vs mean realised canonical ROS over
    the in_calibrated_pool at GRADE_WEEK, and their gap. Reuses the shipped band (ros_center IS the borrowed
    centre at the shipped FORM_ANCHOR_W=0) + the canonical answer key."""
    manifest = data_layer.read_corpus_manifest()
    keys = (manifest.filter((pl.col("stratum") == "matched") & (pl.col("season") == season))
            ["scoring_key"].unique().to_list())
    rows = []
    for sk in sorted(keys):
        b = _quiet(lambda: band.compute(season, scoring_key=sk))
        fz = b.filter((pl.col("as_of_week") == GRADE_WEEK) & pl.col("in_calibrated_pool"))
        if not fz.height:
            continue
        cons = data_layer.read_projection_consensus(season, scoring_key=sk)
        max_proj_week = int(cons["week"].max())
        remaining = range(GRADE_WEEK + 1, max_proj_week + 1)
        truth = _canonical_actual(season, sk)
        preds, reals = [], []
        for r in fz.iter_rows(named=True):
            pid = r["sleeper_player_id"]
            preds.append(float(r["ros_center"]))
            reals.append(sum(truth.get((pid, wk), 0.0) for wk in remaining))
        if not preds:
            continue
        # Round predicted + realized first, then derive gap FROM the rounded values, so the invariant
        # gap == predicted − realized holds exactly (check_debias asserts it).
        pred_r = round(sum(preds) / len(preds), 4)
        real_r = round(sum(reals) / len(reals), 4)
        rows.append({
            "gap_id": _gap_id(season, sk, GRADE_WEEK, prov["code_version"]),
            "season": season, "scoring_key": sk, "as_of_week": GRADE_WEEK, "n_pool": len(preds),
            "predicted_center": pred_r, "realized": real_r, "gap": round(pred_r - real_r, 4),
            "asof_date": prov["config_version"], "code_version": prov["code_version"],
            "constants_hash": prov["constants_hash"],
        })
    return rows


def backfill(seasons) -> pl.DataFrame:
    prov = baseline_provenance()  # the frozen L3 baseline's stamps (std instr 8)
    rows = []
    for s in seasons:
        rows.extend(_season_gaps(s, prov))
    df = pl.DataFrame(rows)
    data_layer.write_center_gap(df)
    print(f"=== center-gap delta-tracking: {df.height} (season × scoring_key) rows "
          f"@ week {GRADE_WEEK}  (code_version {prov['code_version'][:12]}) ===")
    for r in df.sort("season", "scoring_key").iter_rows(named=True):
        print(f"  {r['season']} {r['scoring_key']:>5}: predicted {r['predicted_center']:7.2f}  "
              f"realized {r['realized']:7.2f}  gap {r['gap']:+7.2f}  (n={r['n_pool']})")
    print("  → snapshots/derived/ledger/center_gap.parquet  (append-only; positive gap = optimistic centre)")
    return df


def main():
    ap = argparse.ArgumentParser(description="Session 7 seasonal center-gap delta-tracking.")
    ap.add_argument("--seasons", nargs="+", type=int, default=[2020, 2021, 2022, 2023, 2024, 2025])
    a = ap.parse_args()
    backfill(a.seasons)


if __name__ == "__main__":
    main()
