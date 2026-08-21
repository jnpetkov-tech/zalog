import requests
import json

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

url = f"{BASE_URL}/leagues"
params = {"search": "Premier League", "country": "England"}
r = requests.get(url, headers=headers, params=params)
data = r.json()

for item in data.get("response", []):
    league = item["league"]
    country = item["country"]
    print(f"League ID: {league['id']} | Име: {league['name']} | Държава: {country['name']}")
    seasons = item.get("seasons", [])
    for s in seasons[-5:]:
        coverage = s.get("coverage", {})
        print(f"    Сезон {s['year']} | fixtures: {coverage.get('fixtures', {}).get('events', 'N/A')} | статистики: {coverage.get('fixtures', {}).get('statistics_fixtures', 'N/A')}")
