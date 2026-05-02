import json
import requests
from datetime import datetime, timezone
from config import THE_ODDS_API_KEY as ODDS_API_KEY
from sleeper import get_nfl_state

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"
CACHE_PATH = "data/odds_current.json"

# Sleeper team abbreviations don't always match The Odds API team names.
# This map normalises the most common mismatches.
_ODDS_NAME_TO_SLEEPER = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}


def _derive_implied_totals(game):
    """Return (home_implied, away_implied) from a game's bookmaker odds, or (None, None)."""
    spread = None
    total = None
    home_favored = None

    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "totals" and total is None:
                for outcome in market.get("outcomes", []):
                    if outcome["name"] == "Over":
                        total = outcome["point"]
            if market["key"] == "spreads" and spread is None:
                for outcome in market.get("outcomes", []):
                    if outcome["name"] == game.get("home_team"):
                        spread = outcome["point"]
                        home_favored = spread < 0
        if spread is not None and total is not None:
            break

    if spread is None or total is None:
        return None, None

    home_implied = round((total + abs(spread)) / 2, 1) if home_favored else round((total - abs(spread)) / 2, 1)
    away_implied = round(total - home_implied, 1)
    return home_implied, away_implied


def refresh_odds():
    state = get_nfl_state()
    season_type = state.get("season_type", "off")
    week = state.get("week", 0)

    if season_type == "off":
        print("Off-season — skipping Odds API call to preserve quota.")
        # Write/preserve an empty cache so load_odds() doesn't fail
        empty = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "week": 0,
            "season_type": "off",
            "credits_used_this_call": 0,
            "games": {},
        }
        with open(CACHE_PATH, "w") as f:
            json.dump(empty, f, indent=2)
        return empty

    print(f"Fetching game odds (week {week}, ~2 credits)...")
    r = requests.get(
        f"{BASE_URL}/sports/{SPORT}/odds/",
        params={
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "spreads,totals",
            "oddsFormat": "american",
        },
    )
    r.raise_for_status()

    credits_remaining = r.headers.get("x-requests-remaining", "unknown")
    credits_used = r.headers.get("x-requests-last", "unknown")
    print(f"  Credits used this call: {credits_used} | Remaining: {credits_remaining}")

    games_raw = r.json()
    games = {}

    for game in games_raw:
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        home_abbr = _ODDS_NAME_TO_SLEEPER.get(home_team)
        away_abbr = _ODDS_NAME_TO_SLEEPER.get(away_team)

        home_implied, away_implied = _derive_implied_totals(game)

        # Determine spread from home team's perspective
        spread = None
        total = None
        for bookmaker in game.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market["key"] == "spreads" and spread is None:
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == home_team:
                            spread = outcome["point"]
                if market["key"] == "totals" and total is None:
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == "Over":
                            total = outcome["point"]
            if spread is not None and total is not None:
                break

        if home_abbr:
            games[home_abbr] = {
                "opponent": away_abbr,
                "home": True,
                "spread": spread,
                "total": total,
                "implied_total": home_implied,
                "favored": spread < 0 if spread is not None else None,
            }
        if away_abbr:
            games[away_abbr] = {
                "opponent": home_abbr,
                "home": False,
                "spread": -spread if spread is not None else None,
                "total": total,
                "implied_total": away_implied,
                "favored": spread > 0 if spread is not None else None,
            }

    cache = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "week": week,
        "season_type": season_type,
        "credits_used_this_call": credits_used,
        "games": games,
    }
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)

    print(f"Cached odds for {len(games)} teams to {CACHE_PATH}")
    return cache


def load_odds():
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"games": {}}

    updated = data.get("updated_at")
    if updated and data.get("season_type") != "off":
        updated_dt = datetime.fromisoformat(updated)
        age_hours = (datetime.now(timezone.utc) - updated_dt).total_seconds() / 3600
        if age_hours > 6:
            print(f"Warning: odds_current.json is {age_hours:.1f}h old.")

    return data


def get_team_odds(team_abbr):
    data = load_odds()
    return data.get("games", {}).get(team_abbr)


if __name__ == "__main__":
    cache = refresh_odds()
    if cache["games"]:
        print("\nSample game:")
        first_team = next(iter(cache["games"]))
        print(json.dumps({first_team: cache["games"][first_team]}, indent=2))
    else:
        print("No games available (off-season).")
