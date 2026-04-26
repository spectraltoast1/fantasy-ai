import requests

def get_sleeper_user(username):
    url = f"https://api.sleeper.app/v1/user/{username}"
    r = requests.get(url)
    return r.json()


def get_sleeper_leagues(user_id):
    














if __name__ == "__main__":
    user = get_sleeper_user("spectraltoast1")
    print(user)