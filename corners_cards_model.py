import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
import time

df = pd.read_csv("bulgaria_merged_full.csv")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

df["home_cards"] = df["home_yellow"].fillna(0) + df["home_red"].fillna(0)
df["away_cards"] = df["away_yellow"].fillna(0) + df["away_red"].fillna(0)

all_teams = sorted(set(df.home_team) | set(df.away_team))
n = len(all_teams)
team_idx = {t: i for i, t in enumerate(all_teams)}

XI = 0.0018


def fit_count_model(history_df, ref_date, home_col, away_col):
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


def predict_total(attack, defence, home_adv, home, away, max_val=20):
    if home not in team_idx or away not in team_idx:
        return None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv)
    mu = np.exp(attack[ai] - defence[hi])
    dist_h = poisson.pmf(range(max_val), lam)
    dist_a = poisson.pmf(range(max_val), mu)
    total_dist = np.convolve(dist_h, dist_a)[:max_val]
    total_dist /= total_dist.sum()
    return total_dist


def evaluate_ou_market(target_col_home, target_col_away, threshold, label, valid_df, full_df):
    test_df = valid_df.dropna(subset=[target_col_home, target_col_away]).reset_index(drop=True)
    RETRAIN_EVERY = 15
    attack = defence = home_adv = None
    correct = 0
    total = 0

    for i, row in test_df.iterrows():
        if i % RETRAIN_EVERY == 0:
            history = full_df[full_df["date"] < row["date"]]
            attack, defence, home_adv = fit_count_model(history, row["date"], target_col_home, target_col_away)

        dist = predict_total(attack, defence, home_adv, row.home_team, row.away_team)
        if dist is None:
            continue

        over_prob = sum(dist[i] for i in range(len(dist)) if i > threshold)
        under_prob = 1 - over_prob
        pred = "over" if over_prob > under_prob else "under"

        actual_total = row[target_col_home] + row[target_col_away]
        actual = "over" if actual_total > threshold else "under"

        total += 1
        correct += (pred == actual)

    print(f"{label}: accuracy = {correct/total*100:.1f}% (n={total}, линия={threshold})")
    return correct / total * 100


test_season = df["season"].max()
test_df = df[df["season"] == test_season].reset_index(drop=True)
print(f"Тестов сезон: {test_season}\n")

print("=== Корнери (линия 9.5) ===")
evaluate_ou_market("home_corners", "away_corners", 9.5, "Corners O/U 9.5", test_df, df)

print("\n=== Картони (линия 3.5) ===")
evaluate_ou_market("home_cards", "away_cards", 3.5, "Cards O/U 3.5", test_df, df)

print("\n=== Картони (линия 4.5, алтернативна линия) ===")
evaluate_ou_market("home_cards", "away_cards", 4.5, "Cards O/U 4.5", test_df, df)
