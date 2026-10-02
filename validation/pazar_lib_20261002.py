"""validation/pazar_lib_20261002.py - обща основа за новите пазари (ZADACHA_RAZVITIE т.5/т.6). Настройки: validation/pazari_nastroyki_20261002.md.

late_ab()   - слой AB (живите настройки) walk-forward на късната половина: lam′/mu′ по мач (кеш validation/pazar_ab_late_20261002.csv).
matrix()    - матрицата на резултата като в живия код (Поасон + DC + SCORE_DEP).
calib_a()   - a = Σ(p−b)(y−b)/Σ(p−b)² за един пазар (P, Y: (N, K)); b - честотите на ранната половина.
verdict()   - Brier срещу константата b (bootstrap), a в 0.9-1.1 -> текст и минал/не.
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
from features import layer_lib as L  # noqa: E402

AB = {"depth": 3, "min_child": 300, "l2": 100, "n_est": 200, "shrink": 1.0, "fset": "AB"}
CACHE = os.path.join(ROOT, "validation", "pazar_ab_late_20261002.csv")
A_RANGE = (0.9, 1.1)


def halves(t):
    early = (t["is_eval"] & (t["d"] >= L.EVAL_START) & (t["d"] < L.EARLY_END)).to_numpy()
    late = (t["is_eval"] & (t["d"] >= L.EARLY_END)).to_numpy()
    return early, late


def late_ab():
    """DataFrame на късната половина: fixture_id, league, date, ts, hg, ag, lam, mu, rho (ядро), lam1, mu1 (ядро+слой AB)."""
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE)
    t = L.load_table()
    long = L.to_long(t)
    res, _ = L.walk_forward(long, t, {**AB, "n_list": [AB["n_est"]]}, L.EARLY_END, None)
    rh, ra = res[AB["n_est"]]
    lam1, mu1 = L.corrected(t, rh, ra, AB["shrink"])
    _, late = halves(t)
    out = t.loc[late, ["fixture_id", "league", "date", "ts", "hg", "ag", "lam", "mu", "rho"]].copy()
    out["lam1"], out["mu1"] = lam1[late], mu1[late]
    out.to_csv(CACHE, index=False)
    return out


def early_table():
    t = L.load_table()
    early, _ = halves(t)
    return t[early]


def matrix(lam, mu, rho):
    import final_a_20260924 as fa
    import football_lib as fl
    import razpredelenie_b_20260923 as rb
    lam, mu, rho = (np.asarray(x, float) for x in (lam, mu, rho))
    return fa.shift(rb.matrices(lam, mu, rho, "poisson", 0), lam, mu, fl.SCORE_DEP_F0, fl.SCORE_DEP_F1)


def calib_a(P, Y, b):
    d = P - b[None, :]
    return float((d * (Y - b[None, :])).sum() / (d * d).sum())


def brier(P, Y):
    return ((P - Y) ** 2).mean(1)


def verdict(name, P, Y, b, extra_ok=True, extra_text=""):
    """-> (минал?, редове на доклада, речник с числата)."""
    bm, bb = brier(P, Y), brier(np.repeat(b[None, :], len(Y), 0), Y)
    d = L.boot_ci(bm - bb)
    a = calib_a(P, Y, b)
    informative = d[2] < 0
    in_frame = A_RANGE[0] <= a <= A_RANGE[1]
    ok = informative and in_frame and extra_ok
    lines = [f"| {name} | {len(Y)} | {bm.mean():.5f} | {bb.mean():.5f} | {d[0]:+.5f} [{d[1]:+.5f}; {d[2]:+.5f}] | {a:.3f} | "
             f"{'да' if informative else 'НЕ'} | {'да' if in_frame else 'НЕ'} |{(' ' + extra_text + ' |') if extra_text else ''} **{'МИНАВА' if ok else 'НЕ МИНАВА'}** |"]
    return ok, lines, {"brier": bm.mean(), "brier_base": bb.mean(), "d": d, "a": a, "informative": informative, "in_frame": in_frame}


HEADER = ["| пазар | мачове | Brier модел | Brier честота (b) | разлика [95%] | a (късна) | информативен | a в 0.9–1.1 | решение |",
          "|---|---|---|---|---|---|---|---|---|"]
