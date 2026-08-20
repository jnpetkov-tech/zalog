import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

df = pd.read_csv("bulgaria_merged_full.csv")
df["date"] = pd.to_datetime(df["date"])
df["home_cards"] = df["home_yellow"].fillna(0) + df["home_red"].fillna(0)
df["away_cards"] = df["away_yellow"].fillna(0) + df["away_red"].fillna(0)
df = df.sort_values("date").reset_index(drop=True)

all_teams = sorted(set(df.home_team) | set(df.away_team))
n = len(all_teams)
team_idx = {t: i for i, t in enumerate(all_teams)}

XI = 0.0018


def team_fouls_rating(history_df, ref_date, team):
    home_m = history_df[history_df.home_team == team].dropna(subset=["home_fouls"])
    away_m = history_df[history_df.away_team == team].dropna(subset=["away_fouls"])
    if home_m.empty and away_m.empty:
        return 12.0

    values = list(home_m["home_fouls"]) + list(away_m["away_fouls"])
    dates = list(home_m["date"]) + list(away_m["date"])
    days_ago = [(ref_date - d).days for d in dates]
    weights = [np.exp(-XI * max(d, 0)) for d in days_ago]

    return np.average(values, weights=weights)


def fit_cards_with_fouls(history_df, ref_date):
    valid = history_df.dropna(subset=["home_cards", "away_cards"])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hv = valid["home_cards"].to_numpy()
    av = valid["away_cards"].to_numpy()
    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    fouls_ratings = {t: team_fouls_rating(history_df, ref_date, t) for t in all_teams}
    league_avg = np.mean(list(fouls_ratings.values()))

    home_diff = valid["home_team"].map(fouls_ratings).to_numpy() - league_avg
    away_diff = valid["away_team"].map(fouls_ratings).to_numpy() - league_avg

    def nll(params):
        attack = params[:n]
        defence = params[n:2*n]
        home_adv = params[-2]
        beta_fouls = params[-1]

        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv + beta_fouls * home_diff / 10)
        mu = np.exp(attack[a_idx] - defence[h_idx] + beta_fouls * away_diff / 10)
        ll = poisson.logpmf(hv, lam) + poisson.logpmf(av, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 2)
    result = minimize(nll, x0, method="L-BFGS-B")
    return result.x[:n], result.x[n:2*n], result.x[-2], result.x[-1], fouls_ratings, league_avg


def predict_total(attack, defence, home_adv, beta, ratings, league_avg, home, away, max_val=15):
    if home not in team_idx or away not in team_idx:
        return None
    hi, ai = team_idx[home], team_idx[away]
    home_diff = ratings.get(home, league_avg) - league_avg
    away_diff = ratings.get(away, league_avg) - league_avg
    lam = np.exp(attack[hi] - defence[ai] + home_adv + beta * home_diff / 10)
    mu = np.exp(attack[ai] - defence[hi] + beta * away_diff / 10)
    dist_h = poisson.pmf(range(max_val), lam)
    dist_a = poisson.pmf(range(max_val), mu)
    total_dist = np.convolve(dist_h, dist_a)[:max_val]
    total_dist /= total_dist.sum()
    return total_dist


test_season = df["season"].max()
test_df = df.dropna(subset=["home_cards", "away_cards"])
test_df = test_df[test_df["season"] == test_season].reset_index(drop=True)
print(f"Тестов сезон: {test_season} ({len(test_df)} мача)\n")

total_cards_all = test_df["home_cards"] + test_df["away_cards"]
THRESHOLD = 3.5
naive_baseline = max((total_cards_all > THRESHOLD).mean(), (total_cards_all <= THRESHOLD).mean()) * 100
print(f"Naive baseline (мнозинство клас): {naive_baseline:.1f}%\n")

RETRAIN_EVERY = 15
model = None
correct = 0
total = 0
beta_values = []

for i, row in test_df.iterrows():
    if i % RETRAIN_EVERY == 0:
        history = df[df["date"] < row["date"]]
        model = fit_cards_with_fouls(history, row["date"])
        beta_values.append(model[3])

    attack, defence, home_adv, beta, ratings, league_avg = model
    dist = predict_total(attack, defence, home_adv, beta, ratings, league_avg,
                          row.home_team, row.away_team)
    if dist is None:
        continue

    over_prob = sum(dist[k] for k in range(len(dist)) if k > THRESHOLD)
    pred = "over" if over_prob > 0.5 else "under"
    actual_total = row["home_cards"] + row["away_cards"]
    actual = "over" if actual_total > THRESHOLD else "under"

    total += 1
    correct += (pred == actual)

print(f"Среден fitted beta_fouls коефициент: {np.mean(beta_values):.4f}")
print(f"Cards O/U {THRESHOLD} С fouls rating: {correct/total*100:.1f}%")
print(f"(n={total}, срещу naive baseline {naive_baseline:.1f}% и предишен резултат без covariate 63.7%)")
