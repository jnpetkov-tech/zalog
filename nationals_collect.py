"""
ZADACHA_NACIONALNI2.md, ЧАСТ А (24.09.2026): записва коефициентите и
резултатите на мачовете на европейските национални отбори. САМО събиране
на данни - нищо от тук не се показва публично и не минава през модела.

Самостоятелен скрипт (не минава през живия Flask процес) - всеки пуск е нов
Python процес и чете кода от диска пресен, затова `git commit` е деплой, без
рестарт (CLAUDE.md т.9). НЕ импортира match_predictor_app (импортът му
фитва и записва model_cache/, виж CLAUDE_HANDOFF.md, ZADACHA_TRI В).
Всички заявки минават през api_football._api_get() (rate limiter +
api_calls.log).

Пуска се на всеки 30 мин (:20 и :50) от crontab на потребителя inkas (sudo за нов systemd
unit няма в тази сесия - виж validation/nacionalni_model_20260924.md).

Какво прави при всеки пуск:
1. Кои турнири вървят сега: веднъж на ден /leagues?country=World&current=true
   (1 заявка, кеш в nationals_seasons.json). Турнир, чийто текущ сезон не
   застъпва [днес-3, днес+7], не се пита изобщо.
2. За всеки текущ турнир: /fixtures за [днес-3, днес+7] (1 заявка).
   Всеки мач -> таблица national_fixtures (predictions.db).
   Приключилите -> добавят се в nationals_merged_full.csv (формат като
   клубните {лига}_merged_full.csv + колони за турнира и отборите).
3. Коефициенти за предстоящите (NS/TBD, до 7 дни напред) по същите прагове
   като клубните (_odds_needs_refresh в match_predictor_app.py: 90 мин до
   24ч преди мача, 360 мин до 72ч, 1440 мин по-нататък; плюс 45 мин в
   последните 3ч) ->
   odds_cache (st.set_cached_odds, чете се само по fixture_id - нищо не се
   показва) + national_odds_log (само добавяне, пази всяко теглене - и
   празните, с odds_json NULL, за праговете - за да
   имаме последните коефициенти преди мача дори ако нещо презапише
   odds_cache).
"""
import csv
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

import api_football as af  # noqa: E402
import system_tracker as st  # noqa: E402

# Решение на Дака (ZADACHA_NACIONALNI2.md): само европейските турнири.
NATIONAL_LEAGUES = {
    5: "UEFA Nations League",
    32: "World Cup - Qualification Europe",
    960: "Euro Championship - Qualification",
    4: "Euro Championship",
    1: "World Cup",
}
# Приятелските: само резултати (данни за обучение, не се показват, без
# коефициенти), веднъж на ден в пуска около 03:20, само сеньорски мачове между
# два национални отбора, които вече ги има в nationals_merged_full.csv.
FRIENDLIES_ID = 10
FRIENDLIES_HOUR = 3
YOUTH = re.compile(r"\bU-?\s?(1[5-9]|2[0-3])\b|Olymp", re.I)
DAYS_BACK = 3
DAYS_AHEAD = 7
SEASONS_CACHE = os.path.join(BASE_DIR, "nationals_seasons.json")
RESULTS_CSV = os.path.join(BASE_DIR, "nationals_merged_full.csv")
FINISHED = af.FINISHED_STATUSES
UPCOMING = {"NS", "TBD"}

# Същите колони като клубните {лига}_merged_full.csv, плюс турнира/отборите
# (един файл за всички турнири, за разлика от клубните - по един на лига).
CLUB_COLUMNS = [
    "fixture_id", "season", "date", "home_team", "away_team", "home_goals", "away_goals",
    "home_ht_goals", "away_ht_goals", "home_xg", "away_xg", "home_corners", "away_corners",
    "home_yellow", "away_yellow", "home_red", "away_red", "home_shots", "away_shots",
    "home_shots_on_goal", "away_shots_on_goal", "home_shots_insidebox", "away_shots_insidebox",
    "home_possession", "away_possession", "home_fouls", "away_fouls", "home_offsides",
    "away_offsides", "home_saves", "away_saves", "home_passes", "away_passes",
    "home_passes_accurate", "away_passes_accurate", "home_injuries", "away_injuries",
]
EXTRA_COLUMNS = ["league_id", "league_name", "round", "status", "home_id", "away_id",
                 "venue_city", "et_home_goals", "et_away_goals"]
CSV_COLUMNS = CLUB_COLUMNS + EXTRA_COLUMNS

LOG_MARKETS = ["home_win", "draw", "away_win", "over25", "under25", "btts_yes", "btts_no"]


def log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


def init_tables():
    conn = st.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS national_fixtures (
            fixture_id INTEGER PRIMARY KEY,
            league_id INTEGER, league_name TEXT, season INTEGER, round TEXT,
            kickoff_utc TEXT, status TEXT,
            home_id INTEGER, home_team TEXT, away_id INTEGER, away_team TEXT,
            home_goals INTEGER, away_goals INTEGER,
            home_ht_goals INTEGER, away_ht_goals INTEGER,
            venue_city TEXT, updated_at TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS national_odds_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fixture_id INTEGER, fetched_at TEXT, kickoff_utc TEXT,
            minutes_to_kickoff REAL, odds_json TEXT
        )""")
    conn.commit()
    conn.close()


def current_seasons():
    """{league_id: (season, start, end)} за турнирите от NATIONAL_LEAGUES,
    които API-то маркира като текущи. Кешира се за деня (1 заявка/ден)."""
    today = date.today().isoformat()
    if os.path.exists(SEASONS_CACHE):
        try:
            cached = json.load(open(SEASONS_CACHE))
            if cached.get("date") == today:
                return {int(k): tuple(v) for k, v in cached["seasons"].items()}
        except Exception:
            pass
    r = af._api_get("/leagues", params={"country": "World", "current": "true"}, timeout=30)
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"/leagues грешка: {data['errors']}")
    seasons = {}
    for item in data.get("response", []):
        lid = item["league"]["id"]
        if lid not in NATIONAL_LEAGUES and lid != FRIENDLIES_ID:
            continue
        for s in item.get("seasons", []):
            if s.get("current"):
                seasons[lid] = (s["year"], s["start"], s["end"])
    json.dump({"date": today, "seasons": seasons}, open(SEASONS_CACHE, "w"))
    return seasons


def _goal(v):
    return "" if v is None else v


def fixture_row(f):
    fx, lg, tm, sc = f["fixture"], f["league"], f["teams"], f["score"]
    # 90-минутният резултат (score.fulltime); продълженията - отделно.
    ft = sc.get("fulltime") or {}
    hg = ft.get("home") if ft.get("home") is not None else f["goals"]["home"]
    ag = ft.get("away") if ft.get("away") is not None else f["goals"]["away"]
    et = sc.get("extratime") or {}
    return {
        "fixture_id": fx["id"], "season": lg["season"], "date": fx["date"],
        "home_team": tm["home"]["name"], "away_team": tm["away"]["name"],
        "home_goals": hg, "away_goals": ag,
        "home_ht_goals": (sc.get("halftime") or {}).get("home"),
        "away_ht_goals": (sc.get("halftime") or {}).get("away"),
        "league_id": lg["id"], "league_name": lg["name"], "round": lg.get("round"),
        "status": fx["status"]["short"], "home_id": tm["home"]["id"], "away_id": tm["away"]["id"],
        "venue_city": (fx.get("venue") or {}).get("city"),
        "et_home_goals": et.get("home"), "et_away_goals": et.get("away"),
    }


def save_fixtures(rows):
    conn = st.get_conn()
    now = datetime.now().isoformat()
    for r in rows:
        conn.execute("""
            INSERT INTO national_fixtures (fixture_id, league_id, league_name, season, round,
                kickoff_utc, status, home_id, home_team, away_id, away_team, home_goals, away_goals,
                home_ht_goals, away_ht_goals, venue_city, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(fixture_id) DO UPDATE SET
                league_name=excluded.league_name, round=excluded.round,
                kickoff_utc=excluded.kickoff_utc, status=excluded.status,
                home_goals=excluded.home_goals, away_goals=excluded.away_goals,
                home_ht_goals=excluded.home_ht_goals, away_ht_goals=excluded.away_ht_goals,
                venue_city=excluded.venue_city, updated_at=excluded.updated_at
        """, (r["fixture_id"], r["league_id"], r["league_name"], r["season"], r["round"],
              r["date"], r["status"], r["home_id"], r["home_team"], r["away_id"], r["away_team"],
              r["home_goals"], r["away_goals"], r["home_ht_goals"], r["away_ht_goals"],
              r["venue_city"], now))
    conn.commit()
    conn.close()


def append_results(rows):
    """Приключилите мачове, които още ги няма в nationals_merged_full.csv."""
    finished = [r for r in rows if r["status"] in FINISHED and r["home_goals"] is not None]
    existing = set()
    if os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV, newline="", encoding="utf-8") as fh:
            existing = {int(x["fixture_id"]) for x in csv.DictReader(fh)}
    new = [r for r in finished if r["fixture_id"] not in existing]
    if not new:
        return 0
    write_header = not os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in sorted(new, key=lambda x: x["date"]):
            w.writerow({c: _goal(r.get(c)) for c in CSV_COLUMNS})
    return len(new)


def collect_friendlies(season, lo, today):
    known = set()
    if os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV, newline="", encoding="utf-8") as fh:
            for x in csv.DictReader(fh):
                known.update((x["home_id"], x["away_id"]))
    r = af._api_get("/fixtures", params={
        "league": FRIENDLIES_ID, "season": season, "from": lo.isoformat(), "to": today.isoformat(),
        "timezone": "UTC"}, timeout=30)
    data = r.json()
    if data.get("errors"):
        log(f"ГРЕШКА /fixtures приятелски: {data['errors']}")
        return 0
    rows = [fixture_row(f) for f in data.get("response", [])]
    senior = [x for x in rows if not YOUTH.search(x["home_team"]) and not YOUTH.search(x["away_team"])
              and str(x["home_id"]) in known and str(x["away_id"]) in known]
    added = append_results(senior)
    log(f"Приятелски: {len(rows)} мача, сеньорски между национални {len(senior)}, нови в CSV {added}")
    return added


def odds_needs_refresh(fixture_id, minutes_to_kickoff):
    # последният опит - успешен (odds_cache) или празен (national_odds_log с odds_json NULL),
    # за да не се пита мач без коефициенти на всеки пуск
    conn = st.get_conn()
    last = conn.execute("SELECT MAX(fetched_at) FROM national_odds_log WHERE fixture_id=?",
                        (fixture_id,)).fetchone()[0]
    conn.close()
    cached = st.get_cached_odds(fixture_id)
    stamps = [t for t in (last, (cached or {}).get("fetched_at")) if t]
    if not stamps:
        return True
    age = (datetime.now() - datetime.fromisoformat(max(stamps))).total_seconds() / 60
    # Последните 3 часа - по-често от клубните: последните коефициенти преди
    # мача са мерилото, срещу което после ще сравняваме.
    if minutes_to_kickoff <= 180:
        return age > 45
    if minutes_to_kickoff <= 24 * 60:
        return age > 90
    if minutes_to_kickoff <= 72 * 60:
        return age > 360
    return age > 1440


def refresh_odds(rows):
    now = datetime.now(timezone.utc)
    checked = saved = empty = 0
    markets = 0
    conn = st.get_conn()
    for r in sorted(rows, key=lambda x: x["date"]):
        if r["status"] not in UPCOMING:
            continue
        kickoff = datetime.fromisoformat(r["date"])
        mins = (kickoff - now).total_seconds() / 60
        if mins <= 0 or mins > DAYS_AHEAD * 24 * 60:
            continue
        if not odds_needs_refresh(r["fixture_id"], mins):
            continue
        checked += 1
        odds = af.fetch_fixture_odds(r["fixture_id"])
        present = {k: v for k, v in (odds or {}).items() if v is not None}
        if not present:
            empty += 1
            conn.execute("INSERT INTO national_odds_log (fixture_id, fetched_at, kickoff_utc, "
                         "minutes_to_kickoff, odds_json) VALUES (?,?,?,?,NULL)",
                         (r["fixture_id"], datetime.now().isoformat(), r["date"], round(mins, 1)))
            conn.commit()
            continue
        st.set_cached_odds(r["fixture_id"], odds)
        conn.execute("INSERT INTO national_odds_log (fixture_id, fetched_at, kickoff_utc, "
                     "minutes_to_kickoff, odds_json) VALUES (?,?,?,?,?)",
                     (r["fixture_id"], datetime.now().isoformat(), r["date"], round(mins, 1),
                      json.dumps(present)))
        conn.commit()
        saved += 1
        markets += sum(1 for k in LOG_MARKETS if k in present)
    conn.close()
    return checked, saved, empty, markets


def main():
    init_tables()
    calls_before = af.get_call_count()
    today = date.today()
    lo, hi = today - timedelta(days=DAYS_BACK), today + timedelta(days=DAYS_AHEAD)
    seasons = current_seasons()
    rows = []
    for lid, (season, start, end) in sorted(seasons.items()):
        if end < lo.isoformat() or start > hi.isoformat():
            continue
        r = af._api_get("/fixtures", params={
            "league": lid, "season": season, "from": lo.isoformat(), "to": hi.isoformat(),
            "timezone": "UTC"}, timeout=30)
        data = r.json()
        if data.get("errors"):
            log(f"ГРЕШКА /fixtures league={lid}: {data['errors']}")
            continue
        got = [fixture_row(f) for f in data.get("response", [])]
        log(f"{NATIONAL_LEAGUES[lid]} (сезон {season}): {len(got)} мача в [{lo}, {hi}]")
        rows.extend(got)
    save_fixtures(rows)
    added = append_results(rows)
    if datetime.now().hour == FRIENDLIES_HOUR and FRIENDLIES_ID in seasons:
        added += collect_friendlies(seasons[FRIENDLIES_ID][0], lo, today)
    checked, saved, empty, markets = refresh_odds(rows)
    log(f"РЕЗЮМЕ: мачове в прозореца {len(rows)}, нови резултати в CSV {added}, "
        f"коефициенти питани {checked}, записани {saved} мача ({markets} пазара от "
        f"1X2/над-под 2.5/двата отбора), без коефициенти {empty}, "
        f"API заявки {af.get_call_count() - calls_before}")


if __name__ == "__main__":
    main()
