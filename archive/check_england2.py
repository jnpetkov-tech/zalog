import requests
import json

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

url = f"{BASE_URL}/leagues"
params = {"search": "Premier League"}
r = requests.get(url, headers=headers, params=params)
data = r.json()

print("HTTP status:", r.status_code)
print("results:", data.get("results"))
print("errors:", data.get("errors"))
print()

for item in data.get("response", []):
    league = item["league"]
    country = item["country"]
    print(f"League ID: {league['id']} | Име: {league['name']} | Държава: {country['name']}")
