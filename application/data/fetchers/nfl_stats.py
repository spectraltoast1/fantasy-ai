"""
nflreadpy fetcher — player-week snapshots and player ID mapping.

Public API:
    backfill(year)  — pull full season for a given year and write parquet
    refresh()       — pull the most recently completed week of the current season
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import nflreadpy
import polars as pl

_HERE = Path(__file__).resolve().parent       # .../application/data/fetchers/
_DATA_DIR = _HERE.parent                      # .../application/data/
SNAPSHOT_DIR = _DATA_DIR / "snapshots" / "nflreadpy"
CACHE_DIR = _DATA_DIR / "cache"
PLAYER_ID_MAP_PATH = CACHE_DIR / "player_id_map.parquet"


def _snapshot_path(year: int) -> Path:
    return SNAPSHOT_DIR / f"nfl_stats_{year}.parquet"


def _build_player_id_map() -> pl.DataFrame:
    """Load ff_playerids, write player_id_map.parquet, return the DataFrame."""
    df = nflreadpy.load_ff_playerids()
    df = (
        df
        .select(["gsis_id", "sleeper_id", "pfr_id"])
        .filter(pl.col("gsis_id").is_not_null())
        .with_columns(pl.col("sleeper_id").cast(pl.Utf8).alias("sleeper_player_id"))
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.write_parquet(PLAYER_ID_MAP_PATH)
    print(f"  Player ID map: {len(df)} rows → {PLAYER_ID_MAP_PATH}")
    return df


def _load_player_stats(year: int) -> pl.DataFrame:
    df = nflreadpy.load_player_stats(year, summary_level="week")
    return df.filter(pl.col("season_type") == "REG")


def _load_snap_pct(year: int) -> pl.DataFrame:
    """Return (gsis_id, week, snap_pct) via pfr_id join."""
    snaps = nflreadpy.load_snap_counts(year).filter(pl.col("game_type") == "REG")
    ids = (
        nflreadpy.load_ff_playerids()
        .select(["pfr_id", "gsis_id"])
        .filter(pl.col("pfr_id").is_not_null() & pl.col("gsis_id").is_not_null())
    )
    return (
        snaps
        .join(ids, left_on="pfr_player_id", right_on="pfr_id", how="left")
        .select(["gsis_id", "week", "offense_pct"])
        .rename({"offense_pct": "snap_pct"})
        .filter(pl.col("gsis_id").is_not_null())
    )


def _load_team_rates(year: int) -> pl.DataFrame:
    """Return (team, week, team_pass_rate, team_rush_rate)."""
    df = nflreadpy.load_team_stats(year, summary_level="week").filter(
        pl.col("season_type") == "REG"
    )
    total = pl.col("attempts") + pl.col("carries")
    return df.with_columns([
        (pl.col("attempts") / total).alias("team_pass_rate"),
        (pl.col("carries") / total).alias("team_rush_rate"),
    ]).select(["team", "week", "team_pass_rate", "team_rush_rate"])


def _fetch_and_save(year: int, week: int | None = None) -> None:
    """Core assembly: join all sources, derive columns, write parquet."""
    print(f"  Loading player stats ({year}" + (f" week {week}" if week else "") + ")...")
    stats = _load_player_stats(year)
    if week is not None:
        stats = stats.filter(pl.col("week") == week)

    print("  Building player ID map...")
    id_map = _build_player_id_map()

    stats = stats.join(
        id_map.select(["gsis_id", "sleeper_player_id"]),
        left_on="player_id", right_on="gsis_id", how="left",
    )

    print("  Loading snap counts...")
    snaps = _load_snap_pct(year)
    if week is not None:
        snaps = snaps.filter(pl.col("week") == week)
    stats = stats.join(snaps, left_on=["player_id", "week"], right_on=["gsis_id", "week"], how="left")

    print("  Loading team stats...")
    rates = _load_team_rates(year)
    if week is not None:
        rates = rates.filter(pl.col("week") == week)
    stats = stats.join(rates, on=["team", "week"], how="left")

    stats = stats.with_columns([
        (pl.col("receiving_air_yards") / pl.col("targets").replace(0, None)).alias("adot"),
        pl.lit(datetime.now(timezone.utc).replace(tzinfo=None)).alias("fetched_at"),
    ])

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _snapshot_path(year)

    if out_path.exists() and week is not None:
        existing = pl.read_parquet(out_path)
        existing = existing.filter(pl.col("week") != week)
        stats = pl.concat([existing, stats], how="diagonal")

    stats.write_parquet(out_path)
    print(f"  Wrote {len(stats)} rows → {out_path}")


def backfill(year: int) -> None:
    """Pull the full season for a given year and write to snapshots."""
    print(f"Backfilling {year}...")
    _fetch_and_save(year)
    print(f"Backfill complete for {year}.")


def refresh() -> None:
    """Pull the most recently completed week of the current season."""
    year = nflreadpy.get_current_season()
    print(f"Detecting most recent REG week for {year}...")
    df = nflreadpy.load_player_stats(year, summary_level="week").filter(
        pl.col("season_type") == "REG"
    )
    if df.is_empty():
        print(f"No REG season data available for {year}. Nothing to refresh.")
        return
    week = df["week"].max()
    print(f"Refreshing {year} week {week}...")
    _fetch_and_save(year, week=week)
    print(f"Refresh complete ({year} week {week}).")


if __name__ == "__main__":
    usage = "Usage: nfl_stats.py backfill <year> | nfl_stats.py refresh"
    if len(sys.argv) < 2:
        print(usage)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "backfill":
        if len(sys.argv) < 3:
            print(usage)
            sys.exit(1)
        backfill(int(sys.argv[2]))
    elif cmd == "refresh":
        refresh()
    else:
        print(usage)
        sys.exit(1)
