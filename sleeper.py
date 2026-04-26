import requests

def get_sleeper_user(username):
    url = f"https://api.sleeper.app/v1/user/{username}"
    r = requests.get(url)
    return r.json()

if __name__ == "__main__":
    user = get_sleeper_user("spectraltoast1")
    print(user)