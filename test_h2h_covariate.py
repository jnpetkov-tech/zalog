import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

XI = 0.0018


def compute_h2h_column(df):
    df = df.sort_values("date").reset_index(drop=True)
    df["pair_key"] = df.apply(lambda r: tuple(sorted([r["home_team"], r["away_team"]])), axis=1)

    h2h_values = [None] * len(df)

    for pair, group in df.groupby("pair_key"):
        idxs = group.index.tolist()
        dates = group["date"].tolist()
        totals = (group["home_goals"] + group["away_goals"]).tolist()

        for pos, idx in enumerate(idxs):
            if pos < 2:
                continue
            past_dates = dates[:pos]
            past_totals = totals[:pos]
            cur_date = dates[pos]
            days_ago = [(cur_date - d).days for d in past_dates]
            weights = np.exp(-XI * np.clip(days_ago, 0, None))
            h2h_values[idx] = np.average(past_totals, weights=weights)

    df["h2h_avg_goals"] = h2h_values
    return df


def fit_with_h2h(history_df, ref_date, team_idx, n):
    valid = history_df.dropna(subset=["home_goals", "away_goals", "h2h_avg_goals"])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hg = valid["home_goals"].to_numpy()
    ag = valid["away_goals"].to_numpy()
    h2h = valid["h2h_avg_goals"].to_numpy()
    league_avg_h2h = h2h.mean()
    h2h_diff = h2h - league_avg_h2h

    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-XI * np.clip(days_ago, 0, None))

    def nll(params):
        attack = params[:n]; defence = params[n:2*n]
        home_adv = params[-2]; beta = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv + beta * h2h_diff)
        mu = np.exp(attack[a_idx] - defence[h_idx] + beta * h2h_diff)
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 2)
    r = minimize(nll, x0, method="L-BFGS-B")
    return r.x[:n], r.x[n:2*n], r.x[-2], r.x[-1], league_avg_h2h


def get_lambdas_h2h(model, team_idx, home, away, h2h_val, league_avg):
    attack, defence, home_adv, beta, _ = model
    if home not in team_idx or away not in team_idx:
        return None, None
    hi, ai = team_idx[home], team_idx[away]
    diff = (h2h_val - league_avg) if h2h_val is not None else 0
    lam = np.exp(attack[hi] - defence[ai] + home_adv + beta * diff)
    mu = np.exp(attack[ai] - defence[hi] + beta * diff)
    return lam, mu


def btts_ou_probs(lam, mu, max_g=10):
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    btts_yes = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x >= 1 and y >= 1)
    over25 = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x + y > 2.5)
    return btts_yes, over25


LEAGUES = ["bulgaria", "england", "germany", "spain", "france"]

for league in LEAGUES:
    print(f"\n{'='*55}\n{league.upper()}\n{'='*55}")
    df = pd.read_csv(f"{league}_merged_full.csv")
    df["date"] = pd.to_datetime(df["date"])
    df = compute_h2h_column(df)

    teams = sorted(set(df.home_team) | set(df.away_team))
    n = len(teams)
    team_idx = {t: i for i, t in enumerate(teams)}

    test_season = df["season"].max()
    test_df = df[(df["season"] == test_season) & df["h2h_avg_goals"].notna()].reset_index(drop=True)

    if len(test_df) < 20:
        print(f"Недостатъчно мачове с H2H история ({len(test_df)}), пропускам.")
        continue

    ou_actual = (test_df["home_goals"] + test_df["away_goals"]) > 2.5
    ou_baseline = max(ou_actual.mean(), 1 - ou_actual.mean()) * 100
    btts_actual = (test_df["home_goals"] >= 1) & (test_df["away_goals"] >= 1)
    btts_baseline = max(btts_actual.mean(), 1 - btts_actual.mean()) * 100

    RETRAIN_EVERY = 15
    model = None
    correct_ou = correct_btts = total = 0
    beta_values = []

    for i, row in test_df.iterrows():
        if i % RETRAIN_EVERY == 0:
            history = df[df["date"] < row["date"]]
            model = fit_with_h2h(history, row["date"], team_idx, n)
            beta_values.append(model[3])

        lam, mu = get_lambdas_h2h(model, team_idx, row.home_team, row.away_team, row.h2h_avg_goals, model[4])
        if lam is None:
            continue

        btts_p, ou_p = btts_ou_probs(lam, mu)
        pred_ou = "over" if ou_p > 0.5 else "under"
        actual_ou = "over" if (row.home_goals + row.away_goals) > 2.5 else "under"
        pred_btts = "yes" if btts_p > 0.5 else "no"
        actual_btts = "yes" if (row.home_goals >= 1 and row.away_goals >= 1) else "no"

        total += 1
        correct_ou += (pred_ou == actual_ou)
        correct_btts += (pred_btts == actual_btts)

    print(f"Мачове с достатъчна H2H история: {total}")
    print(f"Среден beta (H2H): {np.mean(beta_values):.4f}")
    print(f"O/U 2.5:  {correct_ou/total*100:.1f}%  (baseline {ou_baseline:.1f}%)  {'ДА бие' if correct_ou/total*100 > ou_baseline else 'НЕ бие'}")
    print(f"BTTS:     {correct_btts/total*100:.1f}%  (baseline {btts_baseline:.1f}%)  {'ДА бие' if correct_btts/total*100 > btts_baseline else 'НЕ бие'}")
