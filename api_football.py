"""
api_football.py — API-Football HTTP клиент, изваден от match_predictor_app.py
(ARCHITECTURE.md, Граница 4, втора част, 22.08.2026).

Чисто преместване, не пренаписване: всяка функция тук е преместена бит-по-бит
(сигнатура, timeout-и, параметри) от match_predictor_app.py, без промяна в
поведението. match_predictor_app.py импортира оттук вместо да дефинира
локално - вижте validation/ за преди/след доказателство на всяка стъпка.
"""
from datetime import date, timedelta
import requests

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
API_HEADERS = {"x-apisports-key": API_KEY}
FINISHED_STATUSES = {"FT", "AET", "PEN", "AWD", "WO"}
DAYS_AHEAD = 7


def fetch_fixture_predictions(fixture_id):
    """Тегли вградената прогноза на API-Football - само за информативно сравнение"""
    try:
        r = requests.get(f"{BASE_URL}/predictions", headers=API_HEADERS,
                          params={"fixture": fixture_id}, timeout=10)
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
    # "HT/FT Double". Corners/cards/BTTS НЕ се парсват тук - вече REJECTED
    # tier в prediction_policy.py, коефициент за тях няма практическа стойност.
    try:
        r = requests.get(f"{BASE_URL}/odds", headers=API_HEADERS,
                          params={"fixture": fixture_id}, timeout=10)
        data = r.json()
        if data.get("errors") or not data.get("response"):
            return None

        odds_1x2 = {"home": [], "draw": [], "away": []}
        odds_ou = {"over": [], "under": []}
        odds_team_total = {"home_over15": [], "home_under15": [], "away_over15": [], "away_under15": []}
        odds_dc = {"dc_1x": [], "dc_x2": [], "dc_12": []}
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
        }
        for key, lst in odds_htft.items():
            result[key] = avg(lst)
        return result
    except Exception:
        return None


def fetch_lineups_available(fixture_id):
    try:
        r = requests.get(f"{BASE_URL}/fixtures/lineups", headers=API_HEADERS,
                          params={"fixture": fixture_id}, timeout=10)
        data = r.json()
        return bool(data.get("response"))
    except Exception:
        return False


def fetch_fixture_injuries(fixture_id):
    try:
        r = requests.get(f"{BASE_URL}/injuries", headers=API_HEADERS,
                          params={"fixture": fixture_id}, timeout=10)
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
        r = requests.get(f"{BASE_URL}/fixtures/lineups", headers=API_HEADERS,
                          params={"fixture": fixture_id}, timeout=10)
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
        r = requests.get(f"{BASE_URL}/fixtures", headers=API_HEADERS,
                          params={"team": team_id, "league": league_id, "season": season,
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
        r = requests.get(f"{BASE_URL}/standings", headers=API_HEADERS,
                          params={"league": league_id, "season": season}, timeout=10)
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


def fetch_upcoming_fixtures(league, from_date=None, to_date=None):
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
    params = {
        "league": _mpa.ALL_LEAGUES[league]["id"],
        "season": from_date.year if from_date.month >= 7 else from_date.year - 1,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "timezone": "Europe/Sofia",
    }
    try:
        r = requests.get(f"{BASE_URL}/fixtures", headers=API_HEADERS, params=params, timeout=15)
        data = r.json()
    except Exception as e:
        return [], f"Мрежова грешка при връзка с API-то: {e}"

    if data.get("errors"):
        errors = data["errors"]
        if isinstance(errors, dict) and "plan" in errors:
            return [], (f"Ограничение на абонаментния план: {errors['plan']} "
                         "Провери плана си в dashboard.api-football.com.")
        return [], f"Грешка от API-то: {errors}"

    return data.get("response", []), None
