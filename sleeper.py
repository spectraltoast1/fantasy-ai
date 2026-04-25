import requests

def get_sleeper_user(username):
    r = requests.get("https://api.sleeper.app/v1/user/")