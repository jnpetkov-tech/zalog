import requests
import csv
import time

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

LEAGUE_ID = 172
SEASONS = [2022, 2023, 2024]

def fetch_season(season):
    url = f"{BASE_URL}/fixtures"
    params = {"league": LEAGUE_ID, "season": season, "status": "FT"}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()
    if data.get("errors"):
        print(f"  Грешка за сезон {season}: {data['errors']}")
        return []
    return data.get("response", [])

def main():
    all_matches = []

    for season in SEASONS:
        print(f"Тегля сезон {season}...")
        fixtures = fetch_season(season)
        print(f"  -> {len(fixtures)} мача")

        for f in fixtures:
            all_matches.append({
                "season": season,
                "date": f["fixture"]["date"][:10],
                "home_team": f["teams"]["home"]["name"],
                "away_team": f["teams"]["away"]["name"],
                "home_goals": f["goals"]["home"],
                "away_goals": f["goals"]["away"],
            })

        time.sleep(1)

    with open("bulgaria_first_league_matches.csv", "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=[
            "season", "date", "home_team", "away_team", "home_goals", "away_goals"
        ])
        writer.writeheader()
        writer.writerows(all_matches)

    print(f"\nОбщо записани {len(all_matches)} мача в bulgaria_first_league_matches.csv")

if __name__ == "__main__":
    main()
