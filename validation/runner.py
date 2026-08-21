"""
validation/runner.py — общ инструмент за before/after backtest на промени
в fit_goals_model() (football_lib.py).

Виж README.md в тази папка за пълния метод. Накратко: walk-forward backtest
(моделът се преизчислява само от историята ПРЕДИ всеки тестван мач, никога
от бъдещи данни), сравнява произволен брой именувани конфигурации на
fit_goals_model() върху ИДЕНТИЧНИ тестови мачове и ИДЕНТИЧНИ re-train точки.
Пазари: 1X2 (3-класов Brier/log-loss) и Over/Under 2.5 (бинарен Brier/
log-loss).

Употреба:
    python3 validation/runner.py --name моя_промяна \
        --leagues bulgaria,italy,portugal \
        --config старо:use_dc=False,low_data_extra_reg=0.0 \
        --config ново:use_dc=True,low_data_extra_reg=20.0

Резултат: validation/<name>_<YYYYMMDD>.csv — ред на (лига, конфигурация),
n тествани мача, Brier/log-loss за 1X2 и OU2.5.

Ограничение: важи само за лиги, минаващи през fit_goals_model() (не
fit_goals_direct_covariate() - england/germany/spain/france, с
has_injuries=True - тази функция няма use_dc/low_data_extra_reg параметри
изобщо, виж football_lib.py). Провери кой fit_* минава за твоята лига
преди да вярваш на резултата.

Произлиза от k1_walkforward_backtest.py (21.08.2026, преместен в
archive/ - виж git history) - същата математика, вече параметризирана
вместо хардкодната "старо"/"ново" двойка, за да се преизползва.
"""
import argparse
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import poisson

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import football_lib as fl  # noqa: E402

RETRAIN_EVERY = 20
MAX_TEST = 200
MIN_TEST = 60
MAX_G = 10


def parse_config_arg(raw):
    """'label:k1=v1,k2=v2' -> (label, {k1: v1_typed, ...}), с проста type-inference."""
    label, _, kv_part = raw.partition(":")
    kwargs = {}
    if kv_part:
        for pair in kv_part.split(","):
            k, _, v = pair.partition("=")
            if v in ("True", "False"):
                kwargs[k] = (v == "True")
            else:
                try:
                    kwargs[k] = float(v) if "." in v else int(v)
                except ValueError:
                    kwargs[k] = v
    return label, kwargs


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


def run_config(df, team_idx, n, xi, test_df, fit_kwargs, retrain_every):
    model = None
    rows = []
    for i, row in enumerate(test_df.itertuples()):
        if i % retrain_every == 0:
            history = df[df["date"] < row.date]
            model = fl.fit_goals_model(history, row.date, team_idx, n, xi=xi, **fit_kwargs)
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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="кратко име на промяната, влиза в името на изходния CSV")
    ap.add_argument("--leagues", required=True, help="списък лиги през запетая, напр. bulgaria,italy,portugal")
    ap.add_argument("--config", action="append", required=True, dest="configs",
                     help="label:k=v,k=v - fit_goals_model() kwargs, може да се повтори")
    ap.add_argument("--retrain-every", type=int, default=RETRAIN_EVERY)
    ap.add_argument("--min-test", type=int, default=MIN_TEST)
    ap.add_argument("--max-test", type=int, default=MAX_TEST)
    args = ap.parse_args()

    leagues = [s.strip() for s in args.leagues.split(",") if s.strip()]
    configs = [parse_config_arg(c) for c in args.configs]

    results = []
    t_start = time.time()
    for league in leagues:
        t0 = time.time()
        df = fl.load_league_data(league)
        df = df.dropna(subset=["home_goals", "away_goals"]).reset_index(drop=True)
        teams, n, team_idx = fl.get_team_index(df)
        xi = fl.LEAGUE_XI.get(league, fl.XI)

        test_size = int(min(args.max_test, max(args.min_test, len(df) * 0.10)))
        test_df = df.iloc[-test_size:].reset_index(drop=True)

        summaries = {}
        for label, kwargs in configs:
            rows = run_config(df, team_idx, n, xi, test_df, kwargs, args.retrain_every)
            summaries[label] = summarize(rows)

        elapsed = time.time() - t0
        parts = " ".join(
            f"{label}: brier_1x2={s['brier_1x2']:.4f} logloss_1x2={s['logloss_1x2']:.4f} "
            f"brier_ou={s['brier_ou25']:.4f} logloss_ou={s['logloss_ou25']:.4f}"
            for label, s in summaries.items()
        )
        print(f"[{league}] n={next(iter(summaries.values()))['n']} teams={n} "
              f"elapsed={elapsed:.1f}s {parts}", flush=True)

        for label, s in summaries.items():
            results.append({
                "league": league, "config": label, "n_teams": n,
                "n_test_matches": s["n"], "elapsed_sec": round(elapsed, 1),
                "brier_1x2": s["brier_1x2"], "logloss_1x2": s["logloss_1x2"],
                "brier_ou25": s["brier_ou25"], "logloss_ou25": s["logloss_ou25"],
            })

    out = pd.DataFrame(results)
    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(out_dir, f"{args.name}_{date.today().strftime('%Y%m%d')}.csv")
    out.to_csv(out_path, index=False)
    print(f"\nОбщо време: {time.time()-t_start:.1f}s")
    print(f"Записано в {out_path}")


if __name__ == "__main__":
    main()
