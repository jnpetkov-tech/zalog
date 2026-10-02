"""validation/pazar_btts_20261002.py - т.6: "двата отбора вкарват" като отделна цел (LightGBM двоична), срещу сегашното показвано P(btts)
(слой AB + LAYER_CALIBRATION_A["btts"]). Настройки: pazari_nastroyki_20261002.md (вкл. поправката за init преди пускане).
Изход: validation/pazar_btts_20261002.md. Употреба: nice -n 19 venv/bin/python3 validation/pazar_btts_20261002.py"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pazar_lib_20261002 as PL  # noqa: E402
from features import layer_lib as L  # noqa: E402

CFG = {"depth": 3, "min_child": 300, "l2": 100, "n_est": 200, "lr": 0.03, "fset": "AB"}


def p_btts(pm):
    return pm[:, 1:, 1:].sum((1, 2))


def main():
    import lightgbm as lgb
    import layer_live
    import prediction_policy as policy
    t = L.load_table()
    long = L.to_long(t)
    n = len(t)
    home = long.iloc[:n]                                   # own = домакин, opp = гост
    cols = L.feature_columns("AB")
    X = home[cols].to_numpy(np.float32)
    y = ((t["hg"] >= 1) & (t["ag"] >= 1)).astype(float).to_numpy()
    p0 = np.clip(p_btts(PL.matrix(t["lam"], t["mu"], t["rho"])), 1e-4, 1 - 1e-4)
    init = np.log(p0 / (1 - p0))
    dts, wk = t["d"].to_numpy(), t["week"].to_numpy()
    early, late = PL.halves(t)
    raw = np.full(n, np.nan)
    params = {**L.lgb_params(CFG), "objective": "binary"}
    for w in sorted(np.unique(wk[late])):
        tr = dts < w
        te = (wk == w) & late
        if tr.sum() < 3000 or not te.any():
            continue
        bst = lgb.train(params, lgb.Dataset(X[tr], label=y[tr], init_score=init[tr], feature_name=cols, categorical_feature=["league_code"]),
                        num_boost_round=CFG["n_est"])
        raw[te] = bst.predict(X[te], raw_score=True)
    p_new = 1 / (1 + np.exp(-(init + raw)))
    # сегашното показвано: слой AB (walk-forward, същия кеш като т.5) + калибрацията за слоя
    lab = PL.late_ab().set_index("fixture_id")
    fl = t["fixture_id"].to_numpy()[late]
    lab = lab.loc[fl]
    p_lay = p_btts(PL.matrix(lab["lam1"], lab["mu1"], lab["rho"]))
    b_live = policy.CALIBRATION_BASE["btts_yes"]
    a_live = layer_live.LAYER_CALIBRATION_A["btts"]
    p_cur = np.clip(b_live + a_live * (p_lay - b_live), 0, 1)
    pn = p_new[late]
    Y = np.column_stack([y[late], 1 - y[late]])
    b = np.array([y[early].mean(), 1 - y[early].mean()])
    Pn, Pc, Pr = (np.column_stack([p, 1 - p]) for p in (pn, p_cur, p_lay))
    bn, bc = PL.brier(Pn, Y), PL.brier(Pc, Y)
    d = L.boot_ci(bn - bc)
    a_n, a_c = PL.calib_a(Pn, Y, b), PL.calib_a(Pc, Y, b)
    ll = lambda p: -np.log(np.where(y[late] == 1, p, 1 - p))  # noqa: E731
    dl = L.boot_ci(ll(pn) - ll(p_cur))
    beats = d[2] < 0
    in_frame = 0.9 <= a_n <= 1.1
    ok = beats and in_frame
    lines = ["# Т.6 — „двата отбора вкарват“ като отделна цел (02.10.2026)", "",
             "Настройки и критерии (записани преди резултатите, с поправката за началната стойност): `validation/pazari_nastroyki_20261002.md`.",
             f"LightGBM двоична, init = logit P(btts) от ядрото, признаци AB, depth 3 / min_child 300 / l2 100 / 200 дървета; седмично префитване. "
             f"Късна половина: **{int(late.sum())} мача**.", "",
             "| | Brier | log-loss | a (късна) |", "|---|---|---|---|",
             f"| сегашно показвано (слой AB + калибрация a={a_live}) | {bc.mean():.5f} | {ll(p_cur).mean():.5f} | {a_c:.3f} |",
             f"| слой AB без калибрация | {PL.brier(Pr, Y).mean():.5f} | {ll(p_lay).mean():.5f} | {PL.calib_a(Pr, Y, b):.3f} |",
             f"| ядро само | {PL.brier(np.column_stack([p0[late], 1 - p0[late]]), Y).mean():.5f} | {ll(p0[late]).mean():.5f} | "
             f"{PL.calib_a(np.column_stack([p0[late], 1 - p0[late]]), Y, b):.3f} |",
             f"| **нов (отделна цел)** | {bn.mean():.5f} | {ll(pn).mean():.5f} | {a_n:.3f} |", "",
             f"Нов − сегашен: Brier {d[0]:+.5f} [{d[1]:+.5f}; {d[2]:+.5f}], log-loss {dl[0]:+.5f} [{dl[1]:+.5f}; {dl[2]:+.5f}].",
             f"Реална честота на късната: {y[late].mean():.3f}; средно нов {pn.mean():.3f}, сегашен {p_cur.mean():.3f}.", "",
             "## Решение", "",
             f"Бие сегашното значимо: {'ДА' if beats else 'НЕ'}; калибрация в 0.9–1.1: {'ДА' if in_frame else 'НЕ'} → "
             f"**{'ВЛИЗА' if ok else 'НЕ ВЛИЗА — остава сегашното'}**.", ""]
    open(os.path.join(PL.ROOT, "validation", "pazar_btts_20261002.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
