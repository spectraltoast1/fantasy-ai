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

def _join_season_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "nfl_sleeper_weekly_joined" / f"season_{season}.parquet"


def read_join_season(season: int) -> pl.DataFrame:
    """Read the full season join file (all weeks)."""
    return pl.read_parquet(_join_season_path(season))


def read_join_nfl_sleeper_weekly(season: int, week: int) -> pl.DataFrame:
    """Read a single week's slice from the season join file."""
    return read_join_season(season).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
    )


def write_join_nfl_sleeper_weekly(df: pl.DataFrame, season: int, week: int) -> None:
    """Append a week's rows to the single season join file.

    `df` is treated as the complete set of rows for (season, week). If the
    season file already exists, any rows matching the (season, week) combo are
    dropped first (dedup guard) so re-running a week replaces it rather than
    duplicating. Otherwise the week's rows seed a new season file.
    """
    path = _join_season_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(
            ~((pl.col("season") == season) & (pl.col("week") == week))
        )
        df = pl.concat([existing, df])
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


# --- LeagueLogs Market Values ---

def _leaguelogs_market_path() -> Path:
    return _SNAPSHOT_DIR / "leaguelogs" / "market_values.parquet"


def read_leaguelogs_market() -> pl.DataFrame:
    """Read the full LeagueLogs market-value snapshot history (all dates, all profiles)."""
    return pl.read_parquet(_leaguelogs_market_path())


def leaguelogs_market_exists() -> bool:
    return _leaguelogs_market_path().exists()


def write_leaguelogs_market_snapshot(df: pl.DataFrame, snapshot_date) -> None:
    """Append one day's market snapshot (all profiles) to the single history file.

    `df` is treated as the complete set of rows for `snapshot_date`. If the file
    already exists, any rows for that date are dropped first (dedup guard), so a
    same-day re-run replaces the day rather than duplicating it. History for other
    dates is never touched — it cannot be re-fetched, so it is preserved.
    """
    path = _leaguelogs_market_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(pl.col("snapshot_date") != snapshot_date)
        df = pl.concat([existing, df])
    df.write_parquet(path)
