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

CANDIDATES = [
    ("home_fouls", "away_fouls", "Фаулове"),
    ("home_possession", "away_possession", "Притежание"),
    ("home_shots", "away_shots", "Общо удари"),
    ("home_shots_insidebox", "away_shots_insidebox", "Удари в кутията"),
]


def team_rating(history_df, ref_date, team, home_col, away_col):
    home_m = history_df[history_df.home_team == team].dropna(subset=[home_col])
    away_m = history_df[history_df.away_team == team].dropna(subset=[away_col])
    if home_m.empty and away_m.empty:
        return None
    values = list(home_m[home_col]) + list(away_m[away_col])
    dates = list(home_m["date"]) + list(away_m["date"])
    days_ago = [(ref_date - d).days for d in dates]
    weights = [np.exp(-XI * max(d, 0)) for d in days_ago]
    return np.average(values, weights=weights)


def fit_goals_with_covariate(history_df, ref_date, cov_home_col, cov_away_col):
    valid = history_df.dropna(subset=["home_goals", "away_goals"])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hg = valid["home_goals"].to_numpy()
    ag = valid["away_goals"].to_numpy()
    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    ratings = {t: team_rating(history_df, ref_date, t, cov_home_col, cov_away_col) for t in all_teams}
    valid_ratings = [v for v in ratings.values() if v is not None]
    league_avg = np.mean(valid_ratings) if valid_ratings else 0
    ratings = {t: (v if v is not None else league_avg) for t, v in ratings.items()}

    home_diff = valid["home_team"].map(ratings).to_numpy() - league_avg
    away_diff = valid["away_team"].map(ratings).to_numpy() - league_avg
    scale = max(abs(league_avg), 1)

    def nll(params):
        attack = params[:n]; defence = params[n:2*n]
        home_adv = params[-2]; beta = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv + beta * home_diff / scale)
        mu = np.exp(attack[a_idx] - defence[h_idx] + beta * away_diff / scale)
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 2)
    r = minimize(nll, x0, method="L-BFGS-B")
    return r.x[:n], r.x[n:2*n], r.x[-2], r.x[-1], ratings, league_avg, scale


def get_lambdas(model, home, away):
    attack, defence, home_adv, beta, ratings, league_avg, scale = model
    if home not in team_idx or away not in team_idx:
        return None, None
    hi, ai = team_idx[home], team_idx[away]
    hd = ratings.get(home, league_avg) - league_avg
    ad = ratings.get(away, league_avg) - league_avg
    lam = np.exp(attack[hi] - defence[ai] + home_adv + beta * hd / scale)
    mu = np.exp(attack[ai] - defence[hi] + beta * ad / scale)
    return lam, mu


def btts_ou_probs(lam, mu, max_g=10):
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    btts_yes = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x >= 1 and y >= 1)
    over25 = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x + y > 2.5)
    return btts_yes, over25


test_season = df["season"].max()
test_df = df[df["season"] == test_season].reset_index(drop=True)

btts_actual_all = (test_df["home_goals"] >= 1) & (test_df["away_goals"] >= 1)
btts_baseline = max(btts_actual_all.mean(), 1 - btts_actual_all.mean()) * 100
ou_actual_all = (test_df["home_goals"] + test_df["away_goals"]) > 2.5
ou_baseline = max(ou_actual_all.mean(), 1 - ou_actual_all.mean()) * 100

print(f"Тестов сезон: {test_season} ({len(test_df)} мача)")
print(f"BTTS baseline: {btts_baseline:.1f}%  |  O/U baseline: {ou_baseline:.1f}%\n")
print(f"{'Feature':<25} {'BTTS':>10} {'BTTS>base?':>12} {'O/U':>10} {'O/U>base?':>12}")
print("=" * 72)

RETRAIN_EVERY = 15

for cov_home, cov_away, label in CANDIDATES:
    if cov_home not in df.columns:
        print(f"{label:<25} - колона липсва -")
        continue

    model = None
    correct_btts = correct_ou = total = 0

    for i, row in test_df.iterrows():
        if i % RETRAIN_EVERY == 0:
            history = df[df["date"] < row["date"]]
            model = fit_goals_with_covariate(history, row["date"], cov_home, cov_away)

        lam, mu = get_lambdas(model, row.home_team, row.away_team)
        if lam is None:
            continue
        btts_p, ou_p = btts_ou_probs(lam, mu)
        pred_btts = "yes" if btts_p > 0.5 else "no"
        pred_ou = "over" if ou_p > 0.5 else "under"

        actual_btts = "yes" if (row.home_goals >= 1 and row.away_goals >= 1) else "no"
        actual_ou = "over" if (row.home_goals + row.away_goals) > 2.5 else "under"

        total += 1
        correct_btts += (pred_btts == actual_btts)
        correct_ou += (pred_ou == actual_ou)

    btts_acc = correct_btts / total * 100
    ou_acc = correct_ou / total * 100
    btts_beats = "ДА" if btts_acc > btts_baseline else "не"
    ou_beats = "ДА" if ou_acc > ou_baseline else "не"

    print(f"{label:<25} {btts_acc:>9.1f}% {btts_beats:>12} {ou_acc:>9.1f}% {ou_beats:>12}")

print(f"\n(n={total} мача на всеки ред)")
