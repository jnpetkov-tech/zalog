import sys
import requests
import numpy as np
import pandas as pd
from scipy.stats import poisson
import football_lib as fl
from production_pipeline import fit_ht_2h_models, predict_ht_ft

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

LEAGUE_IDS = {
    "bulgaria": 172,
    "england": 39,
    "germany": 78,
    "spain": 140,
    "france": 61,
}

DAYS_AHEAD = 7


def fetch_upcoming_fixtures(league_id, days_ahead=7):
    from datetime import date, timedelta
    today = date.today()
    to_date = today + timedelta(days=days_ahead)
    url = f"{BASE_URL}/fixtures"
    params = {
        "league": league_id,
        "season": today.year if today.month >= 7 else today.year - 1,
        "from": today.isoformat(),
        "to": to_date.isoformat(),
    }
    r = requests.get(url, headers=headers, params=params)
    data = r.json()
    if data.get("errors"):
        print(f"Грешка: {data['errors']}")
        return []
    return data.get("response", [])


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "bulgaria"
    if league not in LEAGUE_IDS:
        print(f"Непозната лига: {league}. Налични: {list(LEAGUE_IDS.keys())}")
        sys.exit(1)

    print(f"Тегля предстоящи мачове за {league}...")
    fixtures = fetch_upcoming_fixtures(LEAGUE_IDS[league], DAYS_AHEAD)
    print(f"Намерени {len(fixtures)} предстоящи мача.\n")

    if not fixtures:
        print("Няма предстоящи мачове в този период.")
        return

    print("Зареждам и тренирам моделите...")
    df = fl.load_league_data(league)
    teams, n, team_idx = fl.get_team_index(df)
    ref_date = df["date"].max()

    ft_model = fl.fit_goals_model(df, ref_date, team_idx, n)
    ht_model, h2_model = fit_ht_2h_models(df, team_idx, n)
    print("Готово.\n")

    results = []
    for f in fixtures:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        match_date = f["fixture"]["date"][:16].replace("T", " ")

        if home not in team_idx or away not in team_idx:
            continue

        lam, mu = fl.get_lambdas(ft_model, team_idx, home, away)
        lam_ht, mu_ht = fl.get_lambdas(ht_model, team_idx, home, away)
        lam_2h, mu_2h = fl.get_lambdas(h2_model, team_idx, home, away)
        ht_ft_probs = predict_ht_ft(lam_ht, mu_ht, lam_2h, mu_2h)

        best_label, best_pct = fl.select_best_pick(lam, mu, ht_ft_probs)

        results.append({
            "date": match_date,
            "home_team": home,
            "away_team": away,
            "best_pick": best_label,
            "confidence_%": round(best_pct, 1),
        })

    results_df = pd.DataFrame(results).sort_values("confidence_%", ascending=False)
    output_path = f"best_picks_{league}_{pd.Timestamp.now().strftime('%Y%m%d')}.csv"
    results_df.to_csv(output_path, index=False, encoding="utf-8")

    print(f"Прогнози записани в {output_path}\n")
    print(results_df.to_string(index=False))


if __name__ == "__main__":
    main()
