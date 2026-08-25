import requests
import json

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

url = f"{BASE_URL}/fixtures"
params = {"league": 172, "season": 2023, "status": "FT"}
r = requests.get(url, headers=headers, params=params)
data = r.json()

fixtures = data.get("response", [])
print(f"Намерени {len(fixtures)} завършени мача за сезон 2023\n")

for f in fixtures[:15]:
    home = f["teams"]["home"]["name"]
    away = f["teams"]["away"]["name"]
    gh = f["goals"]["home"]
    ga = f["goals"]["away"]
    date = f["fixture"]["date"][:10]
    print(f"  {date}: {home} {gh}-{ga} {away}")

with open("bulgaria_2023_fixtures.json", "w", encoding="utf-8") as file:
    json.dump(fixtures, file, ensure_ascii=False, indent=2)
print(f"\nЗаписано в bulgaria_2023_fixtures.json ({len(fixtures)} мача общо)")
