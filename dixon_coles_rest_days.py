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

last_match_date = {}
home_rest = []
away_rest = []
DEFAULT_REST = 10

for _, row in df.iterrows():
    h, a, d = row["home_team"], row["away_team"], row["date"]
    hr = (d - last_match_date[h]).days if h in last_match_date else DEFAULT_REST
    ar = (d - last_match_date[a]).days if a in last_match_date else DEFAULT_REST
    home_rest.append(min(hr, DEFAULT_REST))
    away_rest.append(min(ar, DEFAULT_REST))
    last_match_date[h] = d
    last_match_date[a] = d

df["home_rest"] = home_rest
df["away_rest"] = away_rest
df["home_short_rest"] = (df["home_rest"] <= 4).astype(int)
df["away_short_rest"] = (df["away_rest"] <= 4).astype(int)

print(f"Мачове с домакин на кратка почивка (<=4 дни): {df['home_short_rest'].sum()} от {len(df)}")
print(f"Мачове с гост на кратка почивка (<=4 дни): {df['away_short_rest'].sum()} от {len(df)}\n")

XI = 0.0018


def fit_model(history_df, ref_date):
    h_idx = history_df["home_team"].map(team_idx).to_numpy()
    a_idx = history_df["away_team"].map(team_idx).to_numpy()
    hg = history_df["home_goals"].to_numpy()
    ag = history_df["away_goals"].to_numpy()
    h_short = history_df["home_short_rest"].to_numpy()
    a_short = history_df["away_short_rest"].to_numpy()

    days_ago = (ref_date - history_df["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    mask00 = (hg == 0) & (ag == 0)
    mask01 = (hg == 0) & (ag == 1)
    mask10 = (hg == 1) & (ag == 0)
    mask11 = (hg == 1) & (ag == 1)

    def neg_log_likelihood(params):
        attack = params[:n]
        defence = params[n:2*n]
        home_adv = params[-3]
        rho = params[-2]
        beta_fatigue = params[-1]

        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv + beta_fatigue * h_short)
        mu = np.exp(attack[a_idx] - defence[h_idx] + beta_fatigue * a_short)

        tau = np.ones(len(hg))
        tau[mask00] = 1 - lam[mask00] * mu[mask00] * rho
        tau[mask01] = 1 + lam[mask01] * rho
        tau[mask10] = 1 + mu[mask10] * rho
        tau[mask11] = 1 - rho
        tau = np.clip(tau, 1e-10, None)

        ll = np.log(tau) + poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 3)
    bounds = [(None, None)] * (2 * n + 2) + [(-1, 1)]
    result = minimize(neg_log_likelihood, x0, method="L-BFGS-B", bounds=bounds)
    attack = result.x[:n]
    defence = result.x[n:2*n]
    home_adv = result.x[-3]
    rho = result.x[-2]
    beta_fatigue = result.x[-1]
    return attack, defence, home_adv, rho, beta_fatigue


def get_prob_matrix(attack, defence, home_adv, rho, beta_fatigue, home, away, h_short, a_short, max_goals=8):
    if home not in team_idx or away not in team_idx:
        return None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv + beta_fatigue * h_short)
    mu = np.exp(attack[ai] - defence[hi] + beta_fatigue * a_short)

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
    return {
        "home_win": np.sum(np.tril(pm, -1)), "draw": np.sum(np.diag(pm)),
        "away_win": np.sum(np.triu(pm, 1)),
        "btts_yes": btts_yes, "btts_no": 1 - btts_yes,
        "over25": over25, "under25": 1 - over25,
    }


test_df = df[df["season"] == 2024].reset_index(drop=True)
print(f"Тестови мачове: {len(test_df)}\n")

t0 = time.time()
RETRAIN_EVERY = 10
attack = defence = home_adv = rho = beta_fatigue = None
correct_1x2 = correct_btts = correct_ou = 0
log_loss_sum = 0
total = 0
fatigue_betas = []

for i, row in test_df.iterrows():
    if i % RETRAIN_EVERY == 0:
        history = df[df["date"] < row["date"]]
        attack, defence, home_adv, rho, beta_fatigue = fit_model(history, row["date"])
        fatigue_betas.append(beta_fatigue)

    pm = get_prob_matrix(attack, defence, home_adv, rho, beta_fatigue,
                          row.home_team, row.away_team,
                          row.home_short_rest, row.away_short_rest)
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
    log_loss_sum += -np.log(max(m[actual_1x2], 1e-10))

print(f"Общо време: {time.time()-t0:.1f}s")
print(f"Среден fitted beta_fatigue (отрицателно = потвърждава умора): {np.mean(fatigue_betas):.4f}\n")
print("=" * 60)
print("РЕЗУЛТАТИ — МОДЕЛ С ДНИ ПОЧИВКА (сезон 2024)")
print("=" * 60)
print(f"1X2 accuracy: {correct_1x2/total*100:.1f}% | log loss: {log_loss_sum/total:.3f}")
print(f"BTTS accuracy: {correct_btts/total*100:.1f}%")
print(f"Over/Under 2.5 accuracy: {correct_ou/total*100:.1f}%")
print()
print("За сравнение (walk-forward, без фактор умора):")
print("  1X2: 50.0% (log loss 0.992) | BTTS: 56.1% | O/U 53.1%")
