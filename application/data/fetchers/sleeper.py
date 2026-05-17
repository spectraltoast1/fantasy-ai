"""
Sleeper fetcher — league matchups, transactions, rosters, and bracket snapshots.

Public API:
    backfill(league_id, year)  — fetch all completed regular-season weeks, write parquet snapshots
    refresh(league_id)         — fetch current league state to cache and this week's data to snapshots
"""

import json
import sys
import time
from pathlib import Path

import polars as pl
import requests

_HERE = Path(__file__).resolve().parent        # .../application/data/fetchers/
_DATA_DIR = _HERE.parent                       # .../application/data/
SNAPSHOT_DIR = _DATA_DIR / "snapshots" / "sleeper"
CACHE_DIR = _DATA_DIR / "cache" / "sleeper"

_SLEEPER_BASE = "https://api.sleeper.app/v1"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_nfl_state() -> dict:
    resp = requests.get(f"{_SLEEPER_BASE}/state/nfl")
    resp.raise_for_status()
    return resp.json()


def _determine_completed_weeks(state: dict, year: int) -> int:
    """Return the number of completed regular-season weeks for the given year.

    Accounts for the offseason window where season_type is "offseason" but the
    season counter has not yet incremented — in that state the season is complete.
    """
    current_season = int(state["season"])

    if year < current_season:
        return 18                              # past season, fully complete

    if year > current_season:
        return 0                               # future season

    # year == current_season
    season_type = state.get("season_type", "")
    if season_type == "pre":
        return 0                               # season hasn't started yet
    if season_type == "regular":
        leg = int(state.get("leg", 0))
        return min(max(leg - 1, 0), 18)        # subtract 1: current week may be in progress
    # "post", "offseason", or anything else: regular season is complete
    return 18


def _write_json(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    print(f"  Wrote {path.name} → {path}")


def _write_parquet_from_list(data: list, path: Path, label: str) -> bool:
    if not data:
        print(f"  {label}: empty response from Sleeper (offseason or week not yet played) — skipping write.")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pl.from_dicts(data)
    df.write_parquet(path)
    print(f"  {label}: {len(df)} rows → {path}")
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def backfill(league_id: str, year: int) -> None:
    """Fetch all completed regular-season weeks and write parquet snapshots."""
    print(f"Backfilling Sleeper data for league {league_id} ({year})...")

    state = _get_nfl_state()
    completed_weeks = _determine_completed_weeks(state, year)
    print(f"  Completed weeks: {completed_weeks}")

    if completed_weeks == 0:
        print(f"  No completed weeks found for {year}. Nothing to backfill.")
        return

    for week in range(1, completed_weeks + 1):
        print(f"  Week {week}/{completed_weeks}...")

        resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/matchups/{week}")
        resp.raise_for_status()
        _write_parquet_from_list(
            resp.json(),
            SNAPSHOT_DIR / str(year) / f"matchups_week_{week:02d}.parquet",
            f"matchups week {week}",
        )

        resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/transactions/{week}")
        resp.raise_for_status()
        _write_parquet_from_list(
            resp.json(),
            SNAPSHOT_DIR / str(year) / f"transactions_week_{week:02d}.parquet",
            f"transactions week {week}",
        )

        time.sleep(0.5)

    print(f"Backfill complete for league {league_id} ({year}).")


def refresh(league_id: str) -> None:
    """Fetch current league state to cache and this week's data to snapshots."""
    print(f"Refreshing Sleeper data for league {league_id}...")

    state = _get_nfl_state()
    year = state["season"]
    week = int(state.get("leg", 0))
    print(f"  Current season: {year}, current week: {week}")

    # Cache files — current state only, overwritten each run
    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}")
    resp.raise_for_status()
    _write_json(resp.json(), CACHE_DIR / "league.json")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/users")
    resp.raise_for_status()
    _write_json(resp.json(), CACHE_DIR / "users.json")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/rosters")
    resp.raise_for_status()
    _write_json(resp.json(), CACHE_DIR / "rosters.json")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/winners_bracket")
    resp.raise_for_status()
    _write_json(resp.json(), CACHE_DIR / "winners_bracket.json")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/losers_bracket")
    resp.raise_for_status()
    _write_json(resp.json(), CACHE_DIR / "losers_bracket.json")

    # Current week snapshots — same path pattern as backfill
    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/matchups/{week}")
    resp.raise_for_status()
    _write_parquet_from_list(
        resp.json(),
        SNAPSHOT_DIR / str(year) / f"matchups_week_{week:02d}.parquet",
        f"matchups week {week}",
    )

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/transactions/{week}")
    resp.raise_for_status()
    _write_parquet_from_list(
        resp.json(),
        SNAPSHOT_DIR / str(year) / f"transactions_week_{week:02d}.parquet",
        f"transactions week {week}",
    )

    print(f"Refresh complete for league {league_id}.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    usage = "Usage: sleeper.py backfill <year> | sleeper.py refresh"

    if len(sys.argv) < 2:
        print(usage)
        sys.exit(1)

    cmd = sys.argv[1]

    # league_resolver lives in application/shared/ — insert application/ into sys.path
    sys.path.insert(0, str(_HERE.parent.parent))
    from shared import league_resolver

    if cmd == "backfill":
        if len(sys.argv) < 3:
            print(usage)
            sys.exit(1)
        _year = int(sys.argv[2])
        _league_id = league_resolver.resolve_league_id(_year)
        backfill(_league_id, _year)

    elif cmd == "refresh":
        _state = _get_nfl_state()
        _year = int(_state["season"])
        _league_id = league_resolver.resolve_league_id(_year)
        refresh(_league_id)

    else:
        print(usage)
        sys.exit(1)
