"""
Backtest Positional Depth against the full-2025 answer key.

The gate Positional Depth (DECISION_READS.md §6) must clear before it drives any trade/waiver
surface. §6 is a finer re-slice of the already-gated Production VOR, so the honest question is
whether the **per-position** strength claim carries real signal — not just that VOR does in
aggregate. Two verdicts (exit 0 iff both pass):

  - **Predictive** — per position, does projected `starter_value` (the top-need players by borrowed
    ros_value) correlate with each team's **actual** rest-of-season starter ceiling at that position
    (the top-need players by *realized* points over the remaining weeks — management-independent, the
    same "optimal deployment" answer key True Rank uses)? Reported per position; gate on the mean
    across positions (each position n≈10 teams, so per-position is noisy — the mean is the honest
    aggregate, per-position printed for transparency).
  - **Decision-relevant** — within each (position, week) cohort, split teams into the top vs. bottom
    half by projected `starter_value` and confirm the top half's actual starter ceiling out-produces
    the bottom half's. This is the "surplus = real depth, gap = real hole" claim, tested the way
    backtest_true_rank tests strong-vs-weak roster halves.

Imports the SAME pure functions the transform ships (`_position_depth`, `_starter_needs`) — no
re-derivation. Roster-as-of-N + positions come from the Production VOR slice; actual weekly points
from the nfl_stats answer key. Small-sample honesty (10-team league): the freeze week is the primary
read, the pooled-over-weeks correlation is reported as evidence only.

Usage:
    python -m application.data.transforms.backtest_positional_depth --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import mean, pearson
from application.data.transforms.compute_positional_depth import SKILL_POSITIONS, _position_depth, _starter_needs

# Minimum mean-across-positions freeze-week correlation (projected starter_value vs actual ceiling).
CORR_MIN = 0.50


def _actual_weekly(season: int) -> dict:
    """(sleeper_player_id, week) → actual PPR points, the answer key for the realized ceiling."""
    df = (
        data_layer.read_nfl_stats(season)
        .filter(pl.col("position").is_in(SKILL_POSITIONS))
        .select("sleeper_player_id", pl.col("week").cast(pl.Int64), "fantasy_points_ppr")
        .drop_nulls("sleeper_player_id")
        .group_by("sleeper_player_id", "week")
        .agg(pl.col("fantasy_points_ppr").first().alias("actual"))
    )
    return {(r["sleeper_player_id"], r["week"]): float(r["actual"]) for r in df.iter_rows(named=True)}


def _actual_ceiling(players: list, need: int, remaining: list, actual: dict) -> float:
    """A team's realized ROS ceiling at a position: each rostered player's actual points summed over
    the remaining weeks, take the top-`need` (best realized deployment), sum. Management-independent —
    isolates positional roster quality from lineup-setting. `players` carry sleeper_player_id."""
    tot = sorted(
        (sum(actual.get((p["sleeper_player_id"], w), 0.0) for w in remaining) for p in players),
        reverse=True,
    )
    return sum(tot[:need])


def _test_points(season: int):
    """One row per (as_of_week N, roster_id, position): projected starter_value (shipped pure path) +
    the actual starter ceiling over the same remaining weeks. Returns (rows, freeze_week)."""
    vor = data_layer.read_production_vor(season, as_of_week="all").select(
        "as_of_week", "roster_id", "sleeper_player_id", "position", "ros_value", "vor"
    )
    needs = _starter_needs(data_layer.read_lineup_slots(season))
    actual = _actual_weekly(season)

    weeks = sorted(vor["as_of_week"].unique().to_list())
    freeze = max(weeks)
    max_proj_week = int(max(k[1] for k in actual)) if actual else freeze

    rows = []
    for n in weeks:
        remaining = list(range(n + 1, max_proj_week + 1))
        if not remaining:
            continue
        by_tp: dict = {}
        for r in vor.filter(pl.col("as_of_week") == n).iter_rows(named=True):
            by_tp.setdefault((int(r["roster_id"]), r["position"]), []).append(r)
        for (rid, pos), plist in by_tp.items():
            need = needs[pos]
            if need == 0:
                continue
            projected = _position_depth(
                [{"ros_value": p["ros_value"], "vor": p["vor"]} for p in plist], need
            )["starter_value"]
            ceiling = _actual_ceiling(plist, need, remaining, actual)
            rows.append({"as_of_week": n, "roster_id": rid, "position": pos,
                         "projected": projected, "actual": ceiling})
    return pl.DataFrame(rows), freeze


def run(season: int) -> bool:
    tp, freeze = _test_points(season)
    print(f"=== Positional Depth backtest: season={season}  test points={tp.height} "
          f"(team × position × as-of week; freeze week={freeze}) ===")

    # 1. Predictive — per-position freeze-week corr(projected starter_value, actual ceiling).
    fz = tp.filter(pl.col("as_of_week") == freeze)
    print()
    print(f"  predictive (freeze week {freeze}; corr projected starter_value vs actual ROS ceiling):")
    per_pos = {}
    for pos in SKILL_POSITIONS:
        g = fz.filter(pl.col("position") == pos)
        r = pearson(g["projected"].to_list(), g["actual"].to_list())
        per_pos[pos] = r
        print(f"    {pos:<3} n={g.height:<3} corr={r if r is None else round(r, 3)}")
    vals = [r for r in per_pos.values() if r is not None]
    mean_corr = mean(vals) if vals else 0.0
    corr_ok = len(vals) == len(SKILL_POSITIONS) and mean_corr >= CORR_MIN
    print(f"    mean across positions = {mean_corr:.3f}  (min {CORR_MIN:.2f})  {'PASS' if corr_ok else 'FAIL'}")
    # Evidence (not gated): pooled Spearman over all weeks (non-independent — inflates n).
    pooled = tp
    r_pool = pearson(pooled["projected"].to_list(), pooled["actual"].to_list())
    print(f"    [evidence] pooled Pearson over all (pos × team × week), n={pooled.height} = {r_pool:.3f}")

    # 2. Decision-relevant — per (position, week) top vs bottom half by projected → actual separates.
    top_all, bot_all = [], []
    for (pos, n), g in tp.group_by("position", "as_of_week"):
        gg = g.sort("projected", descending=True)
        half = gg.height // 2
        top_all += gg.head(half)["actual"].to_list()
        bot_all += gg.tail(gg.height - half)["actual"].to_list()
    top_m, bot_m = mean(top_all), mean(bot_all)
    separates = top_m > bot_m
    print()
    print(f"  decision-relevant: mean ACTUAL positional ceiling, top vs bottom half by projected")
    print(f"    (per position×week split, pooled): top {top_m:.1f}  >  bottom {bot_m:.1f}  "
          f"(+{top_m - bot_m:.1f})   {'PASS' if separates else 'FAIL'}")

    ok = corr_ok and separates
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — projected positional strength "
          f"{'tracks' if corr_ok else 'does NOT track'} the actual ceiling per position "
          f"(mean ≥{CORR_MIN:.2f}); surplus-side halves {'out-produce' if separates else 'do NOT out-produce'} gap-side.")
    return ok


def __main():
    parser = argparse.ArgumentParser(description="Backtest Positional Depth against the 2025 answer key.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    sys.exit(0 if run(args.season) else 1)


if __name__ == "__main__":
    __main()
