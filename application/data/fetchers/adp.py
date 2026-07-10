"""
Preseason ADP fetcher — FantasyPros consensus rankings via nflreadpy.

The preseason-limits source for the §2 ROS bull/bear anchor (DECISION_READS.md §2). Pulls
nflreadpy.load_ff_rankings("all") — FantasyPros' full weekly-scraped ranking history — and keeps,
per season, the **latest August (pre-kickoff) redraft-overall snapshot**: the market's final
preseason view before the season drifts it. That gives a fixed preseason anchor per player
(ecr = consensus draft rank, best/worst = the expert rank range, sd) that the historical
rank->points curve (compute_adp_points_curve.py) turns into realized floor/center/ceiling points.

`load_ff_rankings` rows carry `id` = the FantasyPros player id; the sleeper bridge is
`id` -> ff_playerids.fantasypros_id -> sleeper_id (verified ~445/446 skill players; the cbs_id /
yahoo_id columns on ff_rankings are all-null and must NOT be used). Player ids land as the same
str sleeper_player_id every other join in the data layer uses.

Public API:
    backfill(seasons=None)  — default backfills 2020..current; writes one season slice at a time.

Usage:
    python -m application.data.fetchers.adp backfill            # 2020..current
    python -m application.data.fetchers.adp backfill 2025       # a single season
"""

import sys

import nflreadpy
import polars as pl

# All snapshot I/O goes through the data layer — the fetcher constructs no paths.
from application.data import data_layer

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]
# Redraft-overall ranking type (vs dynasty `do` / superflex `rsf`): format-matched to a redraft
# league, the same format-match discipline the §4 market read and §7 comparables apply.
_REDRAFT_OVERALL = "ro"
# First season with dependable preseason coverage in load_ff_rankings("all").
_FIRST_SEASON = 2020
# A preseason snapshot must have at least this many skill players to count as a full draft board —
# some late-August scrapes captured only IDP positions (skill board absent), so "latest date" alone
# picks a junk snapshot. Full boards run 400+; an IDP-only scrape is 0.
_MIN_SKILL_BOARD = 150


def _build_bridge() -> pl.DataFrame:
    """FantasyPros id -> sleeper_player_id, from ff_playerids (the only working ADP bridge).

    Returns (id, sleeper_player_id) with id the str FantasyPros id (matches ff_rankings.`id`)
    and sleeper_player_id the str sleeper id (matches every other data-layer join).
    """
    return (
        nflreadpy.load_ff_playerids()
        .select(
            pl.col("fantasypros_id").cast(pl.Utf8).alias("id"),
            pl.col("sleeper_id").cast(pl.Utf8).alias("sleeper_player_id"),
        )
        .filter(pl.col("id").is_not_null() & pl.col("sleeper_player_id").is_not_null())
        .unique(subset=["id"])
    )


def _preseason_skill_board(rankings: pl.DataFrame, season: int) -> pl.DataFrame:
    """`season`'s redraft-overall skill rankings across the preseason window (Jul 1 .. Sep 8),
    one clean row per (scrape_date, id). The snapshot-date choice reads off this frame so the
    skill-board filter and the date filter can't disagree."""
    prefix = str(season)
    return (
        rankings.filter(
            (pl.col("ecr_type") == _REDRAFT_OVERALL)
            & (pl.col("pos").is_in(SKILL_POSITIONS))
            & (pl.col("scrape_date") >= f"{prefix}-07-01")
            & (pl.col("scrape_date") <= f"{prefix}-09-08")
        )
        .select(
            "scrape_date",
            pl.col("id").cast(pl.Utf8),
            pl.col("pos").alias("position"),
            pl.col("ecr").cast(pl.Float64),
            pl.col("best").cast(pl.Float64),
            pl.col("worst").cast(pl.Float64),
            pl.col("sd").cast(pl.Float64),
        )
        .filter(pl.col("ecr").is_not_null())
        .unique(subset=["scrape_date", "id"])
    )


def _preseason_snapshot_date(board: pl.DataFrame) -> str | None:
    """The latest preseason scrape_date carrying a **full skill board** (>= _MIN_SKILL_BOARD players)
    — some late-August scrapes captured only IDP positions, so a bare max(date) picks a junk snapshot.
    Returns None if no snapshot clears the bar."""
    counts = board.group_by("scrape_date").agg(pl.len().alias("n")).filter(pl.col("n") >= _MIN_SKILL_BOARD)
    return counts["scrape_date"].max() if counts.height else None


def _extract_season(rankings: pl.DataFrame, bridge: pl.DataFrame, season: int) -> pl.DataFrame | None:
    """One season's preseason ADP slice: pick the latest full-board pre-kickoff snapshot, bridge to
    sleeper, derive positional ECR rank. Returns None if the season is uncovered."""
    board = _preseason_skill_board(rankings, season)
    date = _preseason_snapshot_date(board)
    if date is None:
        return None

    snap = board.filter(pl.col("scrape_date") == date).drop("scrape_date")
    n_pool = snap.height

    joined = snap.join(bridge, on="id", how="left")
    unmatched = joined.filter(pl.col("sleeper_player_id").is_null())
    matched = joined.filter(pl.col("sleeper_player_id").is_not_null())

    # Positional finish rank (1 = the position's top pick) from the consensus ECR, so the curve is
    # keyed on a stable per-position draft slot rather than an overall rank that conflates positions.
    out = matched.with_columns(
        pl.lit(season).alias("season"),
        pl.col("ecr").rank("ordinal").over("position").cast(pl.Int64).alias("pos_ecr_rank"),
    ).select(
        "season", "sleeper_player_id", "position", "ecr", "best", "worst", "sd", "pos_ecr_rank"
    )

    top = snap.sort("ecr").head(150)
    top_matched = top.join(bridge, on="id", how="left").filter(pl.col("sleeper_player_id").is_not_null()).height
    print(
        f"  {season} (snapshot {date}): {out.height}/{n_pool} skill players bridged "
        f"(top-150 by ecr: {top_matched}/150; unmatched {unmatched.height})"
    )
    return out


def backfill(seasons: list[int] | None = None) -> None:
    """Backfill preseason ADP for each season (default 2020..current). Loads the full ranking
    history and the id bridge once, then writes one season slice at a time (replace-by-season, so a
    partial run leaves completed seasons on disk and a re-run is idempotent)."""
    current = nflreadpy.get_current_season()
    if seasons is None:
        seasons = list(range(_FIRST_SEASON, current + 1))
    print(f"Backfilling preseason ADP for {seasons}...")
    print("  Loading load_ff_rankings('all') + id bridge...")
    rankings = nflreadpy.load_ff_rankings("all")
    bridge = _build_bridge()

    written = 0
    for season in seasons:
        slice_ = _extract_season(rankings, bridge, season)
        if slice_ is None or slice_.is_empty():
            print(f"  {season}: no preseason snapshot available — skipping.")
            continue
        data_layer.write_adp_preseason(slice_, season)
        written += 1
    print(f"Backfill complete — {written} season(s) → snapshots/nflreadpy/adp_preseason.parquet")


if __name__ == "__main__":
    usage = "Usage: python -m application.data.fetchers.adp backfill [season]"
    if len(sys.argv) < 2 or sys.argv[1] != "backfill":
        print(usage)
        sys.exit(1)
    seasons = [int(sys.argv[2])] if len(sys.argv) >= 3 else None
    backfill(seasons)
