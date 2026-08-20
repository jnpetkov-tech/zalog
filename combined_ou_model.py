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


def fit_combined(history_df, ref_date):
    valid = history_df.dropna(subset=["home_goals", "away_goals"])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hg = valid["home_goals"].to_numpy()
    ag = valid["away_goals"].to_numpy()
    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    shots_ratings = {t: team_rating(history_df, ref_date, t, "home_shots_on_goal", "away_shots_on_goal") for t in all_teams}
    off_ratings = {t: team_rating(history_df, ref_date, t, "home_offsides", "away_offsides") for t in all_teams}

    shots_avg = np.mean([v for v in shots_ratings.values() if v is not None])
    off_avg = np.mean([v for v in off_ratings.values() if v is not None])
    shots_ratings = {t: (v if v is not None else shots_avg) for t, v in shots_ratings.items()}
    off_ratings = {t: (v if v is not None else off_avg) for t, v in off_ratings.items()}

    home_shots_diff = (valid["home_team"].map(shots_ratings).to_numpy() - shots_avg) / max(shots_avg, 1)
    away_shots_diff = (valid["away_team"].map(shots_ratings).to_numpy() - shots_avg) / max(shots_avg, 1)
    home_off_diff = (valid["home_team"].map(off_ratings).to_numpy() - off_avg) / max(off_avg, 1)
    away_off_diff = (valid["away_team"].map(off_ratings).to_numpy() - off_avg) / max(off_avg, 1)

    def nll(params):
        attack = params[:n]; defence = params[n:2*n]
        home_adv = params[-3]; beta_shots = params[-2]; beta_off = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv
                      + beta_shots * home_shots_diff + beta_off * home_off_diff)
        mu = np.exp(attack[a_idx] - defence[h_idx]
                     + beta_shots * away_shots_diff + beta_off * away_off_diff)
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 3)
    r = minimize(nll, x0, method="L-BFGS-B")
    return (r.x[:n], r.x[n:2*n], r.x[-3], r.x[-2], r.x[-1],
            shots_ratings, shots_avg, off_ratings, off_avg)


def get_lambdas(model, home, away):
    attack, defence, home_adv, beta_shots, beta_off, shots_r, shots_avg, off_r, off_avg = model
    if home not in team_idx or away not in team_idx:
        return None, None
    hi, ai = team_idx[home], team_idx[away]
    hsd = (shots_r.get(home, shots_avg) - shots_avg) / max(shots_avg, 1)
    asd = (shots_r.get(away, shots_avg) - shots_avg) / max(shots_avg, 1)
    hod = (off_r.get(home, off_avg) - off_avg) / max(off_avg, 1)
    aod = (off_r.get(away, off_avg) - off_avg) / max(off_avg, 1)
    lam = np.exp(attack[hi] - defence[ai] + home_adv + beta_shots * hsd + beta_off * hod)
    mu = np.exp(attack[ai] - defence[hi] + beta_shots * asd + beta_off * aod)
    return lam, mu


def ou_prob(lam, mu, max_g=10):
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    return sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x + y > 2.5)


test_season = df["season"].max()
test_df = df[df["season"] == test_season].reset_index(drop=True)
ou_actual_all = (test_df["home_goals"] + test_df["away_goals"]) > 2.5
ou_baseline = max(ou_actual_all.mean(), 1 - ou_actual_all.mean()) * 100

print(f"Тестов сезон: {test_season} ({len(test_df)} мача)")
print(f"O/U baseline: {ou_baseline:.1f}%\n")

RETRAIN_EVERY = 15
model = None
correct = 0
total = 0

for i, row in test_df.iterrows():
    if i % RETRAIN_EVERY == 0:
        history = df[df["date"] < row["date"]]
        model = fit_combined(history, row["date"])

    lam, mu = get_lambdas(model, row.home_team, row.away_team)
    if lam is None:
        continue
    p = ou_prob(lam, mu)
    pred = "over" if p > 0.5 else "under"
    actual = "over" if (row.home_goals + row.away_goals) > 2.5 else "under"
    total += 1
    correct += (pred == actual)

print(f"Комбиниран модел (удари + засади): {correct/total*100:.1f}%")
print(f"(за сравнение: baseline {ou_baseline:.1f}%, самостоятелно удари 56.0%, самостоятелно засади 56.0%)")
