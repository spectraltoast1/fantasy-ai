"""
build_substrate.py — the NFL-substrate driver (Session 2).

Builds the scoring-scoped forward-prior spine the corpus harvest (Session 3) runs on:
`projection_consensus` then `ros_player_band`, for each standard scoring key × each backfilled season.
Consensus must precede the band (the band reads the consensus centres/spread). Idempotent — re-running
overwrites each scoring/season slice deterministically.

Prerequisites (NFL-global, already banked): `projections` 2020–2025, `nfl_stats`, `adp_preseason`, and
the per-held-out `adp_points_curve/holdout_{S}` (compute_adp_points_curve --all). The band's anchor read
requires holdout_S to exist for each season S it builds.

Scope: the MATCHED stratum's keys only — {ppr, half}. The generalization stratum's ~33 custom keys are
deferred to Session 3 (consensus is scoring-scoped, so 33 keys × 6 seasons is a compute multiplier for a
set you never tune on).

Usage:
    python3 -m application.data.transforms.build_substrate                       # {ppr,half} × 2020..2025
    python3 -m application.data.transforms.build_substrate --seasons 2020 2021   # subset of seasons
    python3 -m application.data.transforms.build_substrate --scoring-keys ppr    # subset of keys
"""

import argparse
import sys

from application.data.transforms import compute_projection_consensus, compute_ros_player_band

DEFAULT_SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]
DEFAULT_KEYS = ["ppr", "half"]


def run(seasons: list[int], scoring_keys: list[str]) -> None:
    for key in scoring_keys:
        for season in seasons:
            print(f"\n########## substrate: scoring={key}  season={season} ##########")
            compute_projection_consensus.run(season, scoring_key=key)
            compute_ros_player_band.run(season, scoring_key=key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build the NFL substrate (projection_consensus + ros_player_band) per scoring_key × season.")
    parser.add_argument("--seasons", type=int, nargs="+", default=DEFAULT_SEASONS)
    parser.add_argument("--scoring-keys", nargs="+", choices=["ppr", "half", "std"], default=DEFAULT_KEYS)
    args = parser.parse_args()
    run(args.seasons, args.scoring_keys)
    sys.exit(0)
