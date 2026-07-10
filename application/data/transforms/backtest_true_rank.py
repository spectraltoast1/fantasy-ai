"""
Backtest True Rank against the full-2025 answer key.

The gate True Rank (DECISION_READS.md §5, first half) must clear before it drives any posture
surface: does the roster-strength read actually rank teams by rest-of-season *quality*? True Rank
sums each team's optimal-lineup ROS value from the borrowed projection, so the honest test is
whether that projected roster strength tracks what the roster really produced. Two verdicts
(exit 0 iff both pass):

  - **Predictive** — across teams, does projected `roster_strength` correlate with each team's
    **actual** rest-of-season optimal-lineup production (the roster's realized ceiling, summed over
    the remaining weeks)? Reported as Pearson (magnitude) AND Spearman (the read is a *ranking*).
    Actual is the *management-independent* ceiling — optimal lineup set each week on realized points
    — so it isolates roster quality (the thing True Rank measures) from lineup-setting skill (which
    is leakage's domain, §not this read). Threshold: corr ≥ CORR_MIN at the freeze week.
  - **Decision-relevant** — split teams into the strong vs. weak half by projected rank and confirm
    the strong half's mean actual ROS clearly exceeds the weak half's. This is the "you're better
    than your record" claim True Rank makes, tested the way backtest_production_vor tests VOR tiers
    (halved because the per-week team n is ~10).

It imports the SAME pure functions the transform ships (`_team_strength`, `expand_slots`,
`optimal_lineup`) — what's validated is exactly what serves the read, no re-derivation. Roster
membership as-of-N + positions come straight from the Production VOR slice (roster-as-of-N already
resolved there); actual weekly points come from the nfl_stats answer key.

**Small-sample honesty (documented, not hidden):** this league is 10 teams, so the primary gate is
the **freeze-week** snapshot (latest as-of N → longest real ROS), the most decision-relevant read
("as of now, is this roster good?"). The pooled-over-all-weeks correlation is reported as *evidence*
only — the same team at N=1..4 isn't independent, so pooling inflates n without adding independent
signal.

Usage:
    python -m application.data.transforms.backtest_true_rank --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import mean, pearson, expand_slots, optimal_lineup
from application.data.transforms.compute_true_rank import _team_strength

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# Minimum freeze-week correlation between projected roster_strength and actual ROS ceiling.
CORR_MIN = 0.60


def _rankdata(xs):
    """Ordinal ranks (average rank for ties) — for Spearman via pearson-on-ranks."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # 1-based average rank across the tie block
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs, ys):
    return pearson(_rankdata(xs), _rankdata(ys))


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


def _actual_strength(players: list, remaining: list, slots: list, actual: dict) -> float:
    """A team's realized ROS ceiling: for each remaining week set the optimal lineup on that week's
    actual points, sum. Management-independent (perfect hindsight lineup) so it measures roster
    quality, not lineup-setting skill. `players` are {sleeper_player_id, position} rostered as-of-N."""
    total = 0.0
    for wk in remaining:
        pool = [
            {"_i": i, "position": p["position"], "pts": actual.get((p["sleeper_player_id"], wk), 0.0)}
            for i, p in enumerate(players)
        ]
        total += optimal_lineup(pool, slots)["total"]
    return total


def _test_points(season: int):
    """One row per (as_of_week N, roster_id): projected roster_strength (shipped pure path) + the
    actual ROS ceiling over the same remaining weeks. Returns (rows, freeze_week)."""
    vor = data_layer.read_production_vor(season, as_of_week="all").select(
        "as_of_week", "roster_id", "sleeper_player_id", "position", "ros_value"
    )
    slots = expand_slots(data_layer.read_lineup_slots(season).to_dicts())
    actual = _actual_weekly(season)

    weeks = sorted(vor["as_of_week"].unique().to_list())
    freeze = max(weeks)
    max_proj_week = int(max(k[1] for k in actual)) if actual else freeze

    rows = []
    for n in weeks:
        remaining = list(range(n + 1, max_proj_week + 1))
        if not remaining:
            continue
        vslice = vor.filter(pl.col("as_of_week") == n)
        by_team = {}
        for r in vslice.iter_rows(named=True):
            by_team.setdefault(int(r["roster_id"]), []).append(r)
        for rid, plist in by_team.items():
            projected = _team_strength(
                [{"position": p["position"], "ros_value": p["ros_value"]} for p in plist], slots
            )["roster_strength"]
            act = _actual_strength(
                [{"sleeper_player_id": p["sleeper_player_id"], "position": p["position"]} for p in plist],
                remaining, slots, actual,
            )
            rows.append({"as_of_week": n, "roster_id": rid,
                         "projected": projected, "actual": act})
    return rows, freeze


def run(season: int) -> bool:
    rows, freeze = _test_points(season)
    tp = pl.DataFrame(rows)
    print(f"=== True Rank backtest: season={season}  test points={tp.height} "
          f"(team × as-of week; freeze week={freeze}) ===")

    # 1. Predictive — freeze-week corr(projected roster_strength, actual ROS ceiling).
    fz = tp.filter(pl.col("as_of_week") == freeze)
    pj, ac = fz["projected"].to_list(), fz["actual"].to_list()
    r_p = pearson(pj, ac)
    r_s = _spearman(pj, ac)
    corr_ok = r_p is not None and r_s is not None and r_p >= CORR_MIN and r_s >= CORR_MIN
    print()
    print(f"  predictive (freeze week {freeze}, n={fz.height} teams; min {CORR_MIN:.2f}):")
    print(f"    Pearson  corr(projected, actual ROS ceiling) = {r_p:.3f}  {'PASS' if r_p and r_p >= CORR_MIN else 'FAIL'}")
    print(f"    Spearman rank corr                            = {r_s:.3f}  {'PASS' if r_s and r_s >= CORR_MIN else 'FAIL'}")
    # Evidence (not gated): pooled over all as-of weeks (non-independent — inflates n).
    r_pool = _spearman(tp["projected"].to_list(), tp["actual"].to_list())
    print(f"    [evidence] pooled Spearman over weeks 1..{freeze} (n={tp.height}, non-indep) = {r_pool:.3f}")

    # 2. Decision-relevant — strong vs weak half by projected rank → actual ceiling separates.
    #    Aggregate the per-week half means so each as-of snapshot contributes equally.
    strong_all, weak_all = [], []
    for (n,), g in tp.group_by("as_of_week"):
        gg = g.sort("projected", descending=True)
        half = gg.height // 2
        strong_all += gg.head(half)["actual"].to_list()
        weak_all += gg.tail(gg.height - half)["actual"].to_list()
    strong_m, weak_m = mean(strong_all), mean(weak_all)
    separates = strong_m > weak_m
    print()
    print(f"  decision-relevant: mean ACTUAL ROS ceiling, strong vs weak half by projected rank")
    print(f"    (per-week split, pooled): strong {strong_m:.1f}  >  weak {weak_m:.1f}  "
          f"(+{strong_m - weak_m:.1f})   {'PASS' if separates else 'FAIL'}")

    ok = corr_ok and separates
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — projected roster strength "
          f"{'tracks' if corr_ok else 'does NOT track'} the actual ROS ceiling at the freeze "
          f"(≥{CORR_MIN:.2f} both corrs); strong half {'out-produces' if separates else 'does NOT out-produce'} the weak half.")
    return ok


def __main():
    parser = argparse.ArgumentParser(description="Backtest True Rank against the 2025 answer key.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    sys.exit(0 if run(args.season) else 1)


if __name__ == "__main__":
    __main()
