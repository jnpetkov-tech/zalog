"""
api_football.py — API-Football HTTP клиент, изваден от match_predictor_app.py
(ARCHITECTURE.md, Граница 4, втора част, 22.08.2026).

Чисто преместване, не пренаписване: всяка функция тук е преместена бит-по-бит
(сигнатура, timeout-и, параметри) от match_predictor_app.py, без промяна в
поведението. match_predictor_app.py импортира оттук вместо да дефинира
локално - вижте validation/ за преди/след доказателство на всяка стъпка.
"""
import requests

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
API_HEADERS = {"x-apisports-key": API_KEY}


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
