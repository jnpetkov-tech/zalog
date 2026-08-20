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


def predict_match(attack, defence, home_adv, rho, home, away, max_goals=8):
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

    home_win = np.sum(np.tril(prob_matrix, -1))
    draw = np.sum(np.diag(prob_matrix))
    away_win = np.sum(np.triu(prob_matrix, 1))
    return {"home_win": home_win, "draw": draw, "away_win": away_win}


test_df = df[df["season"] == 2024].reset_index(drop=True)
print(f"Тестови мачове (walk-forward): {len(test_df)}\n")

t0 = time.time()
correct = 0
total = 0
log_loss_sum = 0
results_log = []
retrain_counter = 0

RETRAIN_EVERY = 10
attack = defence = home_adv = rho = None

for i, row in test_df.iterrows():
    if i % RETRAIN_EVERY == 0:
        history = df[df["date"] < row["date"]]
        attack, defence, home_adv, rho = fit_model(history, row["date"])
        retrain_counter += 1

    pred = predict_match(attack, defence, home_adv, rho, row.home_team, row.away_team)
    if pred is None:
        continue

    if row.home_goals > row.away_goals:
        actual = "home_win"
    elif row.home_goals == row.away_goals:
        actual = "draw"
    else:
        actual = "away_win"

    predicted_outcome = max(pred, key=pred.get)
    total += 1
    if predicted_outcome == actual:
        correct += 1
    p_actual = max(pred[actual], 1e-10)
    log_loss_sum += -np.log(p_actual)

    results_log.append({
        "date": row["date"].date(),
        "match": f"{row.home_team} vs {row.away_team}",
        "actual": f"{row.home_goals}-{row.away_goals}",
        "predicted_home_%": round(pred["home_win"] * 100, 1),
        "predicted_draw_%": round(pred["draw"] * 100, 1),
        "predicted_away_%": round(pred["away_win"] * 100, 1),
        "model_choice": predicted_outcome,
        "correct": predicted_outcome == actual,
    })

print(f"Общо време: {time.time()-t0:.1f}s ({retrain_counter} преобучавания)\n")
print("=" * 60)
print("РЕЗУЛТАТИ — WALK-FORWARD МОДЕЛ (отчита текуща форма)")
print("=" * 60)
print(f"Общо тествани мачове: {total}")
print(f"Точност (accuracy): {correct/total*100:.1f}%")
print(f"Log loss: {log_loss_sum/total:.3f}")
print("\nЗа сравнение:")
print("  Базов Poisson (без подобрения): 50.9% accuracy, log loss 1.029")
print("  Dixon-Coles (статичен, с time-decay): 51.2% accuracy, log loss 1.023")

results_df = pd.DataFrame(results_log)
results_df.to_csv("backtest_results_walkforward.csv", index=False, encoding="utf-8")
print(f"\nПодробен лог: backtest_results_walkforward.csv")
