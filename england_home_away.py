import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
import time

df = pd.read_csv("england_premier_league_matches.csv")
df = df.dropna(subset=["home_goals", "away_goals"])
df["home_goals"] = df["home_goals"].astype(int)
df["away_goals"] = df["away_goals"].astype(int)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

all_teams = sorted(set(df.home_team) | set(df.away_team))
n = len(all_teams)
team_idx = {t: i for i, t in enumerate(all_teams)}

XI = 0.0018

def unpack(params):
    attack_home = params[0*n:1*n]
    defence_home = params[1*n:2*n]
    attack_away = params[2*n:3*n]
    defence_away = params[3*n:4*n]
    rho = params[-1]
    return attack_home, defence_home, attack_away, defence_away, rho


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
        attack_home, defence_home, attack_away, defence_away, rho = unpack(params)
        lam = np.exp(attack_home[h_idx] - defence_away[a_idx])
        mu = np.exp(attack_away[a_idx] - defence_home[h_idx])

        tau = np.ones(len(hg))
        tau[mask00] = 1 - lam[mask00] * mu[mask00] * rho
        tau[mask01] = 1 + lam[mask01] * rho
        tau[mask10] = 1 + mu[mask10] * rho
        tau[mask11] = 1 - rho
        tau = np.clip(tau, 1e-10, None)

        ll = (np.log(tau) + poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu))
        return -np.sum(ll * weights)

    x0 = np.zeros(4 * n + 1)
    bounds = [(None, None)] * (4 * n) + [(-1, 1)]
    result = minimize(neg_log_likelihood, x0, method="L-BFGS-B", bounds=bounds)
    return result.x


def get_prob_matrix(params, home, away, max_goals=8):
    if home not in team_idx or away not in team_idx:
        return None
    attack_home, defence_home, attack_away, defence_away, rho = unpack(params)
    hi, ai = team_idx[home], team_idx[away]

    lam = np.exp(attack_home[hi] - defence_away[ai])
    mu = np.exp(attack_away[ai] - defence_home[hi])

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
    home_win = np.sum(np.tril(pm, -1))
    draw = np.sum(np.diag(pm))
    away_win = np.sum(np.triu(pm, 1))
    return {
        "home_win": home_win, "draw": draw, "away_win": away_win,
        "btts_yes": btts_yes, "btts_no": 1 - btts_yes,
        "over25": over25, "under25": 1 - over25,
    }


test_df = df[df["season"] == 2024].reset_index(drop=True)
print(f"Тестови мачове: {len(test_df)}\n")

t0 = time.time()
RETRAIN_EVERY = 10
params = None

correct_1x2 = correct_btts = correct_ou = 0
log_loss_1x2 = 0
total = 0

for i, row in test_df.iterrows():
    if i % RETRAIN_EVERY == 0:
        history = df[df["date"] < row["date"]]
        params = fit_model(history, row["date"])

    pm = get_prob_matrix(params, row.home_team, row.away_team)
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
    if pred_1x2 == actual_1x2:
        correct_1x2 += 1
    if pred_btts == actual_btts:
        correct_btts += 1
    if pred_ou == actual_ou:
        correct_ou += 1
    log_loss_1x2 += -np.log(max(m[actual_1x2], 1e-10))

print(f"Общо време: {time.time()-t0:.1f}s\n")
print("=" * 60)
print("РЕЗУЛТАТИ — HOME/AWAY-СПЕЦИФИЧЕН МОДЕЛ (сезон 2024)")
print("=" * 60)
print(f"Общо тествани мачове: {total}\n")
print(f"1X2 accuracy: {correct_1x2/total*100:.1f}% | log loss: {log_loss_1x2/total:.3f}")
print(f"BTTS accuracy: {correct_btts/total*100:.1f}%")
print(f"Over/Under 2.5 accuracy: {correct_ou/total*100:.1f}%")
print()
print("За сравнение (walk-forward, общ home_adv):")
print("  1X2: 50.0% (log loss 0.992) | BTTS: 56.1% | O/U 2.5: 53.1%")
