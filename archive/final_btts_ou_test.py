import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

df = pd.read_csv("bulgaria_merged_full.csv")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

all_teams = sorted(set(df.home_team) | set(df.away_team))
n = len(all_teams)
team_idx = {t: i for i, t in enumerate(all_teams)}

XI = 0.0018


def fit_goals_model(history_df, ref_date):
    h_idx = history_df["home_team"].map(team_idx).to_numpy()
    a_idx = history_df["away_team"].map(team_idx).to_numpy()
    hg = history_df["home_goals"].to_numpy()
    ag = history_df["away_goals"].to_numpy()
    days_ago = (ref_date - history_df["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    def nll(params):
        attack = params[:n]; defence = params[n:2*n]; home_adv = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv)
        mu = np.exp(attack[a_idx] - defence[h_idx])
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 1)
    r = minimize(nll, x0, method="L-BFGS-B")
    return r.x[:n], r.x[n:2*n], r.x[-1]


def fit_xg_model(history_df, ref_date):
    valid = history_df.dropna(subset=["home_xg", "away_xg"])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    home_xg = np.clip(valid["home_xg"].to_numpy(), 0.05, None)
    away_xg = np.clip(valid["away_xg"].to_numpy(), 0.05, None)
    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    def nll(params):
        attack = params[:n]; defence = params[n:2*n]; home_adv = params[-1]
        log_lam = attack[h_idx] - defence[a_idx] + home_adv
        log_mu = attack[a_idx] - defence[h_idx]
        err = (np.log(home_xg) - log_lam) ** 2 + (np.log(away_xg) - log_mu) ** 2
        return np.sum(err * weights)

    x0 = np.zeros(2 * n + 1)
    r = minimize(nll, x0, method="L-BFGS-B")
    return r.x[:n], r.x[n:2*n], r.x[-1]


def get_lambdas(model, home, away):
    if home not in team_idx or away not in team_idx:
        return None, None
    attack, defence, home_adv = model
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv)
    mu = np.exp(attack[ai] - defence[hi])
    return lam, mu


def btts_ou_probs(lam, mu, max_g=10):
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    btts_yes = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x >= 1 and y >= 1)
    over25 = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x + y > 2.5)
    return btts_yes, over25


test_season = df["season"].max()
test_df = df[df["season"] == test_season].reset_index(drop=True)
print(f"Тестов сезон: {test_season} ({len(test_df)} мача)\n")

btts_actual = (test_df["home_goals"] >= 1) & (test_df["away_goals"] >= 1)
btts_baseline = max(btts_actual.mean(), 1 - btts_actual.mean()) * 100
ou_actual = (test_df["home_goals"] + test_df["away_goals"]) > 2.5
ou_baseline = max(ou_actual.mean(), 1 - ou_actual.mean()) * 100

RETRAIN_EVERY = 15
goals_model = None
xg_model = None
correct_btts_goals = correct_btts_xg = 0
correct_ou_goals = correct_ou_xg = 0
total = 0

for i, row in test_df.iterrows():
    if i % RETRAIN_EVERY == 0:
        history = df[df["date"] < row["date"]]
        goals_model = fit_goals_model(history, row["date"])
        xg_history = history.dropna(subset=["home_xg", "away_xg"])
        if len(xg_history) > 30:
            xg_model = fit_xg_model(history, row["date"])

    lam_g, mu_g = get_lambdas(goals_model, row.home_team, row.away_team)
    if lam_g is None:
        continue
    btts_g, ou_g = btts_ou_probs(lam_g, mu_g)
    pred_btts_g = "yes" if btts_g > 0.5 else "no"
    pred_ou_g = "over" if ou_g > 0.5 else "under"

    if xg_model is not None:
        lam_x, mu_x = get_lambdas(xg_model, row.home_team, row.away_team)
        btts_x, ou_x = btts_ou_probs(lam_x, mu_x)
        pred_btts_x = "yes" if btts_x > 0.5 else "no"
        pred_ou_x = "over" if ou_x > 0.5 else "under"
    else:
        pred_btts_x, pred_ou_x = pred_btts_g, pred_ou_g

    actual_btts = "yes" if (row.home_goals >= 1 and row.away_goals >= 1) else "no"
    actual_ou = "over" if (row.home_goals + row.away_goals) > 2.5 else "under"

    total += 1
    correct_btts_goals += (pred_btts_g == actual_btts)
    correct_btts_xg += (pred_btts_x == actual_btts)
    correct_ou_goals += (pred_ou_g == actual_ou)
    correct_ou_xg += (pred_ou_x == actual_ou)

print("=" * 65)
print(f"{'Пазар':<20} {'Baseline':>10} {'Goals модел':>14} {'xG модел':>12}")
print("=" * 65)
print(f"{'BTTS':<20} {btts_baseline:>9.1f}% {correct_btts_goals/total*100:>13.1f}% {correct_btts_xg/total*100:>11.1f}%")
print(f"{'Over/Under 2.5':<20} {ou_baseline:>9.1f}% {correct_ou_goals/total*100:>13.1f}% {correct_ou_xg/total*100:>11.1f}%")
print(f"\n(n={total} мача)")
