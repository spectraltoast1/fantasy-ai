import csv
import io
import json
import requests
from datetime import date
from collections import defaultdict

GITHUB_BASE = "https://raw.githubusercontent.com/ThompsonJamesBliss/WeatherData/master/data"
STADIUMS_URL = f"{GITHUB_BASE}/stadium_coordinates.csv"
GAMES_URL = f"{GITHUB_BASE}/games.csv"
GAME_WEATHER_URL = f"{GITHUB_BASE}/games_weather.csv"

STADIUMS_CACHE = "data/stadiums.json"
GAME_WEATHER_CACHE = "data/game_weather.json"

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


def refresh_game_weather():
    """Download games.csv and games_weather.csv, aggregate weather per game, and cache."""
    print("Fetching game index from datawithbliss...")
    games_rows = _fetch_csv(GAMES_URL)
    print("Fetching game weather records (this may take a moment)...")
    weather_rows = _fetch_csv(GAME_WEATHER_URL)

    # Build game_id → stadium map
    game_stadium = {
        row["game_id"]: row.get("StadiumName", "").strip()
        for row in games_rows if row.get("game_id")
    }

    # Aggregate weather measurements per game (average across all readings in the window)
    game_temps = defaultdict(list)
    game_wind = defaultdict(list)
    game_precip = defaultdict(list)
    game_humidity = defaultdict(list)

    for row in weather_rows:
        gid = row.get("game_id")
        if not gid:
            continue
        try:
            if row.get("Temperature"):
                game_temps[gid].append(float(row["Temperature"]))
            if row.get("WindSpeed"):
                game_wind[gid].append(float(row["WindSpeed"]))
            if row.get("Precipitation"):
                game_precip[gid].append(float(row["Precipitation"]))
            if row.get("Humidity"):
                game_humidity[gid].append(float(row["Humidity"]))
        except (ValueError, TypeError):
            continue

    def _avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    def _total(lst):
        return round(sum(lst), 2) if lst else None

    games = {}
    for gid in game_stadium:
        games[gid] = {
            "stadium": game_stadium[gid],
            "temp_f": _avg(game_temps[gid]),
            "wind_mph": _avg(game_wind[gid]),
            "precip_in": _total(game_precip[gid]),
            "humidity_pct": _avg(game_humidity[gid]),
        }

    cache = {"updated_at": str(date.today()), "games": games}
    with open(GAME_WEATHER_CACHE, "w") as f:
        json.dump(cache, f)
    print(f"  Cached weather for {len(games)} games to {GAME_WEATHER_CACHE}")
    return cache


def load_stadiums():
    try:
        with open(STADIUMS_CACHE) as f:
            return json.load(f).get("stadiums", {})
    except FileNotFoundError:
        return {}


def load_game_weather():
    try:
        with open(GAME_WEATHER_CACHE) as f:
            return json.load(f).get("games", {})
    except FileNotFoundError:
        return {}


def get_stadium_info(team_abbr):
    """Look up a team's stadium and weather exposure. Returns None if not found."""
    return load_stadiums().get(team_abbr)


def get_game_weather(game_id):
    """Look up historical weather for a specific game_id. Returns None if not found."""
    return load_game_weather().get(str(game_id))


if __name__ == "__main__":
    import sys

    if "--game-weather" in sys.argv:
        cache = refresh_game_weather()
        sample_id = next(iter(cache["games"]))
        print(f"\nSample game ({sample_id}):")
        print(json.dumps(cache["games"][sample_id], indent=2))
    else:
        cache = refresh_stadiums()
        print("\nSample stadiums:")
        for team in ["DAL", "BUF", "MIN", "LV", "SF"]:
            info = cache["stadiums"].get(team)
            if info:
                label = "indoor" if info["is_indoor"] else ("sheltered" if info["is_sheltered"] else "outdoor")
                print(f"  {team}: {info['stadium']} ({info['roof_type']} — {label})")
