"""
Проверка: има ли реални резултати от мачове за Първа лига България?
League ID: 172 (потвърдено от предишния тест)
"""

import requests
import json

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

LEAGUE_ID = 172

def get_seasons_available():
    url = f"{BASE_URL}/leagues"
    params = {"id": LEAGUE_ID}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()
    if data.get("response"):
        seasons = data["response"][0].get("seasons", [])
        print(f"Налични сезони за League ID {LEAGUE_ID}:\n")
        for s in seasons:
            coverage = s.get("coverage", {})
            print(f"  Сезон {s['year']} | "
                  f"fixtures: {coverage.get('fixtures', {}).get('events', 'N/A')} | "
                  f"статистики по мач: {coverage.get('fixtures', {}).get('statistics_fixtures', 'N/A')} | "
                  f"players: {coverage.get('players', 'N/A')}")
        return seasons
    return []

def get_sample_fixtures(season_year):
    url = f"{BASE_URL}/fixtures"
    params = {"league": LEAGUE_ID, "season": season_year, "status": "FT"}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()
    fixtures = data.get("response", [])
    print(f"\nНамерени {len(fixtures)} завършени мача за сезон {season_year}")
    print(f"(remaining requests today: {r.headers.get('x-ratelimit-requests-remaining', 'N/A')})\n")

    for f in fixtures[:10]:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        goals_home = f["goals"]["home"]
        goals_away = f["goals"]["away"]
        date = f["fixture"]["date"][:10]
        print(f"  {date}: {home} {goals_home}-{goals_away} {away}")

    return fixtures

def main():
    seasons = get_seasons_available()

    if not seasons:
        print("Няма налична информация за сезони.")
        return

    years = sorted([s["year"] for s in seasons], reverse=True)
    test_year = years[1] if len(years) > 1 else years[0]

    fixtures = get_sample_fixtures(test_year)

    with open("bulgaria_fixtures_sample.json", "w", encoding="utf-8") as f:
        json.dump(fixtures, f, ensure_ascii=False, indent=2)
    print(f"\nПълните данни са записани в bulgaria_fixtures_sample.json")

if __name__ == "__main__":
    main()
