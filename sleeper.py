import requests

def get_sleeper_user(username):
    url = f"https://api.sleeper.app/v1/user/{username}"
    r = requests.get(url)
    user_json = r.json()
    return user_json


def get_sleeper_league(user_id):
    url = f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/2025"
    r = requests.get(url)
    league_json = r.json()
    return league_json


def get_sleeper_roster(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    r = requests.get(url)
    roster_json = r.json()
    return roster_json


if __name__ == "__main__":
    user = get_sleeper_user("spectraltoast1")
    user_id = user["user_id"]
    
    leagues = get_sleeper_league(user_id)
    # leagues is a list, so we pick one
    league_id = leagues[0]["league_id"]
    
    rosters = get_sleeper_roster(league_id)

    # test block
    print(user)
    print(leagues)
    print(rosters)