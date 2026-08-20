import requests

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

r = requests.get(f"{BASE_URL}/status", headers=headers)
data = r.json()
print("errors:", data.get("errors"))
if data.get("response"):
    print("Заявки днес:", data["response"]["requests"]["current"], "/", data["response"]["requests"]["limit_day"])
