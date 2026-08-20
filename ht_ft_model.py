import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

df = pd.read_csv("bulgaria_merged_full.csv")
df["date"] = pd.to_datetime(df["date"])
df = df.dropna(subset=["home_ht_goals", "away_ht_goals", "home_goals", "away_goals"])
df = df.sort_values("date").reset_index(drop=True)

print(f"Мачове с валидни HT данни: {len(df)}")

all_teams = sorted(set(df.home_team) | set(df.away_team))
n = len(all_teams)
team_idx = {t: i for i, t in enumerate(all_teams)}

XI = 0.0018


def fit_poisson_model(history_df, ref_date, home_col, away_col):
    valid = history_df.dropna(subset=[home_col, away_col])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hv = valid[home_col].to_numpy()
    av = valid[away_col].to_numpy()
    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    def nll(params):
        attack = params[:n]
        defence = params[n:2*n]
        home_adv = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv)
        mu = np.exp(attack[a_idx] - defence[h_idx])
        ll = poisson.logpmf(hv, lam) + poisson.logpmf(av, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 1)
    result = minimize(nll, x0, method="L-BFGS-B")
    return result.x[:n], result.x[n:2*n], result.x[-1]


def get_lambdas(attack, defence, home_adv, home, away):
    if home not in team_idx or away not in team_idx:
        return None, None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv)
    mu = np.exp(attack[ai] - defence[hi])
    return lam, mu


def ht_ft_outcome(ht_h, ht_a, ft_h, ft_a):
    def result(h, a):
        if h > a:
            return "1"
        elif h == a:
            return "X"
        else:
            return "2"
    return f"{result(ht_h, ht_a)}/{result(ft_h, ft_a)}"


def predict_ht_ft(lam_ht_h, lam_ht_a, lam_2h_h, lam_2h_a, max_goals=6):
    outcomes = {}
    for hh in range(max_goals):
        for ha in range(max_goals):
            p_ht = poisson.pmf(hh, lam_ht_h) * poisson.pmf(ha, lam_ht_a)
            for h2 in range(max_goals):
                for a2 in range(max_goals):
                    p_2h = poisson.pmf(h2, lam_2h_h) * poisson.pmf(a2, lam_2h_a)
                    ft_h, ft_a = hh + h2, ha + a2
                    outcome = ht_ft_outcome(hh, ha, ft_h, ft_a)
                    outcomes[outcome] = outcomes.get(outcome, 0) + p_ht * p_2h
    total = sum(outcomes.values())
    return {k: v / total for k, v in outcomes.items()}


test_season = df["season"].max()
test_df = df[df["season"] == test_season].reset_index(drop=True)
print(f"Тестов сезон: {test_season} ({len(test_df)} мача)\n")

df["home_2h_goals"] = df["home_goals"] - df["home_ht_goals"]
df["away_2h_goals"] = df["away_goals"] - df["away_ht_goals"]

RETRAIN_EVERY = 15
ht_model = None
h2_model = None
correct = 0
total = 0

for i, row in test_df.iterrows():
    if i % RETRAIN_EVERY == 0:
        history = df[df["date"] < row["date"]]
        ht_model = fit_poisson_model(history, row["date"], "home_ht_goals", "away_ht_goals")
        h2_model = fit_poisson_model(history, row["date"], "home_2h_goals", "away_2h_goals")

    lam_ht_h, lam_ht_a = get_lambdas(*ht_model, row.home_team, row.away_team)
    lam_2h_h, lam_2h_a = get_lambdas(*h2_model, row.home_team, row.away_team)
    if lam_ht_h is None:
        continue

    probs = predict_ht_ft(lam_ht_h, lam_ht_a, lam_2h_h, lam_2h_a)
    predicted = max(probs, key=probs.get)

    actual = ht_ft_outcome(row.home_ht_goals, row.away_ht_goals, row.home_goals, row.away_goals)

    total += 1
    correct += (predicted == actual)

print(f"HT/FT accuracy: {correct/total*100:.1f}% (n={total})")
print("(случайно гадаене между 9 комбинации би дало ~11%)")
