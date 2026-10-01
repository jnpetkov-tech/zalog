"""features/layer_select.py - избор на настройките на слоя САМО по ранната половина (дата < 2025-09-23).
Решетката и правилото за избор са записани в validation/sloy_nastroyki_20261001.md (комитнато преди този пуск).
Изход: validation/sloy_rana_20261001.csv (всички 288 настройки), validation/sloy_rana_20261001.md, features/layer_config.json.
Употреба: nice -n 19 venv/bin/python3 features/layer_select.py [--procs 14]
Късната половина НЕ се пипа тук: walk_forward получава end=EARLY_END (в обучението не влиза мач с дата >= понеделника на седмицата)."""
import itertools
import json
import os
import sys
import warnings
from multiprocessing import Pool

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from features import layer_lib as L  # noqa: E402

DEPTHS, MINCH, L2S = [2, 3, 4], [100, 300], [10, 100]
FSETS = ["A", "AB", "ABC", "ABCD"]
N_LIST, SHRINKS = [50, 100, 200], [0.5, 1.0]
T = LONG = MASK = Y = P0 = None


def init():
    global T, LONG, MASK, Y, P0
    T = L.load_table()
    LONG = L.to_long(T)
    MASK = (T["is_eval"] & (T["d"] >= L.EVAL_START) & (T["d"] < L.EARLY_END)).to_numpy()
    Y = L.y_matrix(T["hg"][MASK], T["ag"][MASK])
    P0 = L.probs(T["lam"][MASK], T["mu"][MASK], T["rho"][MASK])


def run(args):
    depth, mc, l2, fset = args
    cfg = {"depth": depth, "min_child": mc, "l2": l2, "n_list": N_LIST, "fset": fset}
    res, _ = L.walk_forward(LONG, T, cfg, L.EVAL_START, L.EARLY_END)
    rows = []
    for n in N_LIST:
        rh, ra = res[n]
        ok = MASK & ~np.isnan(rh) & ~np.isnan(ra)
        assert ok.sum() == MASK.sum(), (ok.sum(), MASK.sum())
        for s in SHRINKS:
            lam, mu = L.corrected(T, rh, ra, s)
            P = L.probs(lam[MASK], mu[MASK], T["rho"][MASK])
            bg = L.brier_group(P, Y)
            rows.append({"depth": depth, "min_child": mc, "l2": l2, "fset": fset, "n_est": n, "shrink": s,
                         "brier_all": float(L.brier_match(P, Y).mean()), **{f"brier_{g}": float(v.mean()) for g, v in bg.items()}})
    return rows


def main():
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 14
    init()
    base = {"brier_all": float(L.brier_match(P0, Y).mean())}
    bg0 = L.brier_group(P0, Y)
    base.update({f"brier_{g}": float(v.mean()) for g, v in bg0.items()})
    grid = list(itertools.product(DEPTHS, MINCH, L2S, FSETS))
    with Pool(procs, initializer=init) as pool:
        parts = pool.map(run, grid, chunksize=1)
    df = pd.DataFrame([r for p in parts for r in p])
    df["d_all"] = df["brier_all"] - base["brier_all"]
    df = df.sort_values("brier_all").reset_index(drop=True)
    df.round(6).to_csv(os.path.join(ROOT, "validation", "sloy_rana_20261001.csv"), index=False)
    best = df.iloc[0]
    near = df[df["brier_all"] <= best["brier_all"] + 2e-5].copy()
    near["fs_len"] = near["fset"].str.len()
    pick = near.sort_values(["n_est", "depth", "fs_len", "shrink", "min_child"]).iloc[0]
    cfg = {"depth": int(pick["depth"]), "min_child": int(pick["min_child"]), "l2": int(pick["l2"]), "fset": pick["fset"],
           "n_est": int(pick["n_est"]), "shrink": float(pick["shrink"]), "lr": 0.03,
           "selected_on": f"ранна половина (дата < {L.EARLY_END}), {int(MASK.sum())} мача",
           "early_brier_core": base["brier_all"], "early_brier_layer": float(pick["brier_all"]),
           "layer_beats_core_on_early": bool(pick["brier_all"] < base["brier_all"])}
    json.dump(cfg, open(os.path.join(ROOT, "features", "layer_config.json"), "w"), ensure_ascii=False, indent=1)
    Lm = ["# Избор на настройките на слоя — само ранна половина — 01.10.2026", "",
          "Предварителна регистрация: `sloy_nastroyki_20261001.md`. Скрипт: `features/layer_select.py`. Всички 288 настройки: `sloy_rana_20261001.csv`.", "",
          f"Ранна половина: {int(MASK.sum())} мача (дата от {L.EVAL_START} до {L.EARLY_END}). Ядро сам: Brier (11 изхода) **{base['brier_all']:.5f}**.", "",
          "## 10-те най-добри настройки (Brier, по-малко е по-добре)", "",
          "| дълбочина | мин. мача/лист | L2 | дървета | s | набор | Brier | разлика спрямо ядрото |", "|---|---|---|---|---|---|---|---|"]
    for r in df.head(10).itertuples():
        Lm.append(f"| {r.depth} | {r.min_child} | {r.l2} | {r.n_est} | {r.shrink} | {r.fset} | {r.brier_all:.5f} | {r.d_all:+.5f} |")
    Lm += ["", "## Най-добрата по набор признаци", "", "| набор | най-добър Brier | разлика спрямо ядрото |", "|---|---|---|"]
    for fs in FSETS:
        r = df[df["fset"] == fs].iloc[0]
        Lm.append(f"| {fs} | {r.brier_all:.5f} | {r.d_all:+.5f} |")
    Lm += ["", "## Колко настройки са по-добри от ядрото на ранната половина", "",
           f"{int((df['d_all'] < 0).sum())} от {len(df)} (разлика < 0).", "",
           "## Избрана настройка (правилото: най-малък Brier; при разлика < 0.00002 — по-простата)", "", "```json", json.dumps(cfg, ensure_ascii=False, indent=1), "```", ""]
    open(os.path.join(ROOT, "validation", "sloy_rana_20261001.md"), "w", encoding="utf-8").write("\n".join(Lm))
    print("\n".join(Lm))


if __name__ == "__main__":
    main()
