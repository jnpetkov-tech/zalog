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

train_df = df[df["season"].isin([2022, 2023])].reset_index(drop=True)
test_df = df[df["season"] == 2024].reset_index(drop=True)

print(f"Тренировъчни данни: {len(train_df)} мача (сезони 2022-2023)")
print(f"Тестови данни: {len(test_df)} мача (сезон 2024)\n")

teams = sorted(set(train_df.home_team) | set(train_df.away_team))
n = len(teams)
team_idx = {t: i for i, t in enumerate(teams)}

home_idx = train_df["home_team"].map(team_idx).to_numpy()
away_idx = train_df["away_team"].map(team_idx).to_numpy()
home_goals = train_df["home_goals"].to_numpy()
away_goals = train_df["away_goals"].to_numpy()

XI = 0.0018
most_recent_date = train_df["date"].max()
days_ago = (most_recent_date - train_df["date"]).dt.days.to_numpy()
weights = np.exp(-XI * days_ago)

mask00 = (home_goals == 0) & (away_goals == 0)
mask01 = (home_goals == 0) & (away_goals == 1)
mask10 = (home_goals == 1) & (away_goals == 0)
mask11 = (home_goals == 1) & (away_goals == 1)


def dc_tau(x, y, lam, mu, rho):
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    elif x == 0 and y == 1:
        return 1 + lam * rho
    elif x == 1 and y == 0:
        return 1 + mu * rho
    elif x == 1 and y == 1:
        return 1 - rho
    else:
        return 1.0


def neg_log_likelihood(params):
    attack = params[:n]
    defence = params[n:2 * n]
    home_adv = params[-2]
    rho = params[-1]

    lam = np.exp(attack[home_idx] - defence[away_idx] + home_adv)
    mu = np.exp(attack[away_idx] - defence[home_idx])

    tau = np.ones(len(home_goals))
    tau[mask00] = 1 - lam[mask00] * mu[mask00] * rho
    tau[mask01] = 1 + lam[mask01] * rho
    tau[mask10] = 1 + mu[mask10] * rho
    tau[mask11] = 1 - rho
    tau = np.clip(tau, 1e-10, None)

    ll = (np.log(tau) + poisson.logpmf(home_goals, lam) + poisson.logpmf(away_goals, mu))
    return -np.sum(ll * weights)


t0 = time.time()
x0 = np.zeros(2 * n + 2)
bounds = [(None, None)] * (2 * n + 1) + [(-1, 1)]
result = minimize(neg_log_likelihood, x0, method="L-BFGS-B", bounds=bounds)
attack = result.x[:n]
defence = result.x[n:2 * n]
home_adv = result.x[-2]
rho = result.x[-1]
print(f"Моделът е трениран за {time.time()-t0:.2f} секунди.")
print(f"Fitted rho (корекция ниски резултати): {rho:.4f}\n")


def predict_match(home, away, max_goals=8):
    if home not in team_idx or away not in team_idx:
        return None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv)
    mu = np.exp(attack[ai] - defence[hi])

    prob_matrix = np.outer(poisson.pmf(range(max_goals), lam), poisson.pmf(range(max_goals), mu))

    for x in range(2):
        for y in range(2):
            prob_matrix[x, y] *= dc_tau(x, y, lam, mu, rho)

    prob_matrix /= prob_matrix.sum()

    home_win = np.sum(np.tril(prob_matrix, -1))
    draw = np.sum(np.diag(prob_matrix))
    away_win = np.sum(np.triu(prob_matrix, 1))
    return {"home_win": home_win, "draw": draw, "away_win": away_win}


correct = 0
total = 0
log_loss_sum = 0
results_log = []

for _, row in test_df.iterrows():
    pred = predict_match(row.home_team, row.away_team)
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
        "match": f"{row.home_team} vs {row.away_team}",
        "actual": f"{row.home_goals}-{row.away_goals}",
        "predicted_home_%": round(pred["home_win"] * 100, 1),
        "predicted_draw_%": round(pred["draw"] * 100, 1),
        "predicted_away_%": round(pred["away_win"] * 100, 1),
        "model_choice": predicted_outcome,
        "correct": predicted_outcome == actual,
    })

print("=" * 60)
print("РЕЗУЛТАТИ — DIXON-COLES МОДЕЛ (сезон 2024, невиждани данни)")
print("=" * 60)
print(f"Общо тествани мачове: {total}")
print(f"Точност (accuracy): {correct/total*100:.1f}%")
print(f"Log loss: {log_loss_sum/total:.3f}")
print("\n(За сравнение — базовият модел без подобрения: 50.9% accuracy, log loss 1.029)")

results_df = pd.DataFrame(results_log)
results_df.to_csv("backtest_results_dixon_coles.csv", index=False, encoding="utf-8")
print(f"\nПодробен лог: backtest_results_dixon_coles.csv")
