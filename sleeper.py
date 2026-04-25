import requests

def get_sleeper_user(username):
    url = f"https://api.sleeper.app/v1/user/{username}"
    r = requests.get(url)
    return r.json()