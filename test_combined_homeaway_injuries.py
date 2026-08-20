import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

XI = 0.0018


def fit_combined(history_df, ref_date, team_idx, n):
    valid = history_df.dropna(subset=["home_goals", "away_goals", "home_injuries", "away_injuries"])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hg = valid["home_goals"].to_numpy()
    ag = valid["away_goals"].to_numpy()
    h_inj = valid["home_injuries"].to_numpy()
    a_inj = valid["away_injuries"].to_numpy()

    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    def nll(params):
        ah = params[0*n:1*n]; dh = params[1*n:2*n]
        aa = params[2*n:3*n]; da = params[3*n:4*n]
        beta = params[-1]
        lam = np.exp(ah[h_idx] - da[a_idx] + beta * h_inj)
        mu = np.exp(aa[a_idx] - dh[h_idx] + beta * a_inj)
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(4 * n + 1)
    r = minimize(nll, x0, method="L-BFGS-B")
    return r.x[0*n:1*n], r.x[1*n:2*n], r.x[2*n:3*n], r.x[3*n:4*n], r.x[-1]


def get_lambdas_combined(model, team_idx, home, away, h_inj, a_inj):
    ah, dh, aa, da, beta = model
    if home not in team_idx or away not in team_idx:
        return None, None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(ah[hi] - da[ai] + beta * h_inj)
    mu = np.exp(aa[ai] - dh[hi] + beta * a_inj)
    return lam, mu


LEAGUES = ["england", "germany", "spain", "france"]

for league in LEAGUES:
    print(f"\n{'='*55}\n{league.upper()}\n{'='*55}")
    df = pd.read_csv(f"{league}_merged_full.csv")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    teams = sorted(set(df.home_team) | set(df.away_team))
    n = len(teams)
    team_idx = {t: i for i, t in enumerate(teams)}

    test_season = df["season"].max()
    test_df = df[df["season"] == test_season].dropna(subset=["home_injuries", "away_injuries"]).reset_index(drop=True)

    if len(test_df) < 30:
        print("Недостатъчно данни, пропускам.")
        continue

    home_win_actual = (test_df["home_goals"] > test_df["away_goals"]).mean()
    draw_actual = (test_df["home_goals"] == test_df["away_goals"]).mean()
    away_win_actual = (test_df["home_goals"] < test_df["away_goals"]).mean()
    baseline = max(home_win_actual, draw_actual, away_win_actual) * 100

    RETRAIN_EVERY = 15
    model = None
    correct = total = 0
    beta_values = []

    for i, row in test_df.iterrows():
        if i % RETRAIN_EVERY == 0:
            history = df[df["date"] < row["date"]]
            model = fit_combined(history, row["date"], team_idx, n)
            beta_values.append(model[4])

        lam, mu = get_lambdas_combined(model, team_idx, row.home_team, row.away_team,
                                         row.home_injuries, row.away_injuries)
        if lam is None:
            continue

        max_g = 10
        pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
        hw = np.sum(np.tril(pm, -1))
        dr = np.sum(np.diag(pm))
        aw = np.sum(np.triu(pm, 1))

        pred = max(("home_win", "draw", "away_win"), key=lambda k: {"home_win": hw, "draw": dr, "away_win": aw}[k])
        actual = "home_win" if row.home_goals > row.away_goals else ("draw" if row.home_goals == row.away_goals else "away_win")

        total += 1
        correct += (pred == actual)

    print(f"Комбиниран модел (home/away + контузии): {correct/total*100:.1f}%  (baseline {baseline:.1f}%)")
    print(f"Среден beta (контузии): {np.mean(beta_values):.4f}")
    print(f"(n={total})")
