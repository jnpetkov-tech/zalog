import requests
import csv
import sys
import time

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}


def fetch_season(league_id, season):
    r = requests.get(f"{BASE_URL}/fixtures", headers=headers,
                      params={"league": league_id, "season": season})
    data = r.json()
    if data.get("errors"):
        print(f"  Грешка за сезон {season}: {data['errors']}")
        return []
    return data.get("response", [])


def main(league_id, country_name):
    all_rows = []
    for season in [2022, 2023, 2024, 2025]:
        print(f"Тегля {country_name} сезон {season}...")
        fixtures = fetch_season(league_id, season)
        print(f"  -> {len(fixtures)} мача")

        for f in fixtures:
            if f["fixture"]["status"]["short"] != "FT":
                continue
            all_rows.append({
                "fixture_id": f["fixture"]["id"],
                "season": season,
                "date": f["fixture"]["date"][:10],
                "home_team": f["teams"]["home"]["name"],
                "away_team": f["teams"]["away"]["name"],
                "home_goals": f["goals"]["home"],
                "away_goals": f["goals"]["away"],
                "home_ht_goals": f["score"]["halftime"]["home"],
                "away_ht_goals": f["score"]["halftime"]["away"],
            })
        time.sleep(0.3)

    with open(f"{country_name}_full_history.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "fixture_id", "season", "date", "home_team", "away_team",
            "home_goals", "away_goals", "home_ht_goals", "away_ht_goals"
        ])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nОбщо {len(all_rows)} завършени мача записани в {country_name}_full_history.csv")


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
