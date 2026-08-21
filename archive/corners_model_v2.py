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


def team_shot_rating(history_df, ref_date, team):
    home_m = history_df[history_df.home_team == team].dropna(subset=["home_shots"])
    away_m = history_df[history_df.away_team == team].dropna(subset=["away_shots"])
    if home_m.empty and away_m.empty:
        return 10.0

    values = list(home_m["home_shots"]) + list(away_m["away_shots"])
    dates = list(home_m["date"]) + list(away_m["date"])
    days_ago = [(ref_date - d).days for d in dates]
    weights = [np.exp(-XI * max(d, 0)) for d in days_ago]

    return np.average(values, weights=weights)


def fit_corners_with_covariate(history_df, ref_date):
    valid = history_df.dropna(subset=["home_corners", "away_corners"])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hv = valid["home_corners"].to_numpy()
    av = valid["away_corners"].to_numpy()
    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    shot_ratings = {t: team_shot_rating(history_df, ref_date, t) for t in all_teams}
    league_avg_shots = np.mean(list(shot_ratings.values()))

    home_shot_diff = valid["home_team"].map(shot_ratings).to_numpy() - league_avg_shots
    away_shot_diff = valid["away_team"].map(shot_ratings).to_numpy() - league_avg_shots

    def nll(params):
        attack = params[:n]
        defence = params[n:2*n]
        home_adv = params[-2]
        beta_shots = params[-1]

        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv + beta_shots * home_shot_diff / 10)
        mu = np.exp(attack[a_idx] - defence[h_idx] + beta_shots * away_shot_diff / 10)
        ll = poisson.logpmf(hv, lam) + poisson.logpmf(av, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 2)
    result = minimize(nll, x0, method="L-BFGS-B")
    return result.x[:n], result.x[n:2*n], result.x[-2], result.x[-1], shot_ratings, league_avg_shots


def predict_total(attack, defence, home_adv, beta_shots, shot_ratings, league_avg, home, away, max_val=20):
    if home not in team_idx or away not in team_idx:
        return None
    hi, ai = team_idx[home], team_idx[away]
    home_diff = shot_ratings.get(home, league_avg) - league_avg
    away_diff = shot_ratings.get(away, league_avg) - league_avg
    lam = np.exp(attack[hi] - defence[ai] + home_adv + beta_shots * home_diff / 10)
    mu = np.exp(attack[ai] - defence[hi] + beta_shots * away_diff / 10)
    dist_h = poisson.pmf(range(max_val), lam)
    dist_a = poisson.pmf(range(max_val), mu)
    total_dist = np.convolve(dist_h, dist_a)[:max_val]
    total_dist /= total_dist.sum()
    return total_dist


def fit_plain(history_df, ref_date):
    valid = history_df.dropna(subset=["home_corners", "away_corners"])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hv = valid["home_corners"].to_numpy()
    av = valid["away_corners"].to_numpy()
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


def predict_plain(attack, defence, home_adv, home, away, max_val=20):
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


test_season = df["season"].max()
test_df = df.dropna(subset=["home_corners", "away_corners"])
test_df = test_df[test_df["season"] == test_season].reset_index(drop=True)
print(f"Тестов сезон: {test_season} ({len(test_df)} мача с корнер данни)\n")

THRESHOLD = 9.5
RETRAIN_EVERY = 15
model = None
plain_model = None
correct = 0
correct_no_covariate = 0
total = 0
beta_values = []

for i, row in test_df.iterrows():
    if i % RETRAIN_EVERY == 0:
        history = df[df["date"] < row["date"]]
        model = fit_corners_with_covariate(history, row["date"])
        plain_model = fit_plain(history, row["date"])
        beta_values.append(model[3])

    attack, defence, home_adv, beta_shots, shot_ratings, league_avg = model
    dist = predict_total(attack, defence, home_adv, beta_shots, shot_ratings, league_avg,
                          row.home_team, row.away_team)
    dist_plain = predict_plain(*plain_model, row.home_team, row.away_team)
    if dist is None:
        continue

    over_prob = sum(dist[k] for k in range(len(dist)) if k > THRESHOLD)
    pred = "over" if over_prob > 0.5 else "under"

    over_prob_plain = sum(dist_plain[k] for k in range(len(dist_plain)) if k > THRESHOLD)
    pred_plain = "over" if over_prob_plain > 0.5 else "under"

    actual_total = row["home_corners"] + row["away_corners"]
    actual = "over" if actual_total > THRESHOLD else "under"

    total += 1
    correct += (pred == actual)
    correct_no_covariate += (pred_plain == actual)

print(f"Среден fitted beta_shots коефициент: {np.mean(beta_values):.4f}")
print(f"Corners O/U {THRESHOLD} С shot rating covariate: {correct/total*100:.1f}%")
print(f"Corners O/U {THRESHOLD} БЕЗ covariate (стар модел): {correct_no_covariate/total*100:.1f}%")
print(f"(n={total})")
