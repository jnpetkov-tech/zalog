import requests

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

r = requests.get(f"{BASE_URL}/leagues", headers=headers, params={"search": "Ligue 1"})
data = r.json()
for item in data.get("response", []):
    if item["league"]["type"] == "League":
        print(f"ID: {item['league']['id']} | {item['league']['name']} | {item['country']['name']}")
