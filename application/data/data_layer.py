from pathlib import Path

import polars as pl

_HERE = Path(__file__).resolve().parent
_SNAPSHOT_DIR = _HERE / "snapshots"
_CACHE_DIR = _HERE / "cache"


# --- Player ID Map ---

def read_player_id_map() -> pl.DataFrame:
    return pl.read_parquet(_CACHE_DIR / "player_id_map.parquet")


# --- NFL Stats ---

def read_nfl_stats(season: int) -> pl.DataFrame:
    return pl.read_parquet(_SNAPSHOT_DIR / "nflreadpy" / f"nfl_stats_{season}.parquet")


# --- Sleeper Matchups ---

def read_sleeper_matchups(season: int, week: int) -> pl.DataFrame:
    return pl.read_parquet(
        _SNAPSHOT_DIR / "sleeper" / str(season) / f"matchups_week_{week:02d}.parquet"
    )


# --- Join: NFL + Sleeper Weekly ---

def read_join_nfl_sleeper_weekly(season: int, week: int) -> pl.DataFrame:
    path = _SNAPSHOT_DIR / "nfl_sleeper_weekly_joined" / str(season) / f"weekly_joined_{season}_w{week:02d}.parquet"
    return pl.read_parquet(path)


def write_join_nfl_sleeper_weekly(df: pl.DataFrame, season: int, week: int) -> None:
    path = _SNAPSHOT_DIR / "nfl_sleeper_weekly_joined" / str(season) / f"weekly_joined_{season}_w{week:02d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
