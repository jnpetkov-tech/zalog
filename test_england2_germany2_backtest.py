import sys
sys.path.insert(0, '.')
import numpy as np
from scipy.stats import poisson
import football_lib as fl
LEAGUES = ["england2", "germany2"]
RETRAIN_EVERY = 15
def btts_ou_probs(lam, mu, max_g=10):
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    btts_yes = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x >= 1 and y >= 1)
    over25 = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x + y > 2.5)
    return btts_yes, over25
for league in LEAGUES:
    print(f"\n{'='*60}\n{league.upper()}\n{'='*60}")
    df = fl.load_league_data(league)
    teams, n, team_idx = fl.get_team_index(df)
    print(f"Мачове: {len(df)} | Уникални отбори: {n}")
    test_season = df["season"].max()
    test_df = df[df["season"] == test_season].reset_index(drop=True)
    if len(test_df) < 30:
        print(f"Недостатъчно тестови данни ({len(test_df)}), пропускам.")
        continue
    home_win_actual = (test_df["home_goals"] > test_df["away_goals"]).mean()
    draw_actual = (test_df["home_goals"] == test_df["away_goals"]).mean()
    away_win_actual = (test_df["home_goals"] < test_df["away_goals"]).mean()
    x1x2_baseline = max(home_win_actual, draw_actual, away_win_actual) * 100
    ou_actual = (test_df["home_goals"] + test_df["away_goals"]) > 2.5
    ou_baseline = max(ou_actual.mean(), 1 - ou_actual.mean()) * 100
    btts_actual = (test_df["home_goals"] >= 1) & (test_df["away_goals"] >= 1)
    btts_baseline = max(btts_actual.mean(), 1 - btts_actual.mean()) * 100
    model = None
    correct_1x2 = correct_ou = correct_btts = total = 0
    for i, row in test_df.iterrows():
        if i % RETRAIN_EVERY == 0:
            history = df[df["date"] < row["date"]]
            model = fl.fit_goals_model(history, row["date"], team_idx, n)
        lam, mu = fl.get_lambdas(model, team_idx, row.home_team, row.away_team)
        if lam is None:
            continue
        max_g = 10
        pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
        hw = np.sum(np.tril(pm, -1))
        dr = np.sum(np.diag(pm))
        aw = np.sum(np.triu(pm, 1))
        pred_1x2 = max(("home_win", "draw", "away_win"), key=lambda k: {"home_win": hw, "draw": dr, "away_win": aw}[k])
        actual_1x2 = "home_win" if row.home_goals > row.away_goals else ("draw" if row.home_goals == row.away_goals else "away_win")
        btts_p, ou_p = btts_ou_probs(lam, mu)
        pred_ou = "over" if ou_p > 0.5 else "under"
        actual_ou = "over" if (row.home_goals + row.away_goals) > 2.5 else "under"
        pred_btts = "yes" if btts_p > 0.5 else "no"
        actual_btts = "yes" if (row.home_goals >= 1 and row.away_goals >= 1) else "no"
        total += 1
        correct_1x2 += (pred_1x2 == actual_1x2)
        correct_ou += (pred_ou == actual_ou)
        correct_btts += (pred_btts == actual_btts)
    print(f"\n1X2:  {correct_1x2/total*100:.1f}%  (baseline {x1x2_baseline:.1f}%)  {'ДА бие' if correct_1x2/total*100 > x1x2_baseline else 'НЕ бие'}")
    print(f"O/U:  {correct_ou/total*100:.1f}%  (baseline {ou_baseline:.1f}%)  {'ДА бие' if correct_ou/total*100 > ou_baseline else 'НЕ бие'}")
    print(f"BTTS: {correct_btts/total*100:.1f}%  (baseline {btts_baseline:.1f}%)  {'ДА бие' if correct_btts/total*100 > btts_baseline else 'НЕ бие'}")
    print(f"(n={total})")
