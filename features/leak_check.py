"""features/leak_check.py - проверка срещу изтичане на информация (ZADACHA_TABLICA, стъпка 2, 01.10.2026).

А. 200 случайни мача (seed 42): признаците се смятат НАНОВО само с данни, отрязани до началото на мача
   (build_features.truncate: резултати/събития/статистика/състави само на мачове със ts < ts на мача; от самия мач -
   предмачовата информация: състав, контузени, съдия, час; разписанието остава, но без резултати) и се сравняват
   ТОЧНО (==, NaN==NaN) със стойностите в таблицата. Всяко разминаване = признакът ползва информация отпреди/след границата
   различно от таблицата.
Б. Тест с разбъркан признак: за всеки признак - корелация (Spearman) с остатъка на ядрото (hg-lam за домакин/общите, ag-mu за гост)
   върху всички мачове; "твърде добър" = |rho| > 0.15 (предмачови признаци при ядро, което вече е видяло историята, носят
   ~0.01-0.08). За 10-те най-силни: 200 пъти се разбърква колоната и се гледа, че корелацията пада до шума (|rho| < 3.5/sqrt(n)),
   т.е. сигналът е в самия признак, а не в подравняването на редовете.
Изход: validation/tablica_iztichane_20261001.md + validation/tablica_iztichane_20261001_univariate.csv.
Употреба: nice -n 19 venv/bin/python3 features/leak_check.py [--procs 6]
"""
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from features import build_features as bf  # noqa: E402

N_SAMPLE = 200
SEED = 42
FLAG = 0.15
RAW = CORE = TAB = None


def _init():
    global RAW, CORE, TAB
    RAW = bf.index_raw(bf.load_raw())
    CORE = pd.read_csv(os.path.join(ROOT, "features", "core_lam_mu.csv"))
    TAB = pd.read_csv(os.path.join(ROOT, "features", "features_table.csv.gz"), float_precision="round_trip")   # точно връщане на записаните float


def _same(a, b):
    if pd.isna(a) and pd.isna(b):
        return True
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return a == b


def check_one(fid):
    row = TAB[TAB["fixture_id"] == fid].iloc[0]
    ts = int(row["ts"])
    cut = bf.truncate(RAW, ts, fid)
    new = bf.build(CORE[CORE["fixture_id"] == fid], cut).iloc[0]
    bad = [c for c in TAB.columns if not _same(row[c], new.get(c, np.nan))]
    return fid, bad


def main():
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 6
    _init()
    rng = np.random.default_rng(SEED)
    ids = rng.choice(TAB["fixture_id"].to_numpy(), size=N_SAMPLE, replace=False)
    with Pool(procs, initializer=_init) as pool:
        res = pool.map(check_one, [int(i) for i in ids], chunksize=2)
    mism = {}
    for fid, bad in res:
        for c in bad:
            mism.setdefault(c, []).append(fid)
    n_ok = sum(1 for _, b in res if not b)

    # ---- Б. едномерно сканиране + разбъркване
    t = TAB.copy()
    t["res_h"] = t["hg"] - t["lam"]
    t["res_a"] = t["ag"] - t["mu"]
    t["res_s"] = (t["hg"] + t["ag"]) - (t["lam"] + t["mu"])
    skip = {"fixture_id", "ts", "hg", "ag", "lam", "mu", "rho", "res_h", "res_a", "res_s", "league", "date", "season"}
    feats = [c for c in t.columns if c not in skip and pd.api.types.is_numeric_dtype(t[c])]
    rows = []
    for c in feats:
        tgt = "res_a" if c.startswith("a_") else "res_h" if c.startswith("h_") else "res_s"
        m = t[[c, tgt]].dropna()
        if len(m) < 500 or m[c].nunique() < 2:
            continue
        rho = spearmanr(m[c], m[tgt])[0]
        rows.append({"feature": c, "target": tgt, "n": len(m), "rho": rho})
    uni = pd.DataFrame(rows)
    uni["abs_rho"] = uni["rho"].abs()
    uni = uni.sort_values("abs_rho", ascending=False)
    uni.round(5).to_csv(os.path.join(ROOT, "validation", "tablica_iztichane_20261001_univariate.csv"), index=False)
    shuf = []
    for r in uni.head(10).itertuples():
        m = t[[r.feature, r.target]].dropna()
        sims = []
        for _ in range(200):
            sims.append(abs(spearmanr(rng.permutation(m[r.feature].to_numpy()), m[r.target])[0]))
        shuf.append({"feature": r.feature, "rho": r.rho, "shuffled_max_abs": float(np.max(sims)),
                     "shuffled_mean_abs": float(np.mean(sims)), "noise_limit": 3.5 / np.sqrt(len(m))})
    shuf = pd.DataFrame(shuf)
    flagged = uni[uni["abs_rho"] > FLAG]

    L = ["# Проверка срещу изтичане — таблица с признаци — 01.10.2026", "",
         "Скрипт: `features/leak_check.py`. Таблица: `features/features_table.csv.gz` (18 435 мача, 150 колони). "
         "Правилото на времето: `features/build_features.py` (докстринг) и `features/README.md`.", "",
         "## А. Наново пресмятане с данни, отрязани до началото на мача", "",
         f"{N_SAMPLE} случайни мача (seed {SEED}). За всеки: данните се режат до ts на мача — резултати, събития, статистика и състави "
         "само на мачове със **строго по-ранен** ts; от самия мач остава само предмачовата информация (състав, контузени, съдия, час, кръг); "
         "разписанието остава, но без резултати. Признаците се смятат наново със същия код и се сравняват **точно** (==) със записаните.", "",
         f"**Точно съвпадение: {n_ok} от {N_SAMPLE} мача** ({sum(len(b) for _, b in res)} разминавания на колона).", ""]
    if mism:
        L += ["| колона | брой мача с разминаване | примерен fixture_id |", "|---|---|---|"]
        for c, f in sorted(mism.items(), key=lambda kv: -len(kv[1])):
            L.append(f"| {c} | {len(f)} | {f[0]} |")
        L.append("")
    else:
        L += ["Нито една колона не се разминава.", ""]
    L += ["## Б. Тест с разбъркан признак", "",
          f"Корелация (Spearman) на всеки признак с остатъка на ядрото (hg−lam за `h_*`, ag−mu за `a_*`, общ остатък за останалите), върху всички "
          f"мачове. Праг „твърде добър“: |ρ| > {FLAG}. Най-силните 15:", "",
          "| признак | цел | n | ρ |", "|---|---|---|---|"]
    for r in uni.head(15).itertuples():
        L.append(f"| {r.feature} | {r.target} | {r.n} | {r.rho:+.4f} |")
    L += ["", f"**Признаци над прага {FLAG}: {len(flagged)}**" + (": " + ", ".join(flagged["feature"]) if len(flagged) else "."), "",
          "Разбъркване на колоната на 10-те най-силни (200 пъти): корелацията трябва да падне до шума.", "",
          "| признак | ρ (реално) | средно \\|ρ\\| разбъркано | макс. \\|ρ\\| разбъркано | граница на шума (3.5/√n) |", "|---|---|---|---|---|"]
    for r in shuf.itertuples():
        L.append(f"| {r.feature} | {r.rho:+.4f} | {r.shuffled_mean_abs:.4f} | {r.shuffled_max_abs:.4f} | {r.noise_limit:.4f} |")
    ok_shuf = bool((shuf["shuffled_max_abs"] < shuf["noise_limit"] * 1.3).all())
    verdict = n_ok == N_SAMPLE and len(flagged) == 0 and ok_shuf
    L += ["", "## Извод", "",
          f"- А: {'ЧИСТО' if n_ok == N_SAMPLE else 'ИМА РАЗМИНАВАНИЯ'} ({n_ok}/{N_SAMPLE} мача съвпадат точно).",
          f"- Б: признаци над прага: {len(flagged)}; разбъркването {'сваля корелацията до шума' if ok_shuf else 'НЕ сваля корелацията до шума - да се провери'}.",
          f"- **{'Чиста проверка — може да се продължи към обучения слой.' if verdict else 'Проверката НЕ е чиста — не се продължава, докато не се обясни.'}**"]
    with open(os.path.join(ROOT, "validation", "tablica_iztichane_20261001.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
