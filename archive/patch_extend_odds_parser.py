import ast

with open("match_predictor_app.py", "r") as f:
    content = f.read()

old = '''def fetch_fixture_odds(fixture_id):
    try:
        r = requests.get(f"{BASE_URL}/odds", headers=API_HEADERS,
                          params={"fixture": fixture_id}, timeout=10)
        data = r.json()
        if data.get("errors") or not data.get("response"):
            return None

        odds_1x2 = {"home": [], "draw": [], "away": []}
        odds_ou = {"over": [], "under": []}

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

        def avg(lst):
            return round(sum(lst) / len(lst), 2) if lst else None

        return {
            "home_win": avg(odds_1x2["home"]), "draw": avg(odds_1x2["draw"]), "away_win": avg(odds_1x2["away"]),
            "over25": avg(odds_ou["over"]), "under25": avg(odds_ou["under"]),
        }
    except Exception:
        return None'''

new = '''def fetch_fixture_odds(fixture_id):
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
        return None'''

assert content.count(old) == 1, f"anchor count={content.count(old)}"
content = content.replace(old, new)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - fetch_fixture_odds() extended (D2).")
