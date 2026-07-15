"""
Two-way player flags for the corpus (Session 2.5, commit 3).

A "two-way" player is one the **pinned** Sleeper registry rosters at a SKILL position (QB/RB/WR/TE) but
whose nflreadpy stats are scored under a NON-skill position — Travis Hunter is the archetype: rostered at
WR, `nfl_stats` scores his CB line, so his `fantasy_points_ppr` come from defensive/return production.
Session 1.7 proved this is a standing hazard: the realized-ROS **answer key** for such a player scores the
WRONG position. The recorded decision (STATUS) is **FLAG, do not exclude** — the roster substrate keeps
them (the pinned-registry fix already makes their membership deterministic); this reference lets the
*scorer* (a later session) slice their cross-position points out.

Detection reuses the EXACT conflict `join_nfl_sleeper_weekly._apply_registry_eligibility` computes
(registry skill ∧ nfl_stats non-skill), filtered to material season production so the corpus flag is the
~4-6/season that actually reach a roster — not the ~28-37/season conflict tail (FBs / punters / fluke-TD
DBs that never matter).

Output: snapshots/corpus/corpus_two_way_flags.parquet — one row per (season, sleeper_player_id):
registry_position / nfl_stats_position / season_ppr.

Run: python3 -m application.data.corpus.two_way_flags
"""
import sys

import polars as pl

from application.data import data_layer

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]
SEASONS = list(range(2020, 2026))
# Material-production floor. 1.7 quantified ~28-37 conflict players/season, of which only ~4-6 score
# ≥20 pts (the rest are FBs/punters/fluke-TD DBs that never reach a fantasy roster). 20 PPR/season is the
# knee that isolates the answer-key hazard that actually matters.
MATERIAL_PPR = 20.0


def compute() -> pl.DataFrame:
    """The material two-way players per season, from the pinned registry × season-summed nfl_stats."""
    reg = data_layer.read_pinned_sleeper_players().select(
        "sleeper_player_id", pl.col("position").alias("registry_position")
    )
    frames = []
    for season in SEASONS:
        stats = (
            data_layer.read_nfl_stats(season)
            .filter(pl.col("sleeper_player_id").is_not_null())
            .sort("week")
            .group_by("sleeper_player_id", maintain_order=True)
            .agg(
                pl.col("fantasy_points_ppr").fill_null(0.0).sum().alias("season_ppr"),
                pl.col("position").drop_nulls().first().alias("nfl_stats_position"),
            )
        )
        joined = stats.join(reg, on="sleeper_player_id", how="left")
        # The two-way conflict — MIRRORS join_nfl_sleeper_weekly._apply_registry_eligibility (L336):
        # the pinned registry says SKILL, nflreadpy says NON-skill. Filtered to material production.
        two_way = (
            joined.filter(
                pl.col("registry_position").is_in(SKILL_POSITIONS)
                & pl.col("nfl_stats_position").is_not_null()
                & ~pl.col("nfl_stats_position").is_in(SKILL_POSITIONS)
                & (pl.col("season_ppr") >= MATERIAL_PPR)
            )
            .with_columns(pl.lit(season, dtype=pl.Int64).alias("season"))
            .select("season", "sleeper_player_id", "registry_position", "nfl_stats_position",
                    pl.col("season_ppr").round(1))
        )
        frames.append(two_way)
    return pl.concat(frames).sort(["season", "season_ppr"], descending=[False, True])


def run() -> None:
    df = compute()
    data_layer.write_corpus_two_way_flags(df)
    per_season = dict(sorted(df.group_by("season").len().sort("season").iter_rows()))
    print(f"=== corpus_two_way_flags: {df.height} rows (material two-way, ≥{MATERIAL_PPR} PPR) ===")
    print(f"  per season: {per_season}")
    print(df.head(20))
    print("  → snapshots/corpus/corpus_two_way_flags.parquet")


if __name__ == "__main__":
    run()
    sys.exit(0)
