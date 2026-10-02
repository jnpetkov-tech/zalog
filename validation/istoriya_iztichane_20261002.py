"""validation/istoriya_iztichane_20261002.py - проверка срещу изтичане на удължената таблица (ZADACHA_RAZVITIE т.3).

Същият метод като features/leak_check.py (част А): за 200 случайни мача (seed 42) от features/features_table_hist.csv.gz данните се
режат до началото на мача (build_features.truncate) и редът се смята наново; всеки признак трябва да съвпада ТОЧНО.
Данните = живите файлове + hist/ (както при строенето). Изход: validation/istoriya_iztichane_20261002.md
"""
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from features import build_features as bf  # noqa: E402
from features import leak_check as lc  # noqa: E402

N_SAMPLE = 200
SEED = 42
HIST_END = "2023-08-01"


def _init():
    if os.path.join(ROOT, "hist") not in bf.EXTRA_DIRS:
        bf.EXTRA_DIRS.append(os.path.join(ROOT, "hist"))
    lc.RAW = bf.index_raw(bf.load_raw())
    lc.CORE = pd.read_csv(os.path.join(ROOT, "features", "core_lam_mu_hist.csv"))
    lc.TAB = pd.read_csv(os.path.join(ROOT, "features", "features_table_hist.csv.gz"), float_precision="round_trip")


def main():
    _init()
    tab = lc.TAB[lc.TAB["date"] < HIST_END]
    ids = np.random.default_rng(SEED).choice(tab["fixture_id"].to_numpy(), size=N_SAMPLE, replace=False)
    with Pool(6, initializer=_init) as pool:
        res = pool.map(lc.check_one, [int(i) for i in ids], chunksize=2)
    mism = {}
    for fid, bad in res:
        for c in bad:
            mism.setdefault(c, []).append(fid)
    n_ok = sum(1 for _, b in res if not b)
    sample = tab[tab["fixture_id"].isin(ids)]
    lines = ["# Удължената таблица — проверка срещу изтичане (02.10.2026)", "",
             f"Метод: `features/leak_check.py`, част А — {N_SAMPLE} случайни мача (seed {SEED}) от `features_table_hist.csv.gz` с дата < {HIST_END}",
             f"({sample['date'].min()} → {sample['date'].max()}, {sample['league'].nunique()} лиги). Данните се режат до началото на мача и редът "
             "се смята наново; признакът трябва да съвпада точно.", "",
             f"**Резултат: {n_ok} от {N_SAMPLE} мача съвпадат напълно.**", ""]
    if mism:
        lines += ["| признак | мачове с разлика |", "|---|---|"] + [f"| {c} | {len(v)} ({', '.join(map(str, v[:5]))}) |" for c, v in mism.items()]
    open(os.path.join(ROOT, "validation", "istoriya_iztichane_20261002.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
