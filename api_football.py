"""
api_football.py — API-Football HTTP клиент, изваден от match_predictor_app.py
(ARCHITECTURE.md, Граница 4, втора част, 22.08.2026).

Чисто преместване, не пренаписване: всяка функция тук е преместена бит-по-бит
(сигнатура, timeout-и, параметри) от match_predictor_app.py, без промяна в
поведението. match_predictor_app.py импортира оттук вместо да дефинира
локално - вижте validation/ за преди/след доказателство на всяка стъпка.
"""
from datetime import date, timedelta
from collections import deque
import threading
import time
import requests
import config

# Сигурност, 25.08.2026: ключът вече идва от .env (виж config.py) - НЕ е
# сменен, само мястото му. По искане на Дака: "стойностите остават същите,
# само мястото им се променя" - завъртане на ключа е отделно, бъдещо решение.
API_KEY = config.API_KEY
BASE_URL = "https://v3.football.api-sports.io"
API_HEADERS = {"x-apisports-key": API_KEY}
FINISHED_STATUSES = {"FT", "AET", "PEN", "AWD", "WO"}
DAYS_AHEAD = 7


class _RateLimiter:
    """Споделен sliding-window rate limiter за API-Football (23.08.2026,
    rate limit на минута, стъпка 2/4). Абонаментът е Pro план, лимит 300
    заявки/минута - потвърдено на живо от `/status` header
    `x-ratelimit-limit` (виж диагнозата в разговора/CLAUDE_HANDOFF.md).
    max_per_minute=280, не 300 - запас за няколкото случая извън тази
    брава (update_injuries_for_league()/run_diagnostics() в
    match_predictor_app.py правят собствени, нечести `requests.get`, не
    минават през fetch_*).

    При НОРМАЛНА употреба (под прага) acquire() не добавя никакво
    закъснение - връща се веднага. Само при доближаване на 280 в
    последните 60 секунди изчаква точно колкото трябва, вместо да остави
    API-то да върне 429 ('Too many requests... limit of requests per
    minute of your subscription' - виж refresh_log.txt за реални случаи
    отпреди тази промяна)."""

    def __init__(self, max_per_minute=280, window_seconds=60):
        self.max_per_minute = max_per_minute
        self.window_seconds = window_seconds
        self._timestamps = deque()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - self.window_seconds
                while self._timestamps and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_per_minute:
                    self._timestamps.append(now)
                    return
                sleep_for = self._timestamps[0] + self.window_seconds - now + 0.05
            time.sleep(max(sleep_for, 0.05))


_rate_limiter = _RateLimiter()


def _api_get(path, params=None, timeout=10):
    """Единствената точка, през която минават всички fetch_* по-долу към
    API-Football - гарантира, че rate limiter-ът вижда всяка заявка."""
    _rate_limiter.acquire()
    return requests.get(f"{BASE_URL}{path}", headers=API_HEADERS, params=params, timeout=timeout)


def fetch_fixture_predictions(fixture_id):
    """Тегли вградената прогноза на API-Football - само за информативно сравнение"""
    try:
        r = _api_get("/predictions", params={"fixture": fixture_id}, timeout=10)
        data = r.json()
        if data.get("errors") or not data.get("response"):
            return None

        pred = data["response"][0].get("predictions", {})
        percent = pred.get("percent", {})
        advice = pred.get("advice")
        winner = pred.get("winner", {}).get("name")
        # Фаза P.1 (21.08.2026): team id-та идват безплатно в същия отговор -
        # ползвани за /fixtures?team=.. (последни 5 мача) и /standings по-долу,
        # без допълнително API извикване само за да намерим team id.
        teams = data["response"][0].get("teams", {})
        home_id = teams.get("home", {}).get("id")
        away_id = teams.get("away", {}).get("id")

        return {
            "home_pct": percent.get("home"), "draw_pct": percent.get("draw"), "away_pct": percent.get("away"),
            "advice": advice, "winner": winner, "home_id": home_id, "away_id": away_id,
        }
    except Exception:
        return None


def fetch_fixture_odds(fixture_id):
    # 2026-08-10 (Фаза D2): разширен да чете HT/FT, двоен шанс, team totals
    # от СЪЩИЯ вече викан /odds отговор - нула допълнителни API заявки.
    # Bet имената потвърдени на живо срещу реален отговор преди този патч
    # (diag_odds_response.py) - "Double Chance", "Total - Home"/"Total - Away",
    # "HT/FT Double".
    #
    # 25.08.2026: добавен "Both Teams Score" (BTTS) - живи проверки
    # (validation/coverage_diagnosis_20260825.md) показаха широко букмейкърско
    # покритие (73-79% от букмейкърите за проверените мачове, сравнимо с team
    # totals), за разлика от предишния коментар тук ("коефициент за тях няма
    # практическа стойност") - грешен поне за BTTS, вече поправен. Corners/
    # cards/offsides остават непарсвани тук - cards/offsides премахнати от
    # системата изцяло (25.08.2026, Дака: "прогнози, които не подлежат на
    # сравнение, нямат място"), corners остава на частично покритие по
    # изрично решение на Дака, без коефициент в предсказанието.
    try:
        r = _api_get("/odds", params={"fixture": fixture_id}, timeout=10)
        data = r.json()
        if data.get("errors") or not data.get("response"):
            return None

        odds_1x2 = {"home": [], "draw": [], "away": []}
        odds_ou = {"over": [], "under": []}
        odds_team_total = {"home_over15": [], "home_under15": [], "away_over15": [], "away_under15": []}
        odds_dc = {"dc_1x": [], "dc_x2": [], "dc_12": []}
        odds_btts = {"yes": [], "no": []}
        odds_htft = {}
        HTFT_SIDE = {"Home": "1", "Draw": "X", "Away": "2"}

        for bookmaker_block in data["response"][0].get("bookmakers", []):
            for bet in bookmaker_block.get("bets", []):
                if bet["name"] == "Match Winner":
                    for v in bet["values"]:
                        if v["value"] == "Home":
                            odds_1x2["home"].append(float(v["odd"]))
                        elif v["value"] == "Draw":
                            odds_1x2["draw"].append(float(v["odd"]))
                        elif v["value"] == "Away":
                            odds_1x2["away"].append(float(v["odd"]))
                elif bet["name"] == "Goals Over/Under":
                    for v in bet["values"]:
                        if v["value"] == "Over 2.5":
                            odds_ou["over"].append(float(v["odd"]))
                        elif v["value"] == "Under 2.5":
                            odds_ou["under"].append(float(v["odd"]))
                elif bet["name"] == "Total - Home":
                    for v in bet["values"]:
                        if v["value"] == "Over 1.5":
                            odds_team_total["home_over15"].append(float(v["odd"]))
                        elif v["value"] == "Under 1.5":
                            odds_team_total["home_under15"].append(float(v["odd"]))
                elif bet["name"] == "Total - Away":
                    for v in bet["values"]:
                        if v["value"] == "Over 1.5":
                            odds_team_total["away_over15"].append(float(v["odd"]))
                        elif v["value"] == "Under 1.5":
                            odds_team_total["away_under15"].append(float(v["odd"]))
                elif bet["name"] == "Double Chance":
                    for v in bet["values"]:
                        if v["value"] == "Home/Draw":
                            odds_dc["dc_1x"].append(float(v["odd"]))
                        elif v["value"] == "Draw/Away":
                            odds_dc["dc_x2"].append(float(v["odd"]))
                        elif v["value"] == "Home/Away":
                            odds_dc["dc_12"].append(float(v["odd"]))
                elif bet["name"] == "Both Teams Score":
                    for v in bet["values"]:
                        if v["value"] == "Yes":
                            odds_btts["yes"].append(float(v["odd"]))
                        elif v["value"] == "No":
                            odds_btts["no"].append(float(v["odd"]))
                elif bet["name"] == "HT/FT Double":
                    for v in bet["values"]:
                        parts = v["value"].split("/")
                        if len(parts) == 2 and parts[0] in HTFT_SIDE and parts[1] in HTFT_SIDE:
                            key = f"htft:{HTFT_SIDE[parts[0]]}/{HTFT_SIDE[parts[1]]}"
                            odds_htft.setdefault(key, []).append(float(v["odd"]))

        def avg(lst):
            return round(sum(lst) / len(lst), 2) if lst else None

        result = {
            "home_win": avg(odds_1x2["home"]), "draw": avg(odds_1x2["draw"]), "away_win": avg(odds_1x2["away"]),
            "over25": avg(odds_ou["over"]), "under25": avg(odds_ou["under"]),
            "home_over15": avg(odds_team_total["home_over15"]), "home_under15": avg(odds_team_total["home_under15"]),
            "away_over15": avg(odds_team_total["away_over15"]), "away_under15": avg(odds_team_total["away_under15"]),
            "dc_1x": avg(odds_dc["dc_1x"]), "dc_x2": avg(odds_dc["dc_x2"]), "dc_12": avg(odds_dc["dc_12"]),
            "btts_yes": avg(odds_btts["yes"]), "btts_no": avg(odds_btts["no"]),
        }
        for key, lst in odds_htft.items():
            result[key] = avg(lst)
        return result
    except Exception:
        return None


def fetch_lineups_available(fixture_id):
    try:
        r = _api_get("/fixtures/lineups", params={"fixture": fixture_id}, timeout=10)
        data = r.json()
        return bool(data.get("response"))
    except Exception:
        return False


def fetch_fixture_injuries(fixture_id):
    try:
        r = _api_get("/injuries", params={"fixture": fixture_id}, timeout=10)
        data = r.json()
        if data.get("errors") or not data.get("response"):
            return 0, 0, False
        home_count = 0
        away_count = 0
        home_team_id = None
        for inj in data["response"]:
            if home_team_id is None:
                home_team_id = inj["team"]["id"]
            if inj["team"]["id"] == home_team_id:
                home_count += 1
            else:
                away_count += 1
        return home_count, away_count, True
    except Exception:
        return 0, 0, False


def fetch_fixture_lineups_full(fixture_id):
    """Връща реалния потвърден състав (стартиращи + резерви) с player_id, или None ако още няма."""
    try:
        r = _api_get("/fixtures/lineups", params={"fixture": fixture_id}, timeout=10)
        data = r.json()
        if not data.get("response"):
            return None
        result = {}
        for team_block in data["response"]:
            team_name = team_block["team"]["name"]
            starters = [{"player_id": p["player"]["id"], "name": p["player"]["name"],
                         "pos": p["player"].get("pos")} for p in team_block.get("startXI", [])]
            subs = [{"player_id": p["player"]["id"], "name": p["player"]["name"],
                     "pos": p["player"].get("pos")} for p in team_block.get("substitutes", [])]
            result[team_name] = {"starters": starters, "substitutes": subs}
        return result
    except Exception:
        return None


def fetch_team_recent_form(team_id, league_id, season, exclude_fixture_id, n=5):
    """Фаза P.1 (21.08.2026): последните n изиграни мача на отбор В СЪЩАТА
    лига (не всички турнири на отбора) - чисто информативно на /match_detail,
    не вход за модела. exclude_fixture_id маха текущия преглеждан мач, ако
    вече е приключил и се е промъкнал в резултата."""
    try:
        r = _api_get("/fixtures", params={"team": team_id, "league": league_id, "season": season,
                                            "last": n + 3}, timeout=10)
        data = r.json()
        if data.get("errors") or not data.get("response"):
            return None
        out = []
        for f in data["response"]:
            if f["fixture"]["status"]["short"] not in FINISHED_STATUSES:
                continue
            if f["fixture"]["id"] == exclude_fixture_id:
                continue
            hg, ag = f["goals"]["home"], f["goals"]["away"]
            if hg is None or ag is None:
                continue
            is_home = f["teams"]["home"]["id"] == team_id
            gf, ga = (hg, ag) if is_home else (ag, hg)
            opponent = f["teams"]["away"]["name"] if is_home else f["teams"]["home"]["name"]
            if gf > ga:
                result = "W"
            elif gf < ga:
                result = "L"
            else:
                result = "D"
            out.append({
                "date": f["fixture"]["date"][:10], "opponent": opponent,
                "gf": gf, "ga": ga, "is_home": is_home, "result": result,
            })
        out.sort(key=lambda x: x["date"], reverse=True)
        return out[:n]
    except Exception:
        return None


def fetch_league_standings_for_teams(league_id, season, home_id, away_id):
    """Фаза P.1 (21.08.2026): текуща позиция в таблицата за двата отбора -
    чисто информативно. Групите (UEFA турнири с групова фаза) се сплескват
    в едно - връща None за отбор, който не е намерен (напр. чист knockout
    турнир без класическа таблица), не гърми."""
    try:
        r = _api_get("/standings", params={"league": league_id, "season": season}, timeout=10)
        data = r.json()
        if data.get("errors") or not data.get("response"):
            return None
        groups = data["response"][0]["league"]["standings"]
        flat = [row for group in groups for row in group]
        total = len(flat)
        by_id = {row["team"]["id"]: row for row in flat}

        def pick(tid):
            row = by_id.get(tid)
            if not row:
                return None
            return {"rank": row["rank"], "points": row["points"],
                     "played": row["all"]["played"], "form": row.get("form")}

        return {"home": pick(home_id), "away": pick(away_id), "total_teams": total}
    except Exception:
        return None


def fetch_upcoming_fixtures(league, from_date=None, to_date=None, use_cache=False, cache_minutes=20):
    # ALL_LEAGUES е регистърът на лигите, притежаван от match_predictor_app.py
    # (референциран и от шаблони/друга бизнес логика там) - НЕ се дублира тук.
    # Ленив import вътре в тялото (същия идиом като run_refresh_all() ->
    # `import incremental_refresh`) - изпълнява се само при реално извикване,
    # когато match_predictor_app вече е напълно зареден, значи без кръгов import.
    import match_predictor_app as _mpa
    today = date.today()
    if from_date is None:
        from_date = today
    if to_date is None:
        to_date = today + timedelta(days=DAYS_AHEAD)

    # 22.08.2026: use_cache=True се подава САМО от фоновите задачи (виж
    # run_refresh_odds_cache/run_refresh_injuries_cache/
    # build_predictions_snapshot.py) - те и трите питат за практически
    # същия списък мачове на всеки 30 мин, независимо една от друга. Кратък
    # TTL кеш споделен между тях среже трикратното повторение. НИКОГА не се
    # включва от страниците, които потребителят реално гледа (/daily,
    # _predict_matches_for_league_from_snapshot) - там живия статус/резултат
    # на мача трябва да е пресен към момента на зареждане, не до 20 мин стар.
    if use_cache:
        import system_tracker as _st
        cached = _st.get_cached_fixture_list(league, from_date.isoformat(), to_date.isoformat(), cache_minutes)
        if cached is not None:
            return cached, None

    params = {
        "league": _mpa.ALL_LEAGUES[league]["id"],
        "season": from_date.year if from_date.month >= 7 else from_date.year - 1,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "timezone": "Europe/Sofia",
    }
    try:
        r = _api_get("/fixtures", params=params, timeout=15)
        data = r.json()
    except Exception as e:
        return [], f"Мрежова грешка при връзка с API-то: {e}"

    if data.get("errors"):
        errors = data["errors"]
        if isinstance(errors, dict) and "plan" in errors:
            return [], (f"Ограничение на абонаментния план: {errors['plan']} "
                         "Провери плана си в dashboard.api-football.com.")
        return [], f"Грешка от API-то: {errors}"

    fixtures = data.get("response", [])
    if use_cache:
        import system_tracker as _st
        _st.set_cached_fixture_list(league, from_date.isoformat(), to_date.isoformat(), fixtures)
    return fixtures, None


def fetch_fixture_id_for_today(league, home, away):
    # get_league_ids() зависи от Flask request.cookies (кой лиги е активирал
    # Дака) - живее в match_predictor_app.py. Ленив import вътре в тялото,
    # виж коментара в fetch_upcoming_fixtures() по-горе за пълната обосновка.
    import match_predictor_app as _mpa
    today = date.today()
    season = today.year if today.month >= 7 else today.year - 1
    try:
        r = _api_get("/fixtures", params={"league": _mpa.get_league_ids()[league], "date": today.isoformat(),
                                            "season": season, "timezone": "Europe/Sofia"}, timeout=10)
        data = r.json()
        if data.get("errors"):
            print(f"fetch_fixture_id_for_today грешка: {data['errors']}")
        for f in data.get("response", []):
            if f["teams"]["home"]["name"] == home and f["teams"]["away"]["name"] == away:
                return f["fixture"]["id"]
    except Exception as e:
        print(f"fetch_fixture_id_for_today изключение: {e}")
    return None
