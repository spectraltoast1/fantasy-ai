from pathlib import Path

import polars as pl

_HERE = Path(__file__).resolve().parent
_SNAPSHOT_DIR = _HERE / "snapshots"
_CACHE_DIR = _HERE / "cache"


# --- Player ID Map ---

def read_player_id_map() -> pl.DataFrame:
    return pl.read_parquet(_CACHE_DIR / "player_id_map.parquet")


# --- Sleeper Players Registry ---

def read_sleeper_players() -> pl.DataFrame:
    """Read the cached Sleeper /players/nfl registry.

    Raises FileNotFoundError if fetch_players() has not been run yet.
    """
    path = _CACHE_DIR / "sleeper" / "players.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"Sleeper players cache not found at {path}. "
            "Run: python fetchers/sleeper.py fetch-players"
        )
    return pl.read_parquet(path)


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


# --- Join Remainders ---

def _remainders_path(season: int, week: int) -> Path:
    return _SNAPSHOT_DIR / "nfl_sleeper_weekly_joined" / str(season) / f"remainders_{season}_w{week:02d}.parquet"


def write_join_remainders(df: pl.DataFrame, season: int, week: int) -> None:
    """Write unresolved Sleeper players to a remainders file.

    An empty DataFrame written here signals a clean join with no unknowns.
    """
    path = _remainders_path(season, week)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_join_remainders(season: int, week: int) -> pl.DataFrame:
    path = _remainders_path(season, week)
    if not path.exists():
        raise FileNotFoundError(f"Remainders file not found: {path}")
    return pl.read_parquet(path)


def remainders_exist(season: int, week: int) -> bool:
    return _remainders_path(season, week).exists()
