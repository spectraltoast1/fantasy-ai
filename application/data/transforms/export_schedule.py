"""
Export Schedule — the pairing-only front-end seam for the Matchups surface (DATA_CONTRACT §4.3).

The Matchups slate is forward-looking: as-of week N it shows week N+1's head-to-head pairings with
*projected* totals (the app is a season replay frozen at 2025 wk4). The pairings — matchup_id groups
two rosters in a week — are known in advance and live in the weekly Sleeper matchup snapshots. But
those snapshots also carry each week's actual `points`, which must NOT reach the client: that would
leak the very future the replay is pretending not to know.

This transform stacks the snapshots (data_layer.read_season_matchups) and keeps ONLY
(week, roster_id, matchup_id) — `points` dropped — plus a `league_id` column, into one derived
parquet the front end reads through the queries.js seam. Pure reshape, no computation.

League-scoped (Stage-B B1): `roster_id`/`matchup_id` are league-local, so the output is keyed per
league (path + column) like every other league-scoped derived read — two same-season leagues no
longer collide. Defaults to the is_mine league of the season.

Output: snapshots/derived/league/<league_id>/schedule_{season}.parquet, one row per (week, roster_id).

Usage:
    python3 -m application.data.transforms.export_schedule --season 2025
    python3 -m application.data.transforms.export_schedule --season 2025 --league-id 1207735666645946368
"""

import argparse

import polars as pl

from application.data import data_layer


def compute(season: int, league_id=None) -> pl.DataFrame:
    league_id = league_id or data_layer._active_league(season)[0]
    return (
        data_layer.read_season_matchups(season, league_id=league_id)
        .select("week", "roster_id", "matchup_id")
        .with_columns(pl.lit(str(league_id)).alias("league_id"))
        .select("league_id", "week", "roster_id", "matchup_id")
        .sort("week", "matchup_id", "roster_id")
    )


def run(season: int, league_id=None) -> None:
    league_id = league_id or data_layer._active_league(season)[0]
    df = compute(season, league_id=league_id)
    data_layer.write_schedule(df, season, league_id=league_id)
    n_weeks = df["week"].n_unique()
    print(f"  → snapshots/derived/league/{league_id}/schedule_{season}.parquet "
          f"({df.height} rows, {n_weeks} weeks; points dropped)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export the pairing-only schedule for the Matchups surface.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--league-id", type=str, default=None,
                        help="League to export (default: the is_mine league of the season).")
    args = parser.parse_args()
    run(args.season, league_id=args.league_id)
