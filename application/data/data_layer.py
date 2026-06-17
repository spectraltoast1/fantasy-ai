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


# --- Sleeper Teams (roster_id → names) ---

def _sleeper_teams_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / f"teams_{season}.parquet"


def write_sleeper_teams(df: pl.DataFrame, season: int) -> None:
    """Write the roster_id → team/owner name map for a season (overwrite).

    Roster identities are effectively fixed once a season is frozen, so this is a
    single overwrite file per season rather than an appended time-series.
    """
    path = _sleeper_teams_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_sleeper_teams(season: int) -> pl.DataFrame:
    return pl.read_parquet(_sleeper_teams_path(season))


# --- Sleeper Roster Positions (league starting-lineup config) ---

def _roster_positions_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / f"roster_positions_{season}.parquet"


def write_roster_positions(df: pl.DataFrame, season: int) -> None:
    """Write the league's raw roster_positions slot list for a season (overwrite).

    One row per slot, in Sleeper's declared order (slot_index, slot). This is the
    source of truth straight from the league object — derive_lineup_slots shapes it
    into the starting skill-slot requirements the optimal-lineup calc consumes.
    Like team identities, league lineup config is fixed once a season is frozen, so
    this is a single overwrite file per season, not an appended time-series.
    """
    path = _roster_positions_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_roster_positions(season: int) -> pl.DataFrame:
    return pl.read_parquet(_roster_positions_path(season))


# --- Lineup Slots (derived starting skill-slot requirements) ---

def _lineup_slots_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / f"lineup_slots_{season}.parquet"


def write_lineup_slots(df: pl.DataFrame, season: int) -> None:
    """Write the derived starting skill-slot requirements for a season (overwrite).

    Output of transforms/derive_lineup_slots.py: one row per distinct starting slot
    type (slot, count, eligible) covering only slots a QB/RB/WR/TE can fill. Consumed
    by the front-end optimal-lineup ("perfect lineup") calculation.
    """
    path = _lineup_slots_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_lineup_slots(season: int) -> pl.DataFrame:
    return pl.read_parquet(_lineup_slots_path(season))


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


# --- Derived Analytics ---
# Pre-computed Team Overview analytics, promoted out of the front-end seam
# (queries.js) into polars transforms. Each is a single overwrite file per season
# (the analytics are a deterministic function of a frozen season's join output), so
# these mirror the lineup-slots pattern: one row per roster_id, derived columns the
# front end reads directly. When a server arrives, these become API endpoints that
# serve the same parquet — no JS math to port.

def _team_form_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"team_form_{season}.parquet"


def write_team_form(df: pl.DataFrame, season: int) -> None:
    """Write the per-team trajectory (form) analytics for a season (overwrite).

    Output of transforms/compute_team_form.py: one row per roster_id carrying the
    recency-weighted scoring slope, direction read, recent record, league-relative
    spectrum position, and the per-week series (serialised JSON).
    """
    path = _team_form_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_team_form(season: int) -> pl.DataFrame:
    return pl.read_parquet(_team_form_path(season))


def _team_leakage_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"team_leakage_{season}.parquet"


def write_team_leakage(df: pl.DataFrame, season: int) -> None:
    """Write the per-team lineup-leakage analytics for a season (overwrite).

    Output of transforms/compute_team_leakage.py: one row per roster_id carrying
    lineup efficiency %, season points left, the coachable-vs-variance split,
    league-relative spectrum position, and the per-week leak + named fixes
    (serialised JSON).
    """
    path = _team_leakage_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_team_leakage(season: int) -> pl.DataFrame:
    return pl.read_parquet(_team_leakage_path(season))


def _player_signal_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"player_signal_{season}.parquet"


def write_player_signal(df: pl.DataFrame, season: int) -> None:
    """Write the per-player spike signal-quality read for a season (overwrite).

    Output of transforms/compute_player_signal.py: one row per rostered skill player
    carrying the recent per-game production, the opportunity vs efficiency
    decomposition (opp_g, ppo, regression_risk), the TD share of scoring, a
    sample-gated categorical read, and the per-week points/opportunity series
    (serialised JSON). The first decision-critique engine slice ("is this production
    real, or noise?").
    """
    path = _player_signal_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_player_signal(season: int) -> pl.DataFrame:
    return pl.read_parquet(_player_signal_path(season))
