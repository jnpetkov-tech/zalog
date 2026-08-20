import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
import time

df = pd.read_csv("bulgaria_first_league_matches.csv")
df = df.dropna(subset=["home_goals", "away_goals"])
df["home_goals"] = df["home_goals"].astype(int)
df["away_goals"] = df["away_goals"].astype(int)

train_df = df[df["season"].isin([2022, 2023])].reset_index(drop=True)
test_df = df[df["season"] == 2024].reset_index(drop=True)

print(f"Тренировъчни данни: {len(train_df)} мача (сезони 2022-2023)")
print(f"Тестови данни: {len(test_df)} мача (сезон 2024, моделът НЕ ги е виждал)\n")

teams = sorted(set(train_df.home_team) | set(train_df.away_team))
n = len(teams)
team_idx = {t: i for i, t in enumerate(teams)}

home_idx = train_df["home_team"].map(team_idx).to_numpy()
away_idx = train_df["away_team"].map(team_idx).to_numpy()
home_goals = train_df["home_goals"].to_numpy()
away_goals = train_df["away_goals"].to_numpy()

def neg_log_likelihood(params):
    attack = params[:n]
    defence = params[n:2 * n]
    home_adv = params[-1]
    lam_home = np.exp(attack[home_idx] - defence[away_idx] + home_adv)
    lam_away = np.exp(attack[away_idx] - defence[home_idx])
    ll = np.sum(poisson.logpmf(home_goals, lam_home)) + np.sum(poisson.logpmf(away_goals, lam_away))
    return -ll

t0 = time.time()
x0 = np.zeros(2 * n + 1)
result = minimize(neg_log_likelihood, x0, method="L-BFGS-B")
attack = result.x[:n]
defence = result.x[n:2 * n]
home_adv = result.x[-1]
print(f"Моделът е трениран за {time.time()-t0:.2f} секунди.\n")

def predict_match(home, away, max_goals=8):
    if home not in team_idx or away not in team_idx:
        return None
    hi, ai = team_idx[home], team_idx[away]
    lam_home = np.exp(attack[hi] - defence[ai] + home_adv)
    lam_away = np.exp(attack[ai] - defence[hi])
    prob_matrix = np.outer(poisson.pmf(range(max_goals), lam_home), poisson.pmf(range(max_goals), lam_away))
    home_win = np.sum(np.tril(prob_matrix, -1))
    draw = np.sum(np.diag(prob_matrix))
    away_win = np.sum(np.triu(prob_matrix, 1))
    return {"home_win": home_win, "draw": draw, "away_win": away_win}

correct = 0
total = 0
log_loss_sum = 0
naive_correct = 0
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
    if actual == "home_win":
        naive_correct += 1
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
print("РЕЗУЛТАТИ ОТ BACKTESTING (сезон 2024, невиждани данни)")
print("=" * 60)
print(f"Общо тествани мачове: {total}")
print(f"Модел точност (accuracy): {correct/total*100:.1f}%")
print(f"Naive baseline (винаги 'домакинът печели'): {naive_correct/total*100:.1f}%")
print(f"Log loss (по-ниско = по-добра калибровка): {log_loss_sum/total:.3f}")
print()
print("За сравнение: случайно гадаене между 3 изхода би дало ~33%.")
print("Професионални букмейкъри обикновено постигат ~53-55% accuracy на 1X2.")

results_df = pd.DataFrame(results_log)
results_df.to_csv("backtest_results_2024.csv", index=False, encoding="utf-8")
print(f"\nПодробен лог по мач: backtest_results_2024.csv")
print("\nПримерни прогнози:")
print(results_df.head(10).to_string(index=False))
