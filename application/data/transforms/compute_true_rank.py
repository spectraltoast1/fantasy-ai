"""
Compute True Rank — team roster strength from the borrowed ROS value (DECISION_READS.md §5, first half).

The team-level aggregation of the Value read (§4). For every team it answers the posture question
behind "am I actually good?": **how strong is this roster, independent of the record it's posted?**
Per design law 3 it borrows nothing new — it *re-aggregates* the Production VOR that already shipped
(the ros_value the §4 transform built from the projection substrate) over the league's lineup rules.

  - roster_strength: the sum of each team's **optimal-lineup** ros_value — fill the declared starting
    slots (QB / RB / WR / TE + FLEX) with the team's rostered players by ros_value, most-constrained
    slot first, and sum what the optimal starters project for the rest of the season. This is roster
    quality measured the way a lineup is actually set (slot-aware), not a raw roster-sum that would
    reward hoarding startable depth you can't play.
  - bench_value: the rostered ros_value **not** in the optimal lineup — the depth / trade-capital
    behind the starters, carried as evidence (a §6 Positional-Depth hint), not folded into the rank.
  - rank: 1 = strongest, dense-ranked within each as-of-week cohort. **Record-independent** — this
    reads no wins/standings; that tension (rank vs. record) is exactly what §5's posture read surfaces.
  - spectrum_pos: league-relative 0–1 marker (min strength → 0, max → 1) via the shared normaliser,
    the same idiom as team_form / team_leakage.

Tall over as_of_week like the three team/player analytics + Production VOR: Production VOR is already
resolved per (as_of_week, roster_id) with the roster taken as-of-N, so True Rank inherits roster-as-of-N
for free — it just groups VOR by (as_of_week, team) and runs the optimal-lineup pass. The roster (season
join behind VOR) is frozen at weeks 1–4, so N is bounded there; the ROS horizon runs to week 18.

**Design note — value, not WAR (§4/§5).** roster_strength is in ROS-projected-points units (the borrowed
centres summed), *not* a wins conversion; the rank is ordinal roster quality. The Phase-4 bracket-math
Monte Carlo (§5 full) is what turns this + the weekly-spread variance into playoff odds — not built here.

Output: snapshots/derived/true_rank_{season}.parquet, one row per (as_of_week, roster_id).

Usage:
    python compute_true_rank.py --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

_TRANSFORMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TRANSFORMS_DIR.parent))  # application/data → data_layer
sys.path.insert(0, str(_TRANSFORMS_DIR))          # transforms → _analytics
import data_layer
from _analytics import round1, spectrum_positions, expand_slots, optimal_lineup


def _team_strength(players: list, slots: list) -> dict:
    """Optimal-lineup roster strength for one team. `players` are that team's rostered entries as
    {position, ros_value}; `slots` the expanded starting slots. Returns roster_strength (sum of the
    optimal starters' ros_value), bench_value (rostered ros_value left over), and the two counts.

    Feeds ros_value in as the shared engine's `pts` so the greedy most-constrained-first fill
    maximises summed ROS value — the §5 'sum each team's optimal-lineup ROS value' definition."""
    pool = [{"_i": i, "position": p["position"], "pts": float(p["ros_value"])}
            for i, p in enumerate(players)]
    opt = optimal_lineup(pool, slots)
    started_i = {p["_i"] for p in opt["picks"]}
    bench = sum(p["pts"] for p in pool if p["_i"] not in started_i)
    return {
        "roster_strength": opt["total"],
        "bench_value": bench,
        "n_starters": len(opt["picks"]),
        "n_rostered": len(pool),
    }


def _rank_cohort(records: list) -> list:
    """Attach dense rank (1 = strongest) and a league-relative 0–1 spectrum_pos to one as-of-week
    cohort of team strength records (each a dict with roster_id + the _team_strength fields). Pure —
    the ranking rule lives here, the spectrum normaliser is shared."""
    order = sorted(records, key=lambda r: r["roster_strength"], reverse=True)
    rank_of = {}
    prev = None
    rank = 0
    for r in order:  # dense rank: ties share a rank, next distinct value increments by one
        if r["roster_strength"] != prev:
            rank += 1
            prev = r["roster_strength"]
        rank_of[r["roster_id"]] = rank
    positions = spectrum_positions([r["roster_strength"] for r in records])
    return [
        {**r, "rank": rank_of[r["roster_id"]], "spectrum_pos": pos}
        for r, pos in zip(records, positions)
    ]


def _compute_as_of(vor_slice: pl.DataFrame, slots: list, season: int, n: int) -> list:
    """True Rank rows for one as-of cutoff N: group the Production VOR slice by team, score each
    team's optimal-lineup ROS strength, then rank the cohort. Returns row dicts tagged as_of_week=N."""
    by_team = {}
    for row in vor_slice.iter_rows(named=True):
        by_team.setdefault(int(row["roster_id"]), []).append(
            {"position": row["position"], "ros_value": row["ros_value"]}
        )

    records = [{"roster_id": rid, **_team_strength(players, slots)}
               for rid, players in by_team.items()]
    ranked = _rank_cohort(records)

    return [
        {
            "season": season,
            "as_of_week": n,
            "roster_id": r["roster_id"],
            "roster_strength": round1(r["roster_strength"]),
            "bench_value": round1(r["bench_value"]),
            "n_starters": r["n_starters"],
            "n_rostered": r["n_rostered"],
            "rank": r["rank"],
            "spectrum_pos": r["spectrum_pos"],
        }
        for r in ranked
    ]


def compute(season: int) -> pl.DataFrame:
    vor = data_layer.read_production_vor(season, as_of_week="all").select(
        "as_of_week", "roster_id", "position", "ros_value"
    )
    slots = expand_slots(data_layer.read_lineup_slots(season).to_dicts())

    all_rows = []
    for n in sorted(vor["as_of_week"].unique().to_list()):
        all_rows.extend(_compute_as_of(vor.filter(pl.col("as_of_week") == n), slots, season, n))

    df = pl.DataFrame(all_rows).sort("as_of_week", "rank")
    max_week = int(df["as_of_week"].max())
    print(f"=== True Rank: season={season}  as_of_week 1..{max_week}  (rows={df.height}) ===")
    print(f"  week {max_week} roster strength (optimal-lineup ROS value, strongest first):")
    print(df.filter(pl.col("as_of_week") == max_week).select(
        "rank", "roster_id", "roster_strength", "bench_value", "n_rostered", "spectrum_pos"
    ))
    return df


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_true_rank(df, season)
    print(f"  → snapshots/derived/true_rank_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute True Rank from the borrowed ROS value (Production VOR).")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
