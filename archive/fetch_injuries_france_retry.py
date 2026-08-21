import requests
import csv
import time

FREE_API_KEY = "88b7314ada2fe7d4e7327b55d6d3e1bd"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": FREE_API_KEY}

print("Изчаквам 20 секунди, за да изчистим лимита на минута...")
time.sleep(20)

for season in [2023, 2024]:
    print(f"Тегля france сезон {season}...")
    r = requests.get(f"{BASE_URL}/injuries", headers=headers,
                      params={"league": 61, "season": season})
    data = r.json()
    if data.get("errors"):
        print(f"  Грешка: {data['errors']}")
        continue

    injuries = data.get("response", [])
    print(f"  -> {len(injuries)} записа")

    with open("injuries_all_leagues.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "country", "season", "fixture_id", "fixture_date", "team_id",
            "team_name", "player_id", "player_name", "type", "reason"
        ])
        for inj in injuries:
            writer.writerow({
                "country": "france", "season": season,
                "fixture_id": inj["fixture"]["id"],
                "fixture_date": inj["fixture"]["date"][:10],
                "team_id": inj["team"]["id"], "team_name": inj["team"]["name"],
                "player_id": inj["player"]["id"], "player_name": inj["player"]["name"],
                "type": inj["player"]["type"], "reason": inj["player"]["reason"],
            })
    time.sleep(10)

print("Готово.")
