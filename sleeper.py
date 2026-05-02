import requests
import json
from datetime import date
from config import SLEEPER_USERNAME

def get_sleeper_user(username):
    url = f"https://api.sleeper.app/v1/user/{username}"
    r = requests.get(url)
    user_json = r.json()
    return user_json


def get_sleeper_league(user_id):
    state = get_nfl_state()
    season = state.get("league_season") or state.get("season")
    url = f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{season}"
    r = requests.get(url)
    return r.json()


def get_sleeper_roster(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    r = requests.get(url)
    roster_json = r.json()
    return roster_json

def get_players():
    r = requests.get('https://api.sleeper.app/v1/players/nfl')
    roster_json = r.json()

    data = {
    "updated_at": str(date.today()),
    "players": roster_json
    }
    
    with open('data/players.json', 'w') as f:
        json.dump(data, f, indent=4)
    return data


def get_league(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}"
    r = requests.get(url)
    return r.json()


def get_nfl_state():
    r = requests.get("https://api.sleeper.app/v1/state/nfl")
    return r.json()


def get_matchups(league_id, week):
    url = f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}"
    r = requests.get(url)
    return r.json()


def get_free_agents(league_id):
    """Return enriched free agent list derived from players not on any roster.

    Sleeper has no dedicated free-agents endpoint, so we compute the set of
    all rostered player IDs then filter the local players.json for active
    skill-position players that aren't rostered.
    """
    SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K"}

    rosters = get_sleeper_roster(league_id)
    rostered = {pid for r in rosters for pid in (r.get("players") or [])}

    try:
        with open("data/players.json") as f:
            all_players = json.load(f).get("players", {})
    except FileNotFoundError:
        return []

    free_agents = []
    for pid, p in all_players.items():
        if pid in rostered:
            continue
        if not p.get("team") or p.get("position") not in SKILL_POSITIONS:
            continue
        free_agents.append({
            "player_id": pid,
            "name": p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            "position": p.get("position"),
            "team": p.get("team"),
            "injury_status": p.get("injury_status"),
            "depth_chart_order": p.get("depth_chart_order"),
        })

    free_agents.sort(key=lambda x: (x["position"], x.get("depth_chart_order") or 99))
    return free_agents


if __name__ == "__main__":
    user = get_sleeper_user(SLEEPER_USERNAME)
    user_id = user["user_id"]
    
    leagues = get_sleeper_league(user_id)
    # leagues is a list, so we pick one
    league_id = leagues[0]["league_id"]
    
    rosters = get_sleeper_roster(league_id)

    # test block
    #get_players()