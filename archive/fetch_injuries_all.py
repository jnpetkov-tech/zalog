import requests
import csv
import time

FREE_API_KEY = "88b7314ada2fe7d4e7327b55d6d3e1bd"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": FREE_API_KEY}

LEAGUES = {"england": 39, "germany": 78, "spain": 140, "france": 61}
SEASONS = [2022, 2023, 2024]


def fetch_league_season_injuries(league_id, season):
    r = requests.get(f"{BASE_URL}/injuries", headers=headers,
                      params={"league": league_id, "season": season})
    data = r.json()
    if data.get("errors"):
        print(f"    Грешка: {data['errors']}")
        return []
    return data.get("response", [])


def main():
    all_rows = []
    for country, league_id in LEAGUES.items():
        for season in SEASONS:
            print(f"Тегля {country} сезон {season}...")
            injuries = fetch_league_season_injuries(league_id, season)
            print(f"  -> {len(injuries)} записа за контузии/отсъствия")

            for inj in injuries:
                all_rows.append({
                    "country": country,
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

    with open("injuries_all_leagues.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "country", "season", "fixture_id", "fixture_date", "team_id",
            "team_name", "player_id", "player_name", "type", "reason"
        ])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nОбщо записани {len(all_rows)} записа в injuries_all_leagues.csv")


if __name__ == "__main__":
    main()
