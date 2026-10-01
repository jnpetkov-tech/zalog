"""features/core_lam_mu.py - ЯДРОТО за таблицата с признаци (ZADACHA_TABLICA стъпка 1, 01.10.2026).

Очакваните голове на двата отбора (lam = домакин, mu = гост) от walk-forward, ТОЧНО както в мерилото:
validation/final_b_20260924.run() (свито темпо FT_FIT_SETTINGS, контузии, xG смес, общ евро модел за трите турнира;
настройките се четат от match_predictor_app.py с ast, без импорт), седмично префитване само от мачове ПРЕДИ понеделника
на седмицата. Разликата спрямо мерилото е само ПРОЗОРЕЦЪТ: вместо последните 730 дни - от START нататък (удължен назад,
за да има повече мачове, на които слоят може да се учи; новите изтеглени данни 2022-23 позволяват признаци и там) и
до последния изигран мач в CSV-тата (включва мачовете след 21.09.2026, които мерилото още нямаше).

Изход: features/core_lam_mu.csv (league, fixture_id, date, hg, ag, lam, mu, rho). Контрол: същите lam/mu като
validation/final_v_20260924_matches.csv за общите мачове (features/core_control.md).
Употреба: nice -n 19 venv/bin/python3 features/core_lam_mu.py [--procs 8]
"""
import os
import sys

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
from multiprocessing import Pool  # noqa: E402

import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

START = pd.Timestamp("2023-08-01")     # първият тестов мач (историята от 2022-08 дава поне година за фитване)
OUT = os.path.join(ROOT, "features", "core_lam_mu.csv")


def job(league):
    import backfill_common  # noqa: F401  (само за пътя; не прави нищо)
    import backtest_full as bf
    import final_b_20260924 as fb
    import football_lib as fl
    df = fl.load_league_data(league)
    fin = df.dropna(subset=["home_goals", "away_goals"])
    bf.PERIOD_DAYS = int((fin["date"].max() - START).days) + 1     # прозорецът се чете от test_weeks() във final_b
    t, _ = fb.run((league, 1.0))
    return t.drop(columns=["xi_mult", "week"])


def main():
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 8
    import backtest_full as bf
    leagues = list(bf.LEAGUES)
    with Pool(procs) as pool:
        parts = pool.map(job, leagues, chunksize=1)
    core = pd.concat(parts, ignore_index=True)
    core.to_csv(OUT, index=False)
    print(len(core), "мача ->", OUT)


if __name__ == "__main__":
    main()
