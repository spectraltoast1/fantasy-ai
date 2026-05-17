"""
Stadium location data + NWS forecast stub.

The historical-weather download from datawithbliss has been removed — past weather
doesn't inform forward advisor decisions, only forecasts do. This module now does
two things:

  1. refresh_stadiums()  — one-time extract of stadium lat/lng + roof type from
                           datawithbliss's stadium_coordinates.csv (used as seed for
                           future NWS forecast lookups, and to short-circuit indoor
                           games where weather is irrelevant).
  2. refresh_forecast()  — STUB. NWS integration is a Phase 2 open question.
"""

import csv
import io
import json
import requests
from datetime import date

GITHUB_BASE = "https://raw.githubusercontent.com/ThompsonJamesBliss/WeatherData/master/data"
STADIUMS_URL = f"{GITHUB_BASE}/stadium_coordinates.csv"

STADIUMS_CACHE = "data/stadiums.json"
FORECAST_CACHE = "data/weather_forecast.json"

# Roof types that mean weather doesn't affect play
INDOOR_ROOF_TYPES = {"Indoor", "Dome"}
# Retractable roofs are usually closed — treat as sheltered unless noted
SHELTERED_ROOF_TYPES = {"Retractable"}


def _fetch_csv(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def refresh_stadiums():
    """Download stadium_coordinates.csv and cache a team → stadium lookup."""
    print("Fetching stadium data from datawithbliss...")
    rows = _fetch_csv(STADIUMS_URL)

    stadiums = {}
    for row in rows:
        team = row.get("HomeTeam", "").strip()
        roof = row.get("RoofType", "").strip()
        if not team:
            continue
        stadiums[team] = {
            "stadium": row.get("StadiumName", "").strip(),
            "roof_type": roof,
            "is_outdoor": roof == "Outdoor",
            "is_sheltered": roof in SHELTERED_ROOF_TYPES,
            "is_indoor": roof in INDOOR_ROOF_TYPES,
            "latitude": float(row["Latitude"]) if row.get("Latitude") else None,
            "longitude": float(row["Longitude"]) if row.get("Longitude") else None,
        }

    cache = {"updated_at": str(date.today()), "stadiums": stadiums}
    with open(STADIUMS_CACHE, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"  Cached {len(stadiums)} stadiums to {STADIUMS_CACHE}")
    return cache


def refresh_forecast():
    """STUB — NWS forecast integration deferred.

    Intended flow when implemented:
      1. Read current NFL state (week + season).
      2. Fetch the week's schedule (nfl_data_py).
      3. For each outdoor game (skip indoor/sheltered roofs), call NWS at the
         stadium's lat/lng, 24–72 hours before kickoff.
      4. Cache result at FORECAST_CACHE with 6h TTL.

    See PRODUCT_ROADMAP.md "Open Questions" for the V1-vs-V2 decision.
    """
    print("refresh_forecast: NWS integration not yet implemented (stub).")
    return None


def load_stadiums():
    try:
        with open(STADIUMS_CACHE) as f:
            return json.load(f).get("stadiums", {})
    except FileNotFoundError:
        return {}


def get_stadium_info(team_abbr):
    """Look up a team's stadium and weather exposure. Returns None if not found."""
    return load_stadiums().get(team_abbr)


if __name__ == "__main__":
    cache = refresh_stadiums()
    print("\nSample stadiums:")
    for team in ["DAL", "BUF", "MIN", "LV", "SF"]:
        info = cache["stadiums"].get(team)
        if info:
            label = "indoor" if info["is_indoor"] else ("sheltered" if info["is_sheltered"] else "outdoor")
            print(f"  {team}: {info['stadium']} ({info['roof_type']} — {label})")
