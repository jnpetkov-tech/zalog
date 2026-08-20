import requests
import time

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

TEAM_ID = 566
FIXTURE_ID = 1551067
LEAGUE_ID = 172

endpoints_to_test = [
    ("/odds", {"fixture": FIXTURE_ID}, "Коефициенти от букмейкъри"),
    ("/predictions", {"fixture": FIXTURE_ID}, "Вградени прогнози на API-Football"),
    ("/standings", {"league": LEAGUE_ID, "season": 2025}, "Класиране"),
    ("/teams/statistics", {"team": TEAM_ID, "league": LEAGUE_ID, "season": 2025}, "Обобщена сезонна статистика на отбор"),
    ("/trophies", {"team": TEAM_ID}, "Трофеи"),
    ("/sidelined", {"team": TEAM_ID}, "Липсващи играчи (различно от /injuries?)"),
    ("/venues", {"id": 1}, "Стадиони"),
    ("/players", {"team": TEAM_ID, "season": 2025}, "Играчи в отбора"),
    ("/transfers", {"team": TEAM_ID}, "Трансфери"),
    ("/fixtures/lineups", {"fixture": FIXTURE_ID}, "Стартови състави"),
    ("/fixtures/events", {"fixture": FIXTURE_ID}, "Събития по мач (голове/картони с минута)"),
    ("/fixtures/headtohead", {"h2h": f"{TEAM_ID}-1"}, "История на преки срещи"),
    ("/players/topscorers", {"league": LEAGUE_ID, "season": 2025}, "Голмайстори"),
    ("/players/topassists", {"league": LEAGUE_ID, "season": 2025}, "Асистенции"),
]

print(f"{'Ендпойнт':<28} {'Описание':<40} {'Статус':<10} {'Резултати'}")
print("=" * 100)

for endpoint, params, description in endpoints_to_test:
    try:
        r = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params, timeout=10)
        data = r.json()
        errors = data.get("errors")
        results = data.get("results", "?")
        status = "✅ РАБОТИ" if not errors and results else ("⚠️ 0 РЕЗУЛТАТА" if not errors else "❌ ГРЕШКА")
        err_str = f" | {errors}" if errors else ""
        print(f"{endpoint:<28} {description:<40} {status:<10} {results}{err_str}")
    except Exception as e:
        print(f"{endpoint:<28} {description:<40} ИЗКЛЮЧЕНИЕ: {e}")
    time.sleep(0.3)
