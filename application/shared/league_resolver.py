"""
League resolver — resolves a Sleeper league ID from config for a given season year.

Public API:
    resolve_league_id(year)  — look up the user's leagues and return the matching league_id
"""

import sys
from pathlib import Path

import requests

_HERE = Path(__file__).resolve().parent        # .../application/shared/
sys.path.insert(0, str(_HERE.parent))          # .../application/ so "import config" resolves
import config


def resolve_league_id(year: int) -> str:
    """Return the Sleeper league_id matching config.SLEEPER_LEAGUE_ID for the given year."""
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
