"""
Разширение: BTTS (двата отбора вкарват) и Over/Under 2.5 гола
================================================================
Ползва СЪЩИЯ Dixon-Coles walk-forward модел - просто извличаме
допълнителна информация от вероятностната матрица, която вече
изчисляваме за 1X2. Без нови данни, без нов модел.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
import time

df = pd.read_csv("bulgaria_first_league_matches.csv")
df = df.dropna(subset=["home_goals", "away_goals"])
df["home_goals"] = df["home_goals"].astype(int)
df["away_goals"] = df["away_goals"].astype(int)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

all_teams = sorted(set(df.home_team) | set(df.away_team))
n = len(all_teams)
team_idx = {t: i for i, t in enumerate(all_teams)}

XI = 0.0018

def fit_model(history_df, ref_date):
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

    def neg_log_likelihood(params):
        attack = params[:n]
        defence = params[n:2 * n]
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

        ll = (np.log(tau) + poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu))
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 2)
    bounds = [(None, None)] * (2 * n + 1) + [(-1, 1)]
    result = minimize(neg_log_likelihood, x0, method="L-BFGS-B", bounds=bounds)
    return result.x[:n], result.x[n:2*n], result.x[-2], result.x[-1]


def get_prob_matrix(attack, defence, home_adv, rho, home, away, max_goals=8):
    if home not in team_idx or away not in team_idx:
        return None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv)
    mu = np.exp(attack[ai] - defence[hi])

    prob_matrix = np.outer(poisson.pmf(range(max_goals), lam), poisson.pmf(range(max_goals), mu))
    for x in range(2):
        for y in range(2):
            if x == 0 and y == 0:
                prob_matrix[x, y] *= (1 - lam * mu * rho)
            elif x == 0 and y == 1:
                prob_matrix[x, y] *= (1 + lam * rho)
            elif x == 1 and y == 0:
                prob_matrix[x, y] *= (1 + mu * rho)
            elif x == 1 and y == 1:
                prob_matrix[x, y] *= (1 - rho)
    prob_matrix /= prob_matrix.sum()
    return prob_matrix


def markets_from_matrix(pm):
    max_goals = pm.shape[0]
    btts_yes = 0.0
    over25 = 0.0
    for x in range(max_goals):
        for y in range(max_goals):
            if x >= 1 and y >= 1:
                btts_yes += pm[x, y]
            if x + y > 2.5:
                over25 += pm[x, y]
    return {
        "btts_yes": btts_yes, "btts_no": 1 - btts_yes,
        "over25": over25, "under25": 1 - over25,
    }


test_df = df[df["season"] == 2024].reset_index(drop=True)
print(f"Тестови мачове: {len(test_df)}\n")

t0 = time.time()
RETRAIN_EVERY = 10
attack = defence = home_adv = rho = None

correct_1x2 = correct_btts = correct_ou = 0
total = 0
results_log = []

for i, row in test_df.iterrows():
    if i % RETRAIN_EVERY == 0:
        history = df[df["date"] < row["date"]]
        attack, defence, home_adv, rho = fit_model(history, row["date"])

    pm = get_prob_matrix(attack, defence, home_adv, rho, row.home_team, row.away_team)
    if pm is None:
        continue

    markets = markets_from_matrix(pm)

    # реални изходи
    actual_btts = "btts_yes" if (row.home_goals >= 1 and row.away_goals >= 1) else "btts_no"
    actual_ou = "over25" if (row.home_goals + row.away_goals) > 2.5 else "under25"

    # прогнози на модела
    pred_btts = "btts_yes" if markets["btts_yes"] > markets["btts_no"] else "btts_no"
    pred_ou = "over25" if markets["over25"] > markets["under25"] else "under25"

    total += 1
    if pred_btts == actual_btts:
        correct_btts += 1
    if pred_ou == actual_ou:
        correct_ou += 1

    results_log.append({
        "match": f"{row.home_team} vs {row.away_team}",
        "actual_score": f"{row.home_goals}-{row.away_goals}",
        "btts_yes_%": round(markets["btts_yes"] * 100, 1),
        "btts_prediction": pred_btts,
        "btts_actual": actual_btts,
        "btts_correct": pred_btts == actual_btts,
        "over25_%": round(markets["over25"] * 100, 1),
        "ou_prediction": pred_ou,
        "ou_actual": actual_ou,
        "ou_correct": pred_ou == actual_ou,
    })

print(f"Общо време: {time.time()-t0:.1f}s\n")
print("=" * 60)
print("РЕЗУЛТАТИ ПО ПАЗАРИ (сезон 2024, walk-forward)")
print("=" * 60)
print(f"Общо тествани мачове: {total}\n")
print(f"BTTS (двата отбора вкарват) accuracy: {correct_btts/total*100:.1f}%")
print(f"Over/Under 2.5 гола accuracy: {correct_ou/total*100:.1f}%")
print(f"\n(За сравнение - 1X2 walk-forward accuracy: 50.0%)")

results_df = pd.DataFrame(results_log)
results_df.to_csv("backtest_results_markets.csv", index=False, encoding="utf-8")
print(f"\nПодробен лог: backtest_results_markets.csv")
print("\nПримери:")
print(results_df.head(10).to_string(index=False))
