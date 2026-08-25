"""
validation/team_goals_dispersion.py - 25.08.2026, разговор с Дака:

Хипотеза: "под 1.5 гола" излиза системно завишено, защото независимият
Poisson модел подценява опашката (реалният брой мачове с 3+/4+ гола на
отбор е по-висок от предсказаното) - т.е. проблемът не е грешен BLEND_WEIGHT
или грешен devig, а самата форма на разпределението.

Метод: walk-forward backtest, същата инфраструктура като validation/runner.py
(модел преизчислен само от историята ПРЕДИ теста, никога от бъдещи данни).
За всеки тестван мач - маргиналното разпределение на голове на всеки отбор
(домакин И гост, извадени от СЪЩАТА pm матрица, която production код ползва
за home_over15/away_over15 - football_lib.extra_markets_probs()/
_raw_candidates() в match_predictor_app.py, вкл. Dixon-Coles корекция при
use_dc=True) се бъкетира в {0, 1, 2, 3, "4+"} и се сумира като ОЧАКВАН брой
(сума на вероятностите), срещу РЕАЛНИЯ брой пъти отборът реално е вкарал
точно толкова гола. Ако Poisson подценява опашката: наблюдаваният дял в
бъкет "4+" (и "3") ще е трайно над очаквания, а "0"/"1" - под очаквания.

Ограничение (същото като runner.py): само 13-те лиги, минаващи през
fit_goals_model() (has_injuries=False) - england/germany/spain/france минават
през fit_goals_direct_covariate(), която изисква реални контузийни данни за
всеки тестван мач и няма walk-forward еквивалент тук.

Употреба: python3 validation/team_goals_dispersion.py
Пише: validation/team_goals_dispersion_20260825.csv
  (ред на (лига, бъкет) + обобщени "(всички лиги)" редове, гранулярни 0-4+
  И агрегирани under1.5/over1.5 - двете гледни точки в един файл)
"""
import os
import sys
import time
from datetime import date

import numpy as np
from scipy.stats import poisson, chisquare

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import football_lib as fl  # noqa: E402

LEAGUES = [
    "bulgaria", "bulgaria2", "conference_league", "champions_league",
    "europa_league", "england2", "france2", "germany2", "italy", "italy2",
    "portugal", "portugal2", "spain2",
]

RETRAIN_EVERY = 20
MAX_TEST = 200
MIN_TEST = 60
MAX_G = 10
BUCKETS = ["0", "1", "2", "3", "4+"]


def marginal_dist(lam, mu, rho):
    """Връща (home_marginal[0..MAX_G-1], away_marginal[0..MAX_G-1]) -
    точно същата pm матрица (с DC корекция) като production
    football_lib.extra_markets_probs()/match_predictor_app._raw_candidates(),
    само маргинализирана по двете оси вместо само над/под 1.5 прага."""
    pm = np.outer(poisson.pmf(range(MAX_G), lam), poisson.pmf(range(MAX_G), mu))
    if rho:
        pm = fl.dc_adjust_matrix(pm, lam, mu, rho)
    home_marg = pm.sum(axis=1)
    away_marg = pm.sum(axis=0)
    return home_marg, away_marg


def bucket_probs(marg):
    """[P(0), P(1), P(2), P(3), P(4+)] от маргиналния вектор с дължина MAX_G."""
    return [marg[0], marg[1], marg[2], marg[3], marg[4:].sum()]


def bucket_actual(goals):
    return min(int(goals), 4)


def run_league(league):
    df = fl.load_league_data(league)
    df = df.dropna(subset=["home_goals", "away_goals"]).reset_index(drop=True)
    teams, n, team_idx = fl.get_team_index(df)
    xi = fl.LEAGUE_XI.get(league, fl.XI)

    test_size = int(min(MAX_TEST, max(MIN_TEST, len(df) * 0.10)))
    test_df = df.iloc[-test_size:].reset_index(drop=True)

    model = None
    expected = np.zeros(5)
    observed = np.zeros(5, dtype=int)
    n_obs = 0

    for i, row in enumerate(test_df.itertuples()):
        if i % RETRAIN_EVERY == 0:
            history = df[df["date"] < row.date]
            model = fl.fit_goals_model(history, row.date, team_idx, n, xi=xi)
        lam, mu = fl.get_lambdas(model, team_idx, row.home_team, row.away_team)
        if lam is None:
            continue
        rho = model["rho"]
        home_marg, away_marg = marginal_dist(lam, mu, rho)

        for marg, actual_goals in ((home_marg, row.home_goals), (away_marg, row.away_goals)):
            probs = bucket_probs(marg)
            expected += probs
            observed[bucket_actual(actual_goals)] += 1
            n_obs += 1

    return n_obs, expected, observed


def summarize(n_obs, expected, observed):
    exp_pct = expected / n_obs * 100
    obs_pct = observed / n_obs * 100
    # хи-квадрат тест на годност: наблюдавани СРЕЩУ очаквани бройки от модела
    # (не срещу равномерно/друго - самият модел е нулевата хипотеза тук)
    chi2, pval = chisquare(observed, f_exp=expected * (observed.sum() / expected.sum()))
    return exp_pct, obs_pct, chi2, pval


def agg_under_over(expected, observed):
    """0+1 = 'под 1.5', 2+3+4+ = 'над 1.5' - директно съпоставимо с
    home_over15/home_under15 пазара."""
    exp_under, exp_over = expected[0] + expected[1], expected[2:].sum()
    obs_under, obs_over = observed[0] + observed[1], observed[2:].sum()
    return exp_under, exp_over, obs_under, obs_over


def main():
    rows = []
    total_expected = np.zeros(5)
    total_observed = np.zeros(5, dtype=int)
    t_start = time.time()

    print(f"{'Лига':<20} {'n(отбор-мач)':>12} {'хи2':>8} {'p-стойност':>11}")
    print("-" * 55)

    for league in LEAGUES:
        t0 = time.time()
        n_obs, expected, observed = run_league(league)
        total_expected += expected
        total_observed += observed
        exp_pct, obs_pct, chi2, pval = summarize(n_obs, expected, observed)
        elapsed = time.time() - t0
        print(f"{league:<20} {n_obs:>12} {chi2:>8.2f} {pval:>11.4f}  ({elapsed:.1f}s)")

        for b_i, b in enumerate(BUCKETS):
            rows.append({
                "league": league, "row_type": "granular", "bucket": b,
                "n_obs": n_obs, "expected_n": round(expected[b_i], 2),
                "expected_pct": round(exp_pct[b_i], 2),
                "observed_n": int(observed[b_i]), "observed_pct": round(obs_pct[b_i], 2),
                "diff_pct": round(obs_pct[b_i] - exp_pct[b_i], 2),
                "chi2": None, "pval": None,
            })

        exp_u, exp_o, obs_u, obs_o = agg_under_over(expected, observed)
        for label, exp_v, obs_v in (("под1.5", exp_u, obs_u), ("над1.5", exp_o, obs_o)):
            rows.append({
                "league": league, "row_type": "agg_15", "bucket": label,
                "n_obs": n_obs, "expected_n": round(exp_v, 2),
                "expected_pct": round(exp_v / n_obs * 100, 2),
                "observed_n": int(obs_v), "observed_pct": round(obs_v / n_obs * 100, 2),
                "diff_pct": round(obs_v / n_obs * 100 - exp_v / n_obs * 100, 2),
                "chi2": None, "pval": None,
            })

    # обобщение по всички 13 лиги накуп
    total_n = int(total_observed.sum())
    exp_pct, obs_pct, chi2, pval = summarize(total_n, total_expected, total_observed)
    print("-" * 55)
    print(f"{'(всички лиги)':<20} {total_n:>12} {chi2:>8.2f} {pval:>11.4f}")
    print(f"\nОбщо време: {time.time()-t_start:.1f}s")

    for b_i, b in enumerate(BUCKETS):
        rows.append({
            "league": "(всички лиги)", "row_type": "granular", "bucket": b,
            "n_obs": total_n, "expected_n": round(total_expected[b_i], 2),
            "expected_pct": round(exp_pct[b_i], 2),
            "observed_n": int(total_observed[b_i]), "observed_pct": round(obs_pct[b_i], 2),
            "diff_pct": round(obs_pct[b_i] - exp_pct[b_i], 2),
            "chi2": round(chi2, 2) if b_i == 0 else None,
            "pval": round(pval, 6) if b_i == 0 else None,
        })
    exp_u, exp_o, obs_u, obs_o = agg_under_over(total_expected, total_observed)
    for label, exp_v, obs_v in (("под1.5", exp_u, obs_u), ("над1.5", exp_o, obs_o)):
        rows.append({
            "league": "(всички лиги)", "row_type": "agg_15", "bucket": label,
            "n_obs": total_n, "expected_n": round(exp_v, 2),
            "expected_pct": round(exp_v / total_n * 100, 2),
            "observed_n": int(obs_v), "observed_pct": round(obs_v / total_n * 100, 2),
            "diff_pct": round(obs_v / total_n * 100 - exp_v / total_n * 100, 2),
            "chi2": None, "pval": None,
        })

    print("\n=== Гранулярно разпределение, обединено по всички лиги ===")
    print(f"{'бъкет':<6} {'очаквано %':>11} {'реално %':>10} {'разлика':>9}")
    for b_i, b in enumerate(BUCKETS):
        print(f"{b:<6} {exp_pct[b_i]:>11.2f} {obs_pct[b_i]:>10.2f} {obs_pct[b_i]-exp_pct[b_i]:>+9.2f}")

    print("\n=== Под/над 1.5, обединено по всички лиги ===")
    print(f"под 1.5: очаквано {exp_u/total_n*100:.2f}% срещу реално {obs_u/total_n*100:.2f}% "
          f"(разлика {obs_u/total_n*100 - exp_u/total_n*100:+.2f})")
    print(f"над 1.5: очаквано {exp_o/total_n*100:.2f}% срещу реално {obs_o/total_n*100:.2f}% "
          f"(разлика {obs_o/total_n*100 - exp_o/total_n*100:+.2f})")

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             f"team_goals_dispersion_{date.today().strftime('%Y%m%d')}.csv")
    import csv
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nЗаписано: {out_path} ({len(rows)} реда)")


if __name__ == "__main__":
    main()
