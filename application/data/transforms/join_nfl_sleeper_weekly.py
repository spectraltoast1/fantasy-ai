"""
Join NFL player stats (nflreadpy) with Sleeper matchup data for a given season + week.

Usage:
    python join_nfl_sleeper_weekly.py --season 2025 --week 4

Output:
    application/data/snapshots/weekly_joined/weekly_joined_{season}_w{week:02d}.parquet
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import data_layer

SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}


def _load_nfl_stats(season: int, week: int) -> pl.DataFrame:
    df = data_layer.read_nfl_stats(season)
    return df.filter(
        (pl.col("season") == season)
        & (pl.col("week") == week)
        & (pl.col("position").is_in(list(SKILL_POSITIONS)))
    )


def _parse_sleeper_matchups(season: int, week: int) -> pl.DataFrame:
    matchups = data_layer.read_sleeper_matchups(season, week)

    rows = []
    for row in matchups.iter_rows(named=True):
        roster_id = row["roster_id"]
        matchup_id = row["matchup_id"]
        roster_total_points = float(row["points"] or 0.0)

        try:
            players_points = json.loads(row["players_points"] or "{}")
        except (json.JSONDecodeError, TypeError):
            players_points = {}

        try:
            starters = set(json.loads(row["starters"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            starters = set()

        for player_id, pts in players_points.items():
            rows.append(
                {
                    "sleeper_player_id": player_id,
                    "roster_id": roster_id,
                    "matchup_id": matchup_id,
                    "sleeper_points": float(pts),
                    "is_starter": player_id in starters,
                    "roster_total_points": roster_total_points,
                }
            )

    if not rows:
        return pl.DataFrame(
            schema={
                "sleeper_player_id": pl.Utf8,
                "roster_id": pl.Int64,
                "matchup_id": pl.Int64,
                "sleeper_points": pl.Float64,
                "is_starter": pl.Boolean,
                "roster_total_points": pl.Float64,
            }
        )

    return pl.DataFrame(rows).with_columns(
        pl.col("sleeper_player_id").cast(pl.Utf8),
        pl.col("roster_id").cast(pl.Int64),
        pl.col("matchup_id").cast(pl.Int64),
        pl.col("sleeper_points").cast(pl.Float64),
        pl.col("is_starter").cast(pl.Boolean),
        pl.col("roster_total_points").cast(pl.Float64),
    )


def _derive_matchup_result(sleeper: pl.DataFrame) -> pl.DataFrame:
    # For each matchup_id, the roster with higher total points wins.
    # Ties are recorded as "L" for both (extremely rare in fantasy).
    winners = (
        sleeper.group_by("matchup_id")
        .agg(
            pl.col("roster_id")
            .sort_by("roster_total_points", descending=True)
            .first()
            .alias("winner_roster_id")
        )
    )
    return sleeper.join(winners, on="matchup_id", how="left").with_columns(
        pl.when(pl.col("roster_id") == pl.col("winner_roster_id"))
        .then(pl.lit("W"))
        .otherwise(pl.lit("L"))
        .alias("matchup_result")
    ).drop("winner_roster_id")


def _print_validation(joined: pl.DataFrame, nfl_row_count: int, season: int, week: int) -> None:
    print(f"\n=== Validation Report: season={season} week={week} ===")
    print(f"Row count: {len(joined)}")

    key_cols = ["player_display_name", "position", "fantasy_points", "matchup_result"]
    for col in key_cols:
        if col in joined.columns:
            null_count = joined[col].is_null().sum()
            null_rate = null_count / len(joined) if len(joined) > 0 else 0.0
            print(f"Null rate [{col}]: {null_rate:.1%} ({null_count}/{len(joined)})")

    distinct_teams = joined["team"].n_unique() if "team" in joined.columns else "N/A"
    distinct_positions = (
        sorted(joined["position"].drop_nulls().unique().to_list())
        if "position" in joined.columns
        else "N/A"
    )
    print(f"Distinct teams: {distinct_teams}")
    print(f"Distinct positions: {distinct_positions}")

    if nfl_row_count > 0:
        coverage = len(joined) / nfl_row_count
        print(
            f"Join coverage: {len(joined)}/{nfl_row_count} ({coverage:.1%})"
            " NFL skill-position players matched in Sleeper"
        )


def run(season: int, week: int) -> None:
    nfl = _load_nfl_stats(season, week)
    sleeper = _parse_sleeper_matchups(season, week)
    sleeper = _derive_matchup_result(sleeper)

    joined = nfl.join(sleeper, on="sleeper_player_id", how="inner")

    data_layer.write_join_nfl_sleeper_weekly(joined, season, week)
    _print_validation(joined, len(nfl), season, week)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Join NFL stats with Sleeper matchups.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()
    run(args.season, args.week)
