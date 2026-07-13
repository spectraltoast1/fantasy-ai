"""
Compute ROS League View — the league-scoped, roster-relative half of §2 ROS Outcome Shape.

L0 keying (audit S3.2) split the old `ros_outcome_shape` into two entities. This is the half that
DEPENDS on the roster: per (as_of_week, roster_id, player) the league-relative bull spectrum position
within the player's position cohort, plus the structured situation/security evidence carried through
from compute_player_signal. Roster membership makes it LEAGUE-scoped. The roster-free bull/bear band
lives in compute_ros_player_band.py; joined on sleeper_player_id the two reconstitute the old frame
(the reconstruction is the L0 no-regression oracle — see backtest_l0_keying.py).

Borrows, does not rebuild:
  - roster membership + position from Production VOR's rostered slice (roster-as-of-N inherited).
  - the bull ceiling (ros_bull) from ros_player_band, for the league-relative spectrum.
  - security tier + trust axis (direction / reliability) from compute_player_signal — carried as
    evidence, not fused into a score (laws 2 + 4). A rostered player absent from the signal slice
    reads security="unknown" (the pre-split default), direction/reliability = null.

`spectrum_pos` reproduces the pre-split computation exactly: within each (as_of_week, position) cohort of
ROSTERED players, `_analytics.spectrum_positions` maps ros_bull to a 0–1 league-relative position
(min→0, max→1; a flat cohort → 0.5), rounded to 3 dp — a pure function of the cohort's ros_bull multiset,
so the window form below is order-independent.

Tall over as_of_week (default = latest). Output:
snapshots/derived/league/<league_id>/ros_league_view_{season}.parquet.

Usage:
    python3 -m application.data.transforms.compute_ros_league_view --season 2025
"""

import argparse
import sys

import polars as pl

from application.data import data_layer


def compute(season: int) -> pl.DataFrame:
    # Rostered players (roster-as-of-N) + their position, from Production VOR.
    vor = data_layer.read_production_vor(season, as_of_week="all").select(
        "season", "as_of_week", "roster_id", "sleeper_player_id", "position"
    )
    # The bull ceiling for the league-relative spectrum, from the scoring-scoped band.
    band = data_layer.read_ros_player_band(season, as_of_week="all").select(
        "as_of_week", "sleeper_player_id", "ros_bull"
    )
    # Situation/security evidence, from the player-signal trust axis. `_sig` marks a present row so a
    # rostered player ABSENT from the slice reads security="unknown" (matching the pre-split sig.get
    # default) while a present-but-null security is preserved.
    signal = data_layer.read_player_signal(season, as_of_week="all").select(
        "as_of_week", "sleeper_player_id", "security", "direction", "reliability"
    ).with_columns(pl.lit(True).alias("_sig"))

    joined = (
        vor.join(band, on=["as_of_week", "sleeper_player_id"], how="left")
           .join(signal, on=["as_of_week", "sleeper_player_id"], how="left")
    )

    lo = pl.col("ros_bull").min().over(["as_of_week", "position"])
    hi = pl.col("ros_bull").max().over(["as_of_week", "position"])
    df = joined.with_columns(
        pl.when(pl.col("_sig").is_null()).then(pl.lit("unknown"))
          .otherwise(pl.col("security")).alias("security"),
        pl.when((hi - lo) == 0).then(pl.lit(0.5))
          .otherwise((pl.col("ros_bull") - lo) / (hi - lo)).round(3).alias("spectrum_pos"),
    ).select(
        "season", "as_of_week", "roster_id", "sleeper_player_id", "position",
        "spectrum_pos", "security", "direction", "reliability",
    ).sort("as_of_week", "roster_id", "spectrum_pos", descending=[False, False, True])

    freeze = int(df["as_of_week"].max())
    latest = df.filter(pl.col("as_of_week") == freeze)
    print(f"=== ROS League View: season={season}  as_of_week 1..{freeze}  (rows={df.height}) ===")
    print(f"  week {freeze} top spectrum (league-relative bull ceiling):")
    print(latest.head(6).select("roster_id", "sleeper_player_id", "position", "spectrum_pos", "security"))
    flagged = latest.filter(pl.col("security") != "stable").height
    print(f"  week {freeze} situation-flagged (security != stable): {flagged} of {latest.height}")
    return df


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_ros_league_view(df, season)   # league-scoped; defaults to the is_mine league
    lid = data_layer._active_league(season)[0]
    print(f"  → snapshots/derived/league/{lid}/ros_league_view_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute the ROS league view (league-scoped §2 half).")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
    sys.exit(0)
