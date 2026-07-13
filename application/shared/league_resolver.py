"""
League resolver — resolves the active Sleeper league for a season.

Public API:
    resolve_active(season)   — (league_id, scoring_key) for the is_mine league, from leagues.parquet
    resolve_league_id(year)  — the is_mine league_id for the year; registry-first, Sleeper-API fallback
"""

import polars as pl
import requests

from application import config
from application.data import data_layer


def resolve_active(season: int) -> tuple[str, str]:
    """(league_id, scoring_key) for the is_mine league in `season`, read from the league registry."""
    return data_layer._active_league(season)


def resolve_league_id(year: int) -> str:
    """The is_mine league_id for `year`.

    Registry-first (leagues.parquet, the single source of truth); falls back to the Sleeper API for a
    not-yet-onboarded league — the onboarding path, before the registry has been built for that year."""
    if data_layer.leagues_exists():
        df = data_layer.read_leagues().filter(pl.col("is_mine") & (pl.col("season") == year))
        if not df.is_empty():
            return str(df.row(0, named=True)["league_id"])
    return _resolve_via_api(year)


def _resolve_via_api(year: int) -> str:
    """Look up the user's Sleeper leagues and return the one matching config.SLEEPER_LEAGUE_ID."""
    username = config.SLEEPER_USERNAME
    target_id = config.SLEEPER_LEAGUE_ID

    print(f"Resolving Sleeper league for user '{username}' ({year})...")

    resp = requests.get(f"https://api.sleeper.app/v1/user/{username}")
    resp.raise_for_status()
    user_id = resp.json()["user_id"]
    print(f"  Sleeper user_id: {user_id}")

    resp = requests.get(f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{year}")
    resp.raise_for_status()
    leagues = resp.json()

    for league in leagues:
        if league["league_id"] == target_id:
            print(f"  Found league: {league['name']} ({league['league_id']})")
            return league["league_id"]

    found_ids = [l["league_id"] for l in leagues]
    raise ValueError(
        f"League {target_id!r} not found in {username}'s {year} leagues. "
        f"Found: {found_ids}"
    )
