import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
import time

df = pd.read_csv("bulgaria_merged_full.csv")
df["date"] = pd.to_datetime(df["date"])
df = df.dropna(subset=["home_xg", "away_xg", "home_goals", "away_goals"])
df = df.sort_values("date").reset_index(drop=True)

print(f"Общо мачове с валидни xG данни: {len(df)}")
print(f"По сезони:\n{df['season'].value_counts().sort_index()}\n")

all_teams = sorted(set(df.home_team) | set(df.away_team))
n = len(all_teams)
team_idx = {t: i for i, t in enumerate(all_teams)}

XI = 0.0018


def fit_xg_model(history_df, ref_date):
    h_idx = history_df["home_team"].map(team_idx).to_numpy()
    a_idx = history_df["away_team"].map(team_idx).to_numpy()
    home_xg = np.clip(history_df["home_xg"].to_numpy(), 0.05, None)
    away_xg = np.clip(history_df["away_xg"].to_numpy(), 0.05, None)

    days_ago = (ref_date - history_df["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    def nll(params):
        attack = params[:n]
        defence = params[n:2*n]
        home_adv = params[-1]

        log_lam = attack[h_idx] - defence[a_idx] + home_adv
        log_mu = attack[a_idx] - defence[h_idx]

        err = (np.log(home_xg) - log_lam) ** 2 + (np.log(away_xg) - log_mu) ** 2
        return np.sum(err * weights)

    x0 = np.zeros(2 * n + 1)
    result = minimize(nll, x0, method="L-BFGS-B")
    return result.x[:n], result.x[n:2*n], result.x[-1]


def fit_goals_model(history_df, ref_date):
    h_idx = history_df["home_team"].map(team_idx).to_numpy()
    a_idx = history_df["away_team"].map(team_idx).to_numpy()
    hg = history_df["home_goals"].to_numpy()
    ag = history_df["away_goals"].to_numpy()

    days_ago = (ref_date - history_df["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    def nll(params):
        attack = params[:n]
        defence = params[n:2*n]
        home_adv = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv)
        mu = np.exp(attack[a_idx] - defence[h_idx])
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 1)
    result = minimize(nll, x0, method="L-BFGS-B")
    return result.x[:n], result.x[n:2*n], result.x[-1]


def get_prob_matrix(attack, defence, home_adv, home, away, max_goals=8):
    if home not in team_idx or away not in team_idx:
        return None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv)
    mu = np.exp(attack[ai] - defence[hi])
    pm = np.outer(poisson.pmf(range(max_goals), lam), poisson.pmf(range(max_goals), mu))
    return pm / pm.sum()


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


def evaluate_model(fit_func, test_df, full_df):
    RETRAIN_EVERY = 15
    attack = defence = home_adv = None
    correct_1x2 = correct_btts = correct_ou = 0
    log_loss_sum = 0
    total = 0

    for i, row in test_df.iterrows():
        if i % RETRAIN_EVERY == 0:
            history = full_df[full_df["date"] < row["date"]]
            attack, defence, home_adv = fit_func(history, row["date"])

        pm = get_prob_matrix(attack, defence, home_adv, row.home_team, row.away_team)
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

    return {"1x2": correct_1x2/total*100, "btts": correct_btts/total*100,
            "ou": correct_ou/total*100, "log_loss": log_loss_sum/total, "n": total}


test_season = df["season"].max()
test_df = df[df["season"] == test_season].reset_index(drop=True)
print(f"Тестов сезон: {test_season} ({len(test_df)} мача)\n")

print("Трениране и тест на GOALS модела (базов, за сравнение)...")
t0 = time.time()
result_goals = evaluate_model(fit_goals_model, test_df, df)
print(f"  Отне {time.time()-t0:.1f}s")

print("\nТрениране и тест на xG модела...")
t0 = time.time()
result_xg = evaluate_model(fit_xg_model, test_df, df)
print(f"  Отне {time.time()-t0:.1f}s")

print("\n" + "=" * 60)
print("СРАВНЕНИЕ: GOALS модел vs xG модел")
print("=" * 60)
print(f"{'Метрика':<12} {'Goals модел':>14} {'xG модел':>14}")
print(f"{'1X2':<12} {result_goals['1x2']:>13.1f}% {result_xg['1x2']:>13.1f}%")
print(f"{'BTTS':<12} {result_goals['btts']:>13.1f}% {result_xg['btts']:>13.1f}%")
print(f"{'O/U 2.5':<12} {result_goals['ou']:>13.1f}% {result_xg['ou']:>13.1f}%")
print(f"{'Log loss':<12} {result_goals['log_loss']:>13.3f} {result_xg['log_loss']:>13.3f}")
print(f"\n(n={result_goals['n']} тествани мача)")
