"""Фаза J.2 (20.08.2026) - еднократна/периодична диагностика: за прозореца
today..today+DAYS_AHEAD, по всяка лига, колко мача имат кеширан коефициент
(odds_cache) срещу общ брой предстоящи мачове. Само четене - не пипа
match_predictor_app.py/football_lib.py/system_tracker.py, не пише в БД.
Извиква се ръчно: python3 check_odds_coverage.py
"""
from datetime import date, timedelta
import requests
import system_tracker as st

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
API_HEADERS = {"x-apisports-key": API_KEY}
DAYS_AHEAD = 7

ALL_LEAGUES = {
    "bulgaria": {"name": "Първа лига България", "id": 172},
    "england": {"name": "Английска Висша лига", "id": 39},
    "germany": {"name": "Бундеслига", "id": 78},
    "spain": {"name": "Ла Лига", "id": 140},
    "france": {"name": "Лига 1 Франция", "id": 61},
    "champions_league": {"name": "Шампионска лига", "id": 2},
    "europa_league": {"name": "Лига Европа", "id": 3},
    "conference_league": {"name": "Лига на конференциите", "id": 848},
    "italy": {"name": "Серия А Италия", "id": 135},
    "portugal": {"name": "Примейра Лига Португалия", "id": 94},
    "france2": {"name": "Франция - Лига 2", "id": 62},
    "spain2": {"name": "Испания - Сегунда Дивисион", "id": 141},
    "italy2": {"name": "Италия - Серия Б", "id": 136},
    "portugal2": {"name": "Португалия - Сегунда Лига", "id": 95},
    "bulgaria2": {"name": "България - Втора лига", "id": 173},
    "england2": {"name": "Англия - Чемпиъншип", "id": 40},
    "germany2": {"name": "Германия - Втора Бундеслига", "id": 79},
}


def fetch_upcoming_fixtures(league_id, from_date, to_date):
    params = {
        "league": league_id,
        "season": from_date.year if from_date.month >= 7 else from_date.year - 1,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "timezone": "Europe/Sofia",
    }
    r = requests.get(f"{BASE_URL}/fixtures", headers=API_HEADERS, params=params, timeout=15)
    data = r.json()
    if data.get("errors"):
        return [], data["errors"]
    return data.get("response", []), None


def has_odds(fixture_id):
    cached = st.get_cached_odds(fixture_id)
    if not cached:
        return False
    return bool(cached.get("home_win") or cached.get("over25"))


def main():
    from_date = date.today()
    to_date = from_date + timedelta(days=DAYS_AHEAD)
    print(f"Проверка на покритие с коефициенти: {from_date} .. {to_date}\n")

    rows = []
    total_fixtures = 0
    total_with_odds = 0
    missing = []

    for key, info in ALL_LEAGUES.items():
        fixtures, err = fetch_upcoming_fixtures(info["id"], from_date, to_date)
        if err:
            rows.append((key, info["name"], None, None, f"ГРЕШКА: {err}"))
            continue
        n = len(fixtures)
        with_odds = 0
        for f in fixtures:
            fid = f["fixture"]["id"]
            if has_odds(fid):
                with_odds += 1
            else:
                home = f["teams"]["home"]["name"]
                away = f["teams"]["away"]["name"]
                fdate = f["fixture"]["date"][:16].replace("T", " ")
                missing.append((key, fdate, home, away))
        pct = (with_odds / n * 100) if n else None
        rows.append((key, info["name"], n, with_odds, pct))
        total_fixtures += n
        total_with_odds += with_odds

    print(f"{'Лига':<20}{'Мачове':>8}{'С коеф.':>10}{'Покритие':>12}")
    print("-" * 52)
    for key, name, n, with_odds, pct in rows:
        if n is None:
            print(f"{key:<20}{pct}")
            continue
        pct_str = f"{pct:.0f}%" if pct is not None else "n/a"
        print(f"{key:<20}{n:>8}{with_odds:>10}{pct_str:>12}")

    overall_pct = (total_with_odds / total_fixtures * 100) if total_fixtures else 0
    print("-" * 52)
    print(f"{'ОБЩО':<20}{total_fixtures:>8}{total_with_odds:>10}{overall_pct:>11.0f}%\n")

    if missing:
        print(f"Мачове БЕЗ коефициент ({len(missing)}):")
        for key, fdate, home, away in missing:
            print(f"  [{key}] {fdate}  {home} - {away}")
    else:
        print("Всички предстоящи мачове имат кеширан коефициент.")


if __name__ == "__main__":
    main()
