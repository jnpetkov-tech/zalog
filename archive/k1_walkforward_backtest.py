"""
K.1 валидация - реален walk-forward backtest, старо срещу ново.

Причина: старите числа, цитирани в CLAUDE_HANDOFF.md ("bulgaria OU +3pp,
england 1X2 +0.8pp, ...") бяха от терминален изход на предишна сесия,
никъде не бяха запазени във файл или git commit - невъзможно е да се
покажат реалните числа зад тях. Този скрипт пресмята нови, с честна
методология, описана долу, и пази резултата в CSV.

Методология:
- За всяка лига, засегната от K.1 (тези, които минават през
  fit_goals_model(), не fit_goals_direct_covariate()): взимаме последните
  min(200, max(60, 10% от мачовете)) мача с валиден резултат, хронологично,
  като тестов прозорец.
- Walk-forward: моделът се преизчислява на всеки 20 тествани мача (само на
  историята ПРЕДИ съответния мач - без изтичане на бъдещи данни).
- Две конфигурации на fit_goals_model(), сравнени "ябълки с ябълки" на
  ИДЕНТИЧНИТЕ тестови мачове и ИДЕНТИЧНИТЕ re-train точки:
    старо = use_dc=False, low_data_extra_reg=0.0 (доказано <1e-5 разлика
            в lambda/mu спрямо кода отпреди K.1 - виж коментара във
            football_lib.py:86-92)
    ново  = use_dc=True,  low_data_extra_reg=15.0 (текущите дефолти)
- Пазари: 1X2 (3-класов Brier - сума на (p-actual)^2 по 3-те изхода;
  log-loss = -log(p на реалния изход)) и Over/Under 2.5 (бинарен Brier;
  log-loss аналогично).
- 4-те лиги с has_injuries=True (england, germany, spain, france) НЕ минават
  оттук - те ползват fit_goals_direct_covariate(), която няма use_dc/
  low_data_extra_reg параметри изобщо (football_lib.py:398) - K.1 буквално
  не може да ги е засегнал, структурно.
"""
import time
import numpy as np
import pandas as pd
from scipy.stats import poisson
import football_lib as fl

AFFECTED_LEAGUES = [
    "bulgaria", "champions_league", "europa_league", "conference_league",
    "italy", "portugal", "france2", "spain2", "italy2", "portugal2",
    "bulgaria2", "england2", "germany2",
]
UNAFFECTED_LEAGUES = ["england", "germany", "spain", "france"]  # fit_goals_direct_covariate, извън обхват на K.1

RETRAIN_EVERY = 20
MAX_TEST = 200
MIN_TEST = 60
MAX_G = 10


def outcome_probs(lam, mu, rho):
    pm = np.outer(poisson.pmf(range(MAX_G), lam), poisson.pmf(range(MAX_G), mu))
    if rho:
        pm = fl.dc_adjust_matrix(pm, lam, mu, rho)
    home = float(np.sum(np.tril(pm, -1)))
    draw = float(np.sum(np.diag(pm)))
    away = float(np.sum(np.triu(pm, 1)))
    total = home + draw + away
    over = float(sum(pm[x, y] for x in range(MAX_G) for y in range(MAX_G) if x + y > 2.5))
    return (home / total, draw / total, away / total), over / total if total else over


def run_config(df, team_idx, n, xi, test_df, use_dc, low_data_extra_reg, retrain_every):
    model = None
    rows = []
    for i, row in enumerate(test_df.itertuples()):
        if i % retrain_every == 0:
            history = df[df["date"] < row.date]
            model = fl.fit_goals_model(history, row.date, team_idx, n, xi=xi,
                                        use_dc=use_dc, low_data_extra_reg=low_data_extra_reg)
        lam, mu = fl.get_lambdas(model, team_idx, row.home_team, row.away_team)
        if lam is None:
            continue
        rho = model["rho"]
        (ph, pdw, pa), p_over = outcome_probs(lam, mu, rho)

        if row.home_goals > row.away_goals:
            actual = (1, 0, 0)
        elif row.home_goals == row.away_goals:
            actual = (0, 1, 0)
        else:
            actual = (0, 0, 1)
        probs = (ph, pdw, pa)
        brier_1x2 = sum((p - a) ** 2 for p, a in zip(probs, actual))
        p_actual = max(probs[actual.index(1)], 1e-10)
        ll_1x2 = -np.log(p_actual)

        actual_over = 1 if (row.home_goals + row.away_goals) > 2.5 else 0
        brier_ou = (p_over - actual_over) ** 2 + ((1 - p_over) - (1 - actual_over)) ** 2
        p_actual_ou = p_over if actual_over == 1 else (1 - p_over)
        ll_ou = -np.log(max(p_actual_ou, 1e-10))

        rows.append((brier_1x2, ll_1x2, brier_ou, ll_ou))
    return rows


def summarize(rows):
    arr = np.array(rows)
    return {
        "n": len(rows),
        "brier_1x2": arr[:, 0].mean(),
        "logloss_1x2": arr[:, 1].mean(),
        "brier_ou25": arr[:, 2].mean(),
        "logloss_ou25": arr[:, 3].mean(),
    }


def main():
    results = []
    t_start = time.time()
    for league in AFFECTED_LEAGUES:
        t0 = time.time()
        df = fl.load_league_data(league)
        df = df.dropna(subset=["home_goals", "away_goals"]).reset_index(drop=True)
        teams, n, team_idx = fl.get_team_index(df)
        xi = fl.LEAGUE_XI.get(league, fl.XI)

        test_size = int(min(MAX_TEST, max(MIN_TEST, len(df) * 0.10)))
        test_df = df.iloc[-test_size:].reset_index(drop=True)

        old_rows = run_config(df, team_idx, n, xi, test_df, use_dc=False, low_data_extra_reg=0.0,
                               retrain_every=RETRAIN_EVERY)
        new_rows = run_config(df, team_idx, n, xi, test_df, use_dc=True, low_data_extra_reg=15.0,
                               retrain_every=RETRAIN_EVERY)

        old_s = summarize(old_rows)
        new_s = summarize(new_rows)
        elapsed = time.time() - t0
        print(f"[{league}] n={old_s['n']} teams={n} elapsed={elapsed:.1f}s "
              f"brier_1x2 old={old_s['brier_1x2']:.4f} new={new_s['brier_1x2']:.4f} "
              f"logloss_1x2 old={old_s['logloss_1x2']:.4f} new={new_s['logloss_1x2']:.4f} "
              f"brier_ou old={old_s['brier_ou25']:.4f} new={new_s['brier_ou25']:.4f} "
              f"logloss_ou old={old_s['logloss_ou25']:.4f} new={new_s['logloss_ou25']:.4f}",
              flush=True)

        results.append({
            "league": league, "n_teams": n, "n_test_matches": old_s["n"], "elapsed_sec": round(elapsed, 1),
            "brier_1x2_old": old_s["brier_1x2"], "brier_1x2_new": new_s["brier_1x2"],
            "brier_1x2_diff_old_minus_new": old_s["brier_1x2"] - new_s["brier_1x2"],
            "logloss_1x2_old": old_s["logloss_1x2"], "logloss_1x2_new": new_s["logloss_1x2"],
            "logloss_1x2_diff_old_minus_new": old_s["logloss_1x2"] - new_s["logloss_1x2"],
            "brier_ou25_old": old_s["brier_ou25"], "brier_ou25_new": new_s["brier_ou25"],
            "brier_ou25_diff_old_minus_new": old_s["brier_ou25"] - new_s["brier_ou25"],
            "logloss_ou25_old": old_s["logloss_ou25"], "logloss_ou25_new": new_s["logloss_ou25"],
            "logloss_ou25_diff_old_minus_new": old_s["logloss_ou25"] - new_s["logloss_ou25"],
        })

    out = pd.DataFrame(results)
    out.to_csv("k1_walkforward_backtest_results.csv", index=False)
    print(f"\nОбщо време: {time.time()-t_start:.1f}s")
    print("Записано в k1_walkforward_backtest_results.csv")
    print(f"\n(4 лиги извън обхват - england/germany/spain/france - използват "
          f"fit_goals_direct_covariate(), която няма use_dc/low_data_extra_reg "
          f"параметри - K.1 структурно не ги засяга, не са тествани тук.)")


if __name__ == "__main__":
    main()
