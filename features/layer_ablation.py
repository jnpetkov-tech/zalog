"""features/layer_ablation.py - ИНФОРМАТИВНО (не е избор, не променя настройката): колко от ползата на слоя идва от кой блок признаци и
дали е стабилна във времето. За всеки набор (A, AB, ABC, ABCD) - най-добрата настройка по РАННАТА половина (от sloy_rana*.csv), мерена
на късната. Разликата ядро+слой − ядро (Brier, 11 изхода) с 95% интервал; и по тримесечия на късната половина за главния набор.
Изход: validation/sloy_20261001_ablation.md. ЗАБЕЛЕЖКА: мери късната половина още веднъж - само за обясняване на главния резултат."""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from features import layer_lib as L  # noqa: E402


def main():
    T = L.load_table()
    LONG = L.to_long(T)
    late = (T["is_eval"] & (T["d"] >= L.EARLY_END)).to_numpy()
    early_all = pd.concat([pd.read_csv(os.path.join(ROOT, "validation", f)) for f in ("sloy_rana_20261001.csv", "sloy_rana2_20261001.csv")])
    Y = L.y_matrix(T["hg"][late], T["ag"][late])
    P0 = L.probs(T["lam"][late], T["mu"][late], T["rho"][late])
    b0 = L.brier_match(P0, Y)
    l0 = np.mean(list(L.logloss_match(P0, Y).values()), axis=0)
    rows, main_pred = [], None
    for fset in ["A", "AB", "ABC", "ABCD"]:
        best = early_all[early_all["fset"] == fset].sort_values("brier_all").iloc[0]
        cfg = {"depth": int(best["depth"]), "min_child": int(best["min_child"]), "l2": int(best["l2"]), "n_list": [int(best["n_est"])], "fset": fset}
        res, _ = L.walk_forward(LONG, T, cfg, L.EARLY_END, None)
        rh, ra = res[cfg["n_list"][0]]
        lam, mu = L.corrected(T, rh, ra, float(best["shrink"]))
        P1 = L.probs(lam[late], mu[late], T["rho"][late])
        b1 = L.brier_match(P1, Y)
        l1 = np.mean(list(L.logloss_match(P1, Y).values()), axis=0)
        d = L.boot_ci(b1 - b0)
        dl = L.boot_ci(l1 - l0)
        rows.append({"fset": fset, "early_diff": float(best["d_all"]), "depth": cfg["depth"], "n_est": cfg["n_list"][0], "d": d, "dl": dl})
        if fset == "ABC":
            main_pred = b1 - b0
    dts = T["d"][late].reset_index(drop=True)
    q = pd.PeriodIndex(dts, freq="Q").astype(str)
    L_ = ["# Слой върху ядрото — информативна разбивка по блокове и по време — 01.10.2026", "",
          "Не е избор и не променя настройката (тя е записана в `features/layer_config.json` преди късната половина). За всеки набор признаци е взета най-добрата "
          "настройка по РАННАТА половина и е мерена на късната. Скрипт: `features/layer_ablation.py`.", "",
          "| набор | какво включва | ранна разлика | късна: Brier слой − ядро | 95% | log-loss разлика | 95% |", "|---|---|---|---|---|---|---|"]
    desc = {"A": "календар + класиране + форма (всичко „ранно“)", "AB": "+ удари/xG", "ABC": "+ състав/отсъстващи/треньор/контузени (главният)",
            "ABCD": "+ съдия/час/месец"}
    for r in rows:
        L_.append(f"| {r['fset']} | {desc[r['fset']]} | {r['early_diff']:+.5f} | {r['d'][0]:+.5f} | [{r['d'][1]:+.5f}; {r['d'][2]:+.5f}] | "
                  f"{r['dl'][0]:+.5f} | [{r['dl'][1]:+.5f}; {r['dl'][2]:+.5f}] |")
    L_ += ["", "## Стабилност по тримесечия (главният набор ABC, късна половина)", "", "| тримесечие | мачове | Brier слой − ядро | 95% |", "|---|---|---|---|"]
    for per in sorted(set(q)):
        m = (q == per)
        d = L.boot_ci(main_pred[m])
        L_.append(f"| {per} | {int(m.sum())} | {d[0]:+.5f} | [{d[1]:+.5f}; {d[2]:+.5f}] |")
    out = "\n".join(L_) + "\n"
    open(os.path.join(ROOT, "validation", "sloy_20261001_ablation.md"), "w", encoding="utf-8").write(out)
    print(out)


if __name__ == "__main__":
    main()
