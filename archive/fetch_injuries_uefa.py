import requests
import csv
import time

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

COMPETITIONS = {"champions_league": 2, "europa_league": 3}
SEASONS = [2022, 2023, 2024, 2025]


def fetch_comp_season_injuries(league_id, season):
    r = requests.get(f"{BASE_URL}/injuries", headers=headers,
                      params={"league": league_id, "season": season})
    data = r.json()
    if data.get("errors"):
        print(f"    Грешка: {data['errors']}")
        return []
    return data.get("response", [])


all_rows = []
for comp_name, league_id in COMPETITIONS.items():
    for season in SEASONS:
        print(f"Тегля {comp_name} сезон {season}...")
        injuries = fetch_comp_season_injuries(league_id, season)
        print(f"  -> {len(injuries)} записа")

        for inj in injuries:
            all_rows.append({
                "competition": comp_name,
                "season": season,
                "fixture_id": inj["fixture"]["id"],
                "fixture_date": inj["fixture"]["date"][:10],
                "team_id": inj["team"]["id"],
                "team_name": inj["team"]["name"],
                "player_id": inj["player"]["id"],
                "player_name": inj["player"]["name"],
                "type": inj["player"]["type"],
                "reason": inj["player"]["reason"],
            })
        time.sleep(0.5)

with open("injuries_uefa.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "competition", "season", "fixture_id", "fixture_date", "team_id",
        "team_name", "player_id", "player_name", "type", "reason"
    ])
    writer.writeheader()
    writer.writerows(all_rows)

print(f"\nОбщо {len(all_rows)} записа в injuries_uefa.csv")
