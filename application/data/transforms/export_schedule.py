"""
Export Schedule — the pairing-only front-end seam for the Matchups surface (DATA_CONTRACT §4.3).

The Matchups slate is forward-looking: as-of week N it shows week N+1's head-to-head pairings with
*projected* totals (the app is a season replay frozen at 2025 wk4). The pairings — matchup_id groups
two rosters in a week — are known in advance and live in the weekly Sleeper matchup snapshots. But
those snapshots also carry each week's actual `points`, which must NOT reach the client: that would
leak the very future the replay is pretending not to know.

This transform stacks the snapshots (data_layer.read_season_matchups) and keeps ONLY
(week, roster_id, matchup_id) — `points` dropped — into one derived parquet the front end reads
through the queries.js seam. Pure reshape, no computation.

Output: snapshots/derived/schedule_{season}.parquet, one row per (week, roster_id).

Usage:
    python3 -m application.data.transforms.export_schedule --season 2025
"""

import argparse

import polars as pl

from application.data import data_layer


def compute(season: int) -> pl.DataFrame:
    return (
        data_layer.read_season_matchups(season)
        .select("week", "roster_id", "matchup_id")
        .sort("week", "matchup_id", "roster_id")
    )


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_schedule(df, season)
    n_weeks = df["week"].n_unique()
    print(f"  → snapshots/derived/schedule_{season}.parquet ({df.height} rows, {n_weeks} weeks; points dropped)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export the pairing-only schedule for the Matchups surface.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
