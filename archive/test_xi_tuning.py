import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

CANDIDATE_XI = [0.0005, 0.001, 0.0018, 0.003, 0.005, 0.008]


def fit_goals_model_xi(history_df, ref_date, team_idx, n, xi_value):
    valid = history_df.dropna(subset=["home_goals", "away_goals"])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hg = valid["home_goals"].to_numpy()
    ag = valid["away_goals"].to_numpy()

    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-xi_value * np.clip(days_ago, 0, None))

    def nll(params):
        attack = params[:n]; defence = params[n:2*n]
        home_adv = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv)
        mu = np.exp(attack[a_idx] - defence[h_idx])
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)

    x0 = np.zeros(2 * n + 1)
    r = minimize(nll, x0, method="L-BFGS-B")
    return r.x[:n], r.x[n:2*n], r.x[-1]


def get_lambdas(model, team_idx, home, away):
    attack, defence, home_adv = model
    if home not in team_idx or away not in team_idx:
        return None, None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv)
    mu = np.exp(attack[ai] - defence[hi])
    return lam, mu


def evaluate_1x2(model, team_idx, test_df):
    correct = 0
    log_loss_sum = 0
    total = 0
    max_g = 10

    for _, row in test_df.iterrows():
        lam, mu = get_lambdas(model, team_idx, row.home_team, row.away_team)
        if lam is None:
            continue
        pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
        hw = np.sum(np.tril(pm, -1))
        dr = np.sum(np.diag(pm))
        aw = np.sum(np.triu(pm, 1))

        actual = "home_win" if row.home_goals > row.away_goals else ("draw" if row.home_goals == row.away_goals else "away_win")
        probs = {"home_win": hw, "draw": dr, "away_win": aw}
        pred = max(probs, key=probs.get)

        total += 1
        correct += (pred == actual)
        log_loss_sum += -np.log(max(probs[actual], 1e-10))

    return correct / total * 100, log_loss_sum / total, total


LEAGUES = ["bulgaria", "england", "germany", "spain", "france"]

for league in LEAGUES:
    print(f"\n{'='*60}\n{league.upper()}\n{'='*60}")
    df = pd.read_csv(f"{league}_merged_full.csv")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    teams = sorted(set(df.home_team) | set(df.away_team))
    n = len(teams)
    team_idx = {t: i for i, t in enumerate(teams)}

    train_2022 = df[df["season"] == 2022].reset_index(drop=True)
    val_2023 = df[df["season"] == 2023].reset_index(drop=True)

    if len(train_2022) < 30 or len(val_2023) < 30:
        print("Недостатъчно данни за 2022/2023, пропускам.")
        continue

    ref_date = train_2022["date"].max()
    print(f"{'XI':<10} {'Accuracy':<12} {'Log loss':<10}")

    best_xi = None
    best_log_loss = float("inf")

    for xi in CANDIDATE_XI:
        model = fit_goals_model_xi(train_2022, ref_date, team_idx, n, xi)
        acc, ll, cnt = evaluate_1x2(model, team_idx, val_2023)
        marker = ""
        if ll < best_log_loss:
            best_log_loss = ll
            best_xi = xi
            marker = " <- засега най-добра"
        print(f"{xi:<10} {acc:<12.1f} {ll:<10.3f}{marker}")

    print(f"\nИзбрана XI = {best_xi} (по log loss на валидацията)")

    test_season = df["season"].max()
    test_df = df[df["season"] == test_season].reset_index(drop=True)
    if len(test_df) < 20:
        continue

    RETRAIN_EVERY = 15
    model = None
    correct = total = 0
    log_loss_sum = 0

    for i, row in test_df.iterrows():
        if i % RETRAIN_EVERY == 0:
            history = df[df["date"] < row["date"]]
            model = fit_goals_model_xi(history, row["date"], team_idx, n, best_xi)

        lam, mu = get_lambdas(model, team_idx, row.home_team, row.away_team)
        if lam is None:
            continue
        max_g = 10
        pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
        hw = np.sum(np.tril(pm, -1))
        dr = np.sum(np.diag(pm))
        aw = np.sum(np.triu(pm, 1))
        actual = "home_win" if row.home_goals > row.away_goals else ("draw" if row.home_goals == row.away_goals else "away_win")
        probs = {"home_win": hw, "draw": dr, "away_win": aw}
        pred = max(probs, key=probs.get)
        total += 1
        correct += (pred == actual)
        log_loss_sum += -np.log(max(probs[actual], 1e-10))

    home_win_actual = (test_df["home_goals"] > test_df["away_goals"]).mean()
    draw_actual = (test_df["home_goals"] == test_df["away_goals"]).mean()
    away_win_actual = (test_df["home_goals"] < test_df["away_goals"]).mean()
    baseline = max(home_win_actual, draw_actual, away_win_actual) * 100

    print(f"\nФинален тест на сезон {test_season} с XI={best_xi}:")
    print(f"  Accuracy: {correct/total*100:.1f}%  (baseline {baseline:.1f}%)")
    print(f"  Log loss: {log_loss_sum/total:.3f}")
