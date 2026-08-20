import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

XI = 0.0018

LEAGUE_XI = {
    "bulgaria": 0.0005,
    "england": 0.0005,
    "germany": 0.008,
    "spain": 0.0005,
    "france": 0.0005,
}

# --- Фаза K.1 (20.08.2026): Dixon-Coles ниска-резултатна корекция -------
# Независимият Poisson модел системно подценява 0-0/1-1 и надценява
# 1-0/0-1 (Dixon & Coles, 1997) - rho се фитва заедно с attack/defence/
# home_adv във fit_goals_model() (use_dc=True), не е фиксирана константа.


def dc_tau(hg, ag, lam, mu, rho):
    """Dixon-Coles τ(x,y). hg/ag/lam/mu - numpy масиви (или скалари) с
    еднаква форма. НЕ е гарантирано > 0 за произволно rho - викащият
    трябва да clip-не преди log() при MLE (виж fit_goals_model)."""
    hg = np.asarray(hg)
    ag = np.asarray(ag)
    lam = np.asarray(lam)
    mu = np.asarray(mu)
    tau = np.ones(np.broadcast(hg, ag, lam, mu).shape, dtype=float)
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)
    tau = np.where(m00, 1 - lam * mu * rho, tau)
    tau = np.where(m01, 1 + lam * rho, tau)
    tau = np.where(m10, 1 + mu * rho, tau)
    tau = np.where(m11, 1 - rho, tau)
    return tau


def dc_adjust_matrix(pm, lam, mu, rho):
    """pm: independent-Poisson съвместна матрица (outer product), вече
    построена от викащия. Прилага DC корекция върху 4-те ниско-резултатни
    клетки и renormalize-ва (DC не гарантира сума точно 1, отклонението е
    малко, но renormalize е евтин и премахва риска изцяло)."""
    pm = pm.copy()
    pm[0, 0] *= max(1 - lam * mu * rho, 0.0)
    if pm.shape[1] > 1:
        pm[0, 1] *= max(1 + lam * rho, 0.0)
    if pm.shape[0] > 1:
        pm[1, 0] *= max(1 + mu * rho, 0.0)
    if pm.shape[0] > 1 and pm.shape[1] > 1:
        pm[1, 1] *= max(1 - rho, 0.0)
    total = pm.sum()
    if total > 0:
        pm /= total
    return pm


def load_league_data(country_name):
    df = pd.read_csv(f"{country_name.lower()}_merged_full.csv")
    df["date"] = pd.to_datetime(df["date"].astype(str).str[:10])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def get_team_index(df):
    teams = sorted(set(df.home_team) | set(df.away_team))
    return teams, len(teams), {t: i for i, t in enumerate(teams)}


def team_rating(history_df, ref_date, team, home_col, away_col, xi=None):
    xi_val = xi if xi is not None else XI
    home_m = history_df[history_df.home_team == team].dropna(subset=[home_col])
    away_m = history_df[history_df.away_team == team].dropna(subset=[away_col])
    if home_m.empty and away_m.empty:
        return None
    values = list(home_m[home_col]) + list(away_m[away_col])
    dates = list(home_m["date"]) + list(away_m["date"])
    days_ago = [(ref_date - d).days for d in dates]
    weights = [np.exp(-xi_val * max(d, 0)) for d in days_ago]
    return np.average(values, weights=weights)


def fit_goals_model(history_df, ref_date, team_idx, n, cov_home_col=None, cov_away_col=None, xi=None,
                     reg_strength=3.0, use_dc=True, low_data_extra_reg=15.0, reg_floor=1.0):
    """Фаза K.1 (20.08.2026), две промени спрямо оригинала - и двете
    валидирани с walk-forward backtest на 17-те лиги (виж
    CLAUDE_HANDOFF.md K.1) преди деплой, use_dc=False+low_data_extra_reg=0.0
    възпроизвежда СТАРОТО поведение точно (проверено - разлика < 1e-5 в
    lambda/mu):

    1. use_dc=True (по подразбиране): фитва допълнителен rho (Dixon-Coles)
       параметър - вижда се в model["rho"]. Прилага се при показване чрез
       dc_adjust_matrix()/dc_tau() - НЕ променя lambda/mu сами по себе си,
       само съвместното разпределение на резултата.

    2. Регуляризация зависима от обема данни на отбор (N.2 диагнозата):
       всеки отбор получава effective reg = reg_strength +
       low_data_extra_reg / (team_weight + reg_floor), team_weight = сума
       от time-decay теглата на мачовете му. Отбор с малко "пресни"
       наблюдения (напр. ЦСКА 1948 в евротурнир) се дърпа силно към
       "среден отбор" (потвърдено: до ~44% свиване на attack+defence за
       weight~3 срещу <5% за weight>40), вместо да дава екстремна lambda.
       low_data_extra_reg=0.0 връща старата еднаква регуляризация точно."""
    xi_val = xi if xi is not None else XI
    valid = history_df.dropna(subset=["home_goals", "away_goals"])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hg = valid["home_goals"].to_numpy()
    ag = valid["away_goals"].to_numpy()
    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-xi_val * np.clip(days_ago, 0, None))

    team_weight = np.zeros(n)
    np.add.at(team_weight, h_idx, weights)
    np.add.at(team_weight, a_idx, weights)
    reg_vec = reg_strength + low_data_extra_reg / (team_weight + reg_floor)

    use_covariate = cov_home_col is not None
    if use_covariate:
        teams = list(team_idx.keys())
        ratings = {t: team_rating(history_df, ref_date, t, cov_home_col, cov_away_col, xi_val) for t in teams}
        valid_ratings = [v for v in ratings.values() if v is not None]
        league_avg = np.mean(valid_ratings) if valid_ratings else 0
        ratings = {t: (v if v is not None else league_avg) for t, v in ratings.items()}
        scale = max(abs(league_avg), 1)
        home_diff = valid["home_team"].map(ratings).to_numpy() - league_avg
        away_diff = valid["away_team"].map(ratings).to_numpy() - league_avg
    else:
        ratings, league_avg, scale = None, None, None
        home_diff = away_diff = None

    def nll(params):
        attack = params[:n]
        defence = params[n:2 * n]
        if use_covariate:
            home_adv = params[-3] if use_dc else params[-2]
            beta = params[-2] if use_dc else params[-1]
            rho = params[-1] if use_dc else 0.0
            lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv + beta * home_diff / scale)
            mu = np.exp(attack[a_idx] - defence[h_idx] + beta * away_diff / scale)
        else:
            home_adv = params[-2] if use_dc else params[-1]
            rho = params[-1] if use_dc else 0.0
            lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv)
            mu = np.exp(attack[a_idx] - defence[h_idx])
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        if use_dc:
            tau = dc_tau(hg, ag, lam, mu, rho)
            ll = ll + np.log(np.clip(tau, 1e-10, None))
        reg = np.sum(reg_vec * (attack ** 2 + defence ** 2))
        return -np.sum(ll * weights) + reg

    if use_covariate:
        n_params = 2 * n + 3 if use_dc else 2 * n + 2
    else:
        n_params = 2 * n + 2 if use_dc else 2 * n + 1
    x0 = np.zeros(n_params)
    bounds = None
    if use_dc:
        bounds = [(None, None)] * (n_params - 1) + [(-0.9, 0.9)]
    result = minimize(nll, x0, method="L-BFGS-B", bounds=bounds)

    if use_covariate:
        home_adv_i, beta_i = (-3, -2) if use_dc else (-2, -1)
    else:
        home_adv_i, beta_i = ((-2, None) if use_dc else (-1, None))
    rho_val = float(result.x[-1]) if use_dc else 0.0

    return {
        "attack": result.x[:n],
        "defence": result.x[n:2 * n],
        "home_adv": result.x[home_adv_i],
        "beta": result.x[beta_i] if (use_covariate and beta_i is not None) else 0.0,
        "ratings": ratings,
        "league_avg": league_avg,
        "scale": scale,
        "use_covariate": use_covariate,
        "rho": rho_val,
        "team_weight": team_weight,
    }


def get_lambdas(model, team_idx, home, away):
    if home not in team_idx or away not in team_idx:
        return None, None
    hi, ai = team_idx[home], team_idx[away]
    attack, defence, home_adv = model["attack"], model["defence"], model["home_adv"]

    if model["use_covariate"]:
        hd = model["ratings"].get(home, model["league_avg"]) - model["league_avg"]
        ad = model["ratings"].get(away, model["league_avg"]) - model["league_avg"]
        beta, scale = model["beta"], model["scale"]
        lam = np.exp(attack[hi] - defence[ai] + home_adv + beta * hd / scale)
        mu = np.exp(attack[ai] - defence[hi] + beta * ad / scale)
    else:
        lam = np.exp(attack[hi] - defence[ai] + home_adv)
        mu = np.exp(attack[ai] - defence[hi])
    return lam, mu


def btts_ou_probs(lam, mu, max_g=10, rho=0.0):
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    if rho:
        pm = dc_adjust_matrix(pm, lam, mu, rho)
    btts_yes = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x >= 1 and y >= 1)
    over25 = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x + y > 2.5)
    return btts_yes, over25


def backtest_covariate(df, team_idx, n, cov_home_col, cov_away_col, retrain_every=15):
    test_season = df["season"].max()
    test_df = df[df["season"] == test_season].reset_index(drop=True)

    btts_actual_all = (test_df["home_goals"] >= 1) & (test_df["away_goals"] >= 1)
    btts_baseline = max(btts_actual_all.mean(), 1 - btts_actual_all.mean()) * 100
    ou_actual_all = (test_df["home_goals"] + test_df["away_goals"]) > 2.5
    ou_baseline = max(ou_actual_all.mean(), 1 - ou_actual_all.mean()) * 100

    model = None
    correct_btts = correct_ou = total = 0

    for i, row in test_df.iterrows():
        if i % retrain_every == 0:
            history = df[df["date"] < row["date"]]
            model = fit_goals_model(history, row["date"], team_idx, n, cov_home_col, cov_away_col)

        lam, mu = get_lambdas(model, team_idx, row.home_team, row.away_team)
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

    return {
        "test_season": test_season,
        "n": total,
        "btts_baseline": btts_baseline,
        "ou_baseline": ou_baseline,
        "btts_acc": correct_btts / total * 100,
        "ou_acc": correct_ou / total * 100,
    }


def extra_markets_probs(lam, mu, max_g=10, rho=0.0):
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    if rho:
        pm = dc_adjust_matrix(pm, lam, mu, rho)

    home_clean_sheet = sum(pm[x, 0] for x in range(max_g))
    away_clean_sheet = sum(pm[0, y] for y in range(max_g))

    home_win_to_nil = sum(pm[x, 0] for x in range(1, max_g))
    away_win_to_nil = sum(pm[0, y] for y in range(1, max_g))

    home_minus1 = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x - y >= 2)
    away_minus1 = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if y - x >= 2)

    home_over15 = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if x > 1.5)
    away_over15 = sum(pm[x, y] for x in range(max_g) for y in range(max_g) if y > 1.5)

    return {
        "home_clean_sheet": home_clean_sheet,
        "away_clean_sheet": away_clean_sheet,
        "home_win_to_nil": home_win_to_nil,
        "away_win_to_nil": away_win_to_nil,
        "home_handicap_minus1": home_minus1,
        "away_handicap_minus1": away_minus1,
        "home_over15": home_over15,
        "away_over15": away_over15,
    }


def backtest_extra_markets(df, team_idx, n, retrain_every=15):
    test_season = df["season"].max()
    test_df = df[df["season"] == test_season].reset_index(drop=True)

    markets = ["home_clean_sheet", "away_clean_sheet", "home_win_to_nil", "away_win_to_nil",
               "home_handicap_minus1", "away_handicap_minus1", "home_over15", "away_over15"]

    actuals = {
        "home_clean_sheet": test_df["away_goals"] == 0,
        "away_clean_sheet": test_df["home_goals"] == 0,
        "home_win_to_nil": (test_df["home_goals"] > test_df["away_goals"]) & (test_df["away_goals"] == 0),
        "away_win_to_nil": (test_df["away_goals"] > test_df["home_goals"]) & (test_df["home_goals"] == 0),
        "home_handicap_minus1": (test_df["home_goals"] - test_df["away_goals"]) >= 2,
        "away_handicap_minus1": (test_df["away_goals"] - test_df["home_goals"]) >= 2,
        "home_over15": test_df["home_goals"] > 1.5,
        "away_over15": test_df["away_goals"] > 1.5,
    }

    baselines = {m: max(actuals[m].mean(), 1 - actuals[m].mean()) * 100 for m in markets}

    model = None
    correct = {m: 0 for m in markets}
    total = 0

    for i, row in test_df.iterrows():
        if i % retrain_every == 0:
            history = df[df["date"] < row["date"]]
            model = fit_goals_model(history, row["date"], team_idx, n)

        lam, mu = get_lambdas(model, team_idx, row.home_team, row.away_team)
        if lam is None:
            continue

        probs = extra_markets_probs(lam, mu)
        total += 1

        for m in markets:
            pred = probs[m] > 0.5
            actual = bool(actuals[m].loc[row.name])
            correct[m] += (pred == actual)

    results = {}
    for m in markets:
        results[m] = {"acc": correct[m] / total * 100, "baseline": baselines[m]}
    return results, total


def select_best_pick(lam, mu, ht_ft_probs=None, rho=0.0):
    max_g = 10
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    if rho:
        pm = dc_adjust_matrix(pm, lam, mu, rho)
    home_win = np.sum(np.tril(pm, -1))
    draw = np.sum(np.diag(pm))
    away_win = np.sum(np.triu(pm, 1))

    btts_p, ou_p = btts_ou_probs(lam, mu, rho=rho)
    extra = extra_markets_probs(lam, mu, rho=rho)

    candidates = {
        "Домакинът печели": home_win,
        "Равен": draw,
        "Гостът печели": away_win,
        "Двоен шанс 1X (дом. или равен)": home_win + draw,
        "Двоен шанс X2 (равен или гост)": draw + away_win,
        "Двоен шанс 12 (без равен)": home_win + away_win,
        "Над 2.5 гола": ou_p,
        "Под 2.5 гола": 1 - ou_p,
        "Домакинът над 1.5 гола": extra["home_over15"],
        "Домакинът под 1.5 гола": 1 - extra["home_over15"],
    }

    if ht_ft_probs:
        best_htft = max(ht_ft_probs.items(), key=lambda x: x[1])
        candidates[f"HT/FT {best_htft[0]}"] = best_htft[1]

    best_label, best_pct = max(candidates.items(), key=lambda x: x[1])
    return best_label, best_pct * 100


def fit_total_model(df, ref_date, team_idx, n, home_col, away_col, xi=None, reg_strength=3.0):
    xi_val = xi if xi is not None else XI
    valid = df.dropna(subset=[home_col, away_col])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hv = valid[home_col].to_numpy()
    av = valid[away_col].to_numpy()
    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-xi_val * np.clip(days_ago, 0, None))
    def nll(params):
        attack = params[:n]
        defence = params[n:2*n]
        home_adv = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv)
        mu = np.exp(attack[a_idx] - defence[h_idx])
        ll = poisson.logpmf(hv, lam) + poisson.logpmf(av, mu)
        reg = reg_strength * (np.sum(attack ** 2) + np.sum(defence ** 2))
        return -np.sum(ll * weights) + reg
    x0 = np.zeros(2 * n + 1)
    result = minimize(nll, x0, method="L-BFGS-B")
    return {
        "attack": result.x[:n], "defence": result.x[n:2*n],
        "home_adv": result.x[-1], "beta": 0.0, "use_covariate": False,
    }


def total_ou_prob(lam, mu, threshold, max_val=25):
    dist_h = poisson.pmf(range(max_val), lam)
    dist_a = poisson.pmf(range(max_val), mu)
    total_dist = np.convolve(dist_h, dist_a)[:max_val]
    total_dist /= total_dist.sum()
    over = sum(total_dist[i] for i in range(max_val) if i > threshold)
    return over


def fit_goals_direct_covariate(history_df, ref_date, team_idx, n, home_cov_col, away_cov_col, xi=None, reg_strength=3.0):
    xi_val = xi if xi is not None else XI
    valid = history_df.dropna(subset=["home_goals", "away_goals", home_cov_col, away_cov_col])
    h_idx = valid["home_team"].map(team_idx).to_numpy()
    a_idx = valid["away_team"].map(team_idx).to_numpy()
    hg = valid["home_goals"].to_numpy()
    ag = valid["away_goals"].to_numpy()
    h_cov = valid[home_cov_col].to_numpy()
    a_cov = valid[away_cov_col].to_numpy()
    days_ago = (ref_date - valid["date"]).dt.days.to_numpy()
    weights = np.exp(-xi_val * np.clip(days_ago, 0, None))
    def nll(params):
        attack = params[:n]; defence = params[n:2 * n]
        home_adv = params[-2]; beta = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv + beta * h_cov)
        mu = np.exp(attack[a_idx] - defence[h_idx] + beta * a_cov)
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        reg = reg_strength * (np.sum(attack ** 2) + np.sum(defence ** 2))
        return -np.sum(ll * weights) + reg
    x0 = np.zeros(2 * n + 2)
    result = minimize(nll, x0, method="L-BFGS-B")
    return {"attack": result.x[:n], "defence": result.x[n:2 * n],
            "home_adv": result.x[-2], "beta_direct": result.x[-1],
            "direct_covariate": True}
    return {"attack": result.x[:n], "defence": result.x[n:2 * n],
            "home_adv": result.x[-2], "beta_direct": result.x[-1],
            "direct_covariate": True}


def get_lambdas_direct(model, team_idx, home, away, h_cov, a_cov):
    if home not in team_idx or away not in team_idx:
        return None, None
    hi, ai = team_idx[home], team_idx[away]
    attack, defence, home_adv, beta = model["attack"], model["defence"], model["home_adv"], model["beta_direct"]
    lam = np.exp(attack[hi] - defence[ai] + home_adv + beta * h_cov)
    mu = np.exp(attack[ai] - defence[hi] + beta * a_cov)
    return lam, mu


def live_match_probs(lam_full, mu_full, minutes_elapsed, current_hg, current_ag, max_extra=10):
    remaining_minutes = max(90 - minutes_elapsed, 0)
    fraction = remaining_minutes / 90

    remaining_lam = lam_full * fraction
    remaining_mu = mu_full * fraction

    dist_h = poisson.pmf(range(max_extra), remaining_lam)
    dist_a = poisson.pmf(range(max_extra), remaining_mu)

    home_win = draw = away_win = 0.0
    total_probs = {}

    for extra_h in range(max_extra):
        for extra_a in range(max_extra):
            p = dist_h[extra_h] * dist_a[extra_a]
            final_h = current_hg + extra_h
            final_a = current_ag + extra_a

            if final_h > final_a:
                home_win += p
            elif final_h == final_a:
                draw += p
            else:
                away_win += p

            total = final_h + final_a
            total_probs[total] = total_probs.get(total, 0) + p

    over25 = sum(p for total, p in total_probs.items() if total > 2.5)

    return {
        "home_win": home_win, "draw": draw, "away_win": away_win,
        "over25": over25, "under25": 1 - over25,
        "remaining_lam": remaining_lam, "remaining_mu": remaining_mu,
        "remaining_minutes": remaining_minutes,
    }


def live_match_probs_v2(lam_ht, mu_ht, lam_2h, mu_2h, minutes_elapsed, current_hg, current_ag, max_extra=10):
    if minutes_elapsed < 45:
        remaining_1h_fraction = (45 - minutes_elapsed) / 45
        remaining_lam = lam_ht * remaining_1h_fraction + lam_2h
        remaining_mu = mu_ht * remaining_1h_fraction + mu_2h
        remaining_minutes = (45 - minutes_elapsed) + 45
    else:
        remaining_2h_fraction = max(90 - minutes_elapsed, 0) / 45
        remaining_lam = lam_2h * remaining_2h_fraction
        remaining_mu = mu_2h * remaining_2h_fraction
        remaining_minutes = max(90 - minutes_elapsed, 0)

    dist_h = poisson.pmf(range(max_extra), remaining_lam)
    dist_a = poisson.pmf(range(max_extra), remaining_mu)

    home_win = draw = away_win = 0.0
    total_probs = {}

    for extra_h in range(max_extra):
        for extra_a in range(max_extra):
            p = dist_h[extra_h] * dist_a[extra_a]
            final_h = current_hg + extra_h
            final_a = current_ag + extra_a

            if final_h > final_a:
                home_win += p
            elif final_h == final_a:
                draw += p
            else:
                away_win += p

            total = final_h + final_a
            total_probs[total] = total_probs.get(total, 0) + p

    over25 = sum(p for total, p in total_probs.items() if total > 2.5)

    return {
        "home_win": home_win, "draw": draw, "away_win": away_win,
        "over25": over25, "under25": 1 - over25,
        "remaining_lam": remaining_lam, "remaining_mu": remaining_mu,
        "remaining_minutes": remaining_minutes,
    }
