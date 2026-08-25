import requests
import csv
import time
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

LEAGUES_TO_FIND = {
    "Germany": "Bundesliga",
    "Italy": "Serie A",
    "Spain": "La Liga",
}

SEASONS = [2022, 2023, 2024]


def find_league_id(country, name_search):
    url = f"{BASE_URL}/leagues"
    params = {"search": name_search, "country": country}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()
    for item in data.get("response", []):
        if item["league"]["type"] == "League":
            return item["league"]["id"], item["league"]["name"]
    return None, None


def fetch_season(league_id, season):
    url = f"{BASE_URL}/fixtures"
    params = {"league": league_id, "season": season, "status": "FT"}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()
    if data.get("errors"):
        print(f"    Грешка: {data['errors']}")
        return []
    return data.get("response", [])


def fetch_league_data(league_id, csv_path):
    all_matches = []
    for season in SEASONS:
        fixtures = fetch_season(league_id, season)
        print(f"    Сезон {season}: {len(fixtures)} мача")
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

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=[
            "season", "date", "home_team", "away_team", "home_goals", "away_goals"
        ])
        writer.writeheader()
        writer.writerows(all_matches)
    return len(all_matches)


XI = 0.0018


def fit_model(history_df, ref_date, team_idx, n):
    h_idx = history_df["home_team"].map(team_idx).to_numpy()
    a_idx = history_df["away_team"].map(team_idx).to_numpy()
    hg = history_df["home_goals"].to_numpy()
    ag = history_df["away_goals"].to_numpy()
    days_ago = (ref_date - history_df["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    mask00 = (hg == 0) & (ag == 0)
    mask01 = (hg == 0) & (ag == 1)
    mask10 = (hg == 1) & (ag == 0)
    mask11 = (hg == 1) & (ag == 1)

    def nll(params):
        attack = params[:n]
        defence = params[n:2*n]
        home_adv = params[-2]
        rho = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv)
        mu = np.exp(attack[a_idx] - defence[h_idx])
        tau = np.ones(len(hg))
        tau[mask00] = 1 - lam[mask00] * mu[mask00] * rho
        tau[mask01] = 1 + lam[mask01] * rho
        tau[mask10] = 1 + mu[mask10] * rho
        tau[mask11] = 1 - rho
        tau = np.clip(tau, 1e-10, None)
        ll = np.log(tau) + poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2*n+2)
    bounds = [(None, None)]*(2*n+1) + [(-1, 1)]
    r = minimize(nll, x0, method="L-BFGS-B", bounds=bounds)
    return r.x[:n], r.x[n:2*n], r.x[-2], r.x[-1]


def get_prob_matrix(attack, defence, home_adv, rho, team_idx, home, away, max_goals=8):
    if home not in team_idx or away not in team_idx:
        return None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv)
    mu = np.exp(attack[ai] - defence[hi])
    pm = np.outer(poisson.pmf(range(max_goals), lam), poisson.pmf(range(max_goals), mu))
    pm[0, 0] *= (1 - lam * mu * rho)
    pm[0, 1] *= (1 + lam * rho)
    pm[1, 0] *= (1 + mu * rho)
    pm[1, 1] *= (1 - rho)
    pm /= pm.sum()
    return pm


def markets_from_matrix(pm):
    max_goals = pm.shape[0]
    btts_yes = over25 = 0.0
    for x in range(max_goals):
        for y in range(max_goals):
            if x >= 1 and y >= 1:
                btts_yes += pm[x, y]
            if x + y > 2.5:
                over25 += pm[x, y]
    return {"home_win": np.sum(np.tril(pm, -1)), "draw": np.sum(np.diag(pm)),
            "away_win": np.sum(np.triu(pm, 1)),
            "btts_yes": btts_yes, "btts_no": 1 - btts_yes,
            "over25": over25, "under25": 1 - over25}


def backtest_league(csv_path):
    df = pd.read_csv(csv_path)
    df = df.dropna(subset=["home_goals", "away_goals"])
    df["home_goals"] = df["home_goals"].astype(int)
    df["away_goals"] = df["away_goals"].astype(int)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    teams = sorted(set(df.home_team) | set(df.away_team))
    n = len(teams)
    team_idx = {t: i for i, t in enumerate(teams)}

    test_df = df[df["season"] == 2024].reset_index(drop=True)

    RETRAIN_EVERY = 15
    attack = defence = home_adv = rho = None
    correct_1x2 = correct_btts = correct_ou = 0
    total = 0

    for i, row in test_df.iterrows():
        if i % RETRAIN_EVERY == 0:
            history = df[df["date"] < row["date"]]
            attack, defence, home_adv, rho = fit_model(history, row["date"], team_idx, n)

        pm = get_prob_matrix(attack, defence, home_adv, rho, team_idx, row.home_team, row.away_team)
        if pm is None:
            continue
        m = markets_from_matrix(pm)

        if row.home_goals > row.away_goals:
            actual_1x2 = "home_win"
        elif row.home_goals == row.away_goals:
            actual_1x2 = "draw"
        else:
            actual_1x2 = "away_win"
        actual_btts = "btts_yes" if (row.home_goals >= 1 and row.away_goals >= 1) else "btts_no"
        actual_ou = "over25" if (row.home_goals + row.away_goals) > 2.5 else "under25"

        pred_1x2 = max(("home_win", "draw", "away_win"), key=lambda k: m[k])
        pred_btts = "btts_yes" if m["btts_yes"] > m["btts_no"] else "btts_no"
        pred_ou = "over25" if m["over25"] > m["under25"] else "under25"

        total += 1
        correct_1x2 += (pred_1x2 == actual_1x2)
        correct_btts += (pred_btts == actual_btts)
        correct_ou += (pred_ou == actual_ou)

    return {
        "n_test": total,
        "1x2": correct_1x2/total*100,
        "btts": correct_btts/total*100,
        "ou": correct_ou/total*100,
    }


results_summary = {}

for country, search_name in LEAGUES_TO_FIND.items():
    print(f"\n{'='*50}")
    print(f"{country} - {search_name}")
    print('='*50)

    league_id, league_name = find_league_id(country, search_name)
    if league_id is None:
        print(f"  НЕ Е НАМЕРЕНА лига за {country}")
        continue
    print(f"  League ID: {league_id} ({league_name})")

    csv_path = f"{country.lower()}_matches.csv"
    print(f"  Тегля данни...")
    total_matches = fetch_league_data(league_id, csv_path)
    print(f"  Общо: {total_matches} мача записани в {csv_path}")

    print(f"  Пускам backtest (walk-forward, сезон 2024)...")
    result = backtest_league(csv_path)
    results_summary[country] = result
    print(f"  1X2: {result['1x2']:.1f}% | BTTS: {result['btts']:.1f}% | O/U 2.5: {result['ou']:.1f}%")

print(f"\n\n{'='*60}")
print("ОБОБЩЕНА ТАБЛИЦА - ВСИЧКИ ЛИГИ")
print('='*60)
print(f"{'Лига':<12} {'1X2':>8} {'BTTS':>8} {'O/U 2.5':>8}")
for country, r in results_summary.items():
    print(f"{country:<12} {r['1x2']:>7.1f}% {r['btts']:>7.1f}% {r['ou']:>7.1f}%")
print(f"\nЗа сравнение:")
print(f"{'Bulgaria':<12} {50.0:>7.1f}% {56.1:>7.1f}% {53.1:>7.1f}%")
print(f"{'England':<12} {53.7:>7.1f}% {56.1:>7.1f}% {58.9:>7.1f}%")
