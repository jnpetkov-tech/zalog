"""validation/pazar_goli_20261002.py - т.5а: над/под 1.5 и 3.5 гола, точен резултат (от матрицата на слоя AB). Настройки: pazari_nastroyki_20261002.md.
Изход: validation/pazar_goli_20261002.md. Употреба: nice -n 19 venv/bin/python3 validation/pazar_goli_20261002.py"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pazar_lib_20261002 as PL  # noqa: E402

X, Y_ = np.meshgrid(np.arange(10), np.arange(10), indexing="ij")
CELLS = [(i, j) for i in range(4) for j in range(4)]


def ou(pm, line):
    p = pm[:, X + Y_ > line].sum(1)
    return np.column_stack([p, 1 - p])


def exact(pm):
    p = np.column_stack([pm[:, i, j] for i, j in CELLS])
    return np.column_stack([p, 1 - p.sum(1)])


def y_ou(hg, ag, line):
    o = (hg + ag > line).astype(float)
    return np.column_stack([o, 1 - o])


def y_exact(hg, ag):
    y = np.column_stack([((hg == i) & (ag == j)).astype(float) for i, j in CELLS])
    return np.column_stack([y, 1 - y.sum(1)])


def main():
    late = PL.late_ab()
    early = PL.early_table()
    hg, ag = late["hg"].to_numpy(int), late["ag"].to_numpy(int)
    eh, ea = early["hg"].to_numpy(int), early["ag"].to_numpy(int)
    pm = PL.matrix(late["lam1"], late["mu1"], late["rho"])
    pm0 = PL.matrix(late["lam"], late["mu"], late["rho"])
    lines = ["# Т.5а — над/под 1.5 и 3.5 гола, точен резултат (02.10.2026)", "",
             "Настройки и критерии (записани преди резултатите): `validation/pazari_nastroyki_20261002.md`. Матрицата — от ядро+слой AB "
             "(живите настройки), walk-forward на късната половина (дата ≥ 2025-09-23).", ""] + PL.HEADER
    res = {}
    for name, P, Pc, Y, Yb in (("над/под 1.5", ou(pm, 1.5), ou(pm0, 1.5), y_ou(hg, ag, 1.5), y_ou(eh, ea, 1.5)),
                               ("над/под 3.5", ou(pm, 3.5), ou(pm0, 3.5), y_ou(hg, ag, 3.5), y_ou(eh, ea, 3.5)),
                               ("точен резултат (16 + друг)", exact(pm), exact(pm0), y_exact(hg, ag), y_exact(eh, ea))):
        b = Yb.mean(0)
        ok, L, num = PL.verdict(name, P, Y, b)
        res[name] = (ok, num, PL.brier(Pc, Y).mean(), PL.calib_a(Pc, Y, b))
        lines += L
    lines += ["", "За сведение — само ядрото (без слоя): " + "; ".join(f"{k}: Brier {v[2]:.5f}, a {v[3]:.3f}" for k, v in res.items()), "",
              "Реални честоти на късната половина: над 1.5 — {:.1%}, над 3.5 — {:.1%}; модел средно: {:.1%}, {:.1%}.".format(
                  (hg + ag > 1.5).mean(), (hg + ag > 3.5).mean(), ou(pm, 1.5)[:, 0].mean(), ou(pm, 3.5)[:, 0].mean()), ""]
    lines += ["## Решение", ""] + [f"- {k}: **{'влиза' if v[0] else 'не влиза'}**" + ("" if v[0] else
              f" (информативен: {'да' if v[1]['informative'] else 'не'}, a = {v[1]['a']:.3f})") for k, v in res.items()] + [""]
    open(os.path.join(PL.ROOT, "validation", "pazar_goli_20261002.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
