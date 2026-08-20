import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

XI = 0.0018


def fit_with_injury_covariate(history_df, ref_date, team_idx, n):
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
        attack = params[:n]; defence = params[n:2*n]
        home_adv = params[-2]; beta = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv + beta * h_inj)
        mu = np.exp(attack[a_idx] - defence[h_idx] + beta * a_inj)
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 2)
    r = minimize(nll, x0, method="L-BFGS-B")
    return r.x[:n], r.x[n:2*n], r.x[-2], r.x[-1]


def get_lambdas_inj(model, team_idx, home, away, h_inj, a_inj):
    attack, defence, home_adv, beta = model
    if home not in team_idx or away not in team_idx:
        return None, None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv + beta * h_inj)
    mu = np.exp(attack[ai] - defence[hi] + beta * a_inj)
    return lam, mu


def btts_ou_probs(lam, mu, max_g=10):
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    btts_yes = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x >= 1 and y >= 1)
    over25 = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x + y > 2.5)
    home_win = np.sum(np.tril(pm, -1))
    draw = np.sum(np.diag(pm))
    away_win = np.sum(np.triu(pm, 1))
    return home_win, draw, away_win, btts_yes, over25


LEAGUES = ["england", "germany", "spain", "france"]

for league in LEAGUES:
    print(f"\n{'='*60}\n{league.upper()}\n{'='*60}")
    df = pd.read_csv(f"{league}_merged_full.csv")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    teams = sorted(set(df.home_team) | set(df.away_team))
    n = len(teams)
    team_idx = {t: i for i, t in enumerate(teams)}

    test_season = df["season"].max()
    test_df = df[df["season"] == test_season].dropna(subset=["home_injuries", "away_injuries"]).reset_index(drop=True)

    if len(test_df) < 30:
        print("Недостатъчно тестови данни, пропускам.")
        continue

    btts_actual = (test_df["home_goals"] >= 1) & (test_df["away_goals"] >= 1)
    btts_baseline = max(btts_actual.mean(), 1 - btts_actual.mean()) * 100
    ou_actual = (test_df["home_goals"] + test_df["away_goals"]) > 2.5
    ou_baseline = max(ou_actual.mean(), 1 - ou_actual.mean()) * 100
    home_win_actual = (test_df["home_goals"] > test_df["away_goals"]).mean()
    draw_actual = (test_df["home_goals"] == test_df["away_goals"]).mean()
    away_win_actual = (test_df["home_goals"] < test_df["away_goals"]).mean()
    x1x2_baseline = max(home_win_actual, draw_actual, away_win_actual) * 100

    RETRAIN_EVERY = 15
    model = None
    correct_1x2 = correct_btts = correct_ou = total = 0
    beta_values = []

    for i, row in test_df.iterrows():
        if i % RETRAIN_EVERY == 0:
            history = df[df["date"] < row["date"]]
            model = fit_with_injury_covariate(history, row["date"], team_idx, n)
            beta_values.append(model[3])

        lam, mu = get_lambdas_inj(model, team_idx, row.home_team, row.away_team,
                                    row.home_injuries, row.away_injuries)
        if lam is None:
            continue

        hw, dr, aw, btts_p, ou_p = btts_ou_probs(lam, mu)
        pred_1x2 = max(("home_win", "draw", "away_win"), key=lambda k: {"home_win": hw, "draw": dr, "away_win": aw}[k])
        actual_1x2 = "home_win" if row.home_goals > row.away_goals else ("draw" if row.home_goals == row.away_goals else "away_win")
        pred_btts = "yes" if btts_p > 0.5 else "no"
        actual_btts = "yes" if (row.home_goals >= 1 and row.away_goals >= 1) else "no"
        pred_ou = "over" if ou_p > 0.5 else "under"
        actual_ou = "over" if (row.home_goals + row.away_goals) > 2.5 else "under"

        total += 1
        correct_1x2 += (pred_1x2 == actual_1x2)
        correct_btts += (pred_btts == actual_btts)
        correct_ou += (pred_ou == actual_ou)

    print(f"Среден beta (контузии): {np.mean(beta_values):.4f} (отрицателна = логично)")
    print(f"1X2:  {correct_1x2/total*100:.1f}%  (baseline {x1x2_baseline:.1f}%)  {'ДА бие' if correct_1x2/total*100 > x1x2_baseline else 'НЕ бие'}")
    print(f"BTTS: {correct_btts/total*100:.1f}%  (baseline {btts_baseline:.1f}%)  {'ДА бие' if correct_btts/total*100 > btts_baseline else 'НЕ бие'}")
    print(f"O/U:  {correct_ou/total*100:.1f}%  (baseline {ou_baseline:.1f}%)  {'ДА бие' if correct_ou/total*100 > ou_baseline else 'НЕ бие'}")
    print(f"(n={total})")
