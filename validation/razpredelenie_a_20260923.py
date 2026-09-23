"""
validation/razpredelenie_a_20260923.py - ZADACHA_RAZPREDELENIE.md, ЧАСТ А.

Германия/Франция обратно. Правилото за диапазона в kalibraciq_xg_20260923.py
беше абсолютно (сместа в 0.3-3.5) и отряза лиги, при които сместа ПОДОБРЯВА
диапазона. Поправено правило: сместа влиза, ако НЕ ВЛОШАВА диапазона спрямо
сегашния модел - макс на сместа <= макс на сегашния И мин на сместа >= мин на
сегашния, отделно за двете проверки (мерилото, ранна+късна, и всички двойки
отбори днес). Без абсолютен праг.

Останалите две условия - без промяна: (1) избраното w > 0 (избор върху
ранната половина), (2) на КЪСНАТА половина калибрация + xG < само калибрация.

Всичко останало (модел Б, избор на w, калибрацията, bootstrap) - изцяло от
kalibraciq_xg_20260923.py, импортирано, не копирано. Изход:
validation/razpredelenie_a_20260923.md/.csv.

Употреба: venv/bin/python3 validation/razpredelenie_a_20260923.py
"""
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

import backtest_full as bf  # noqa: E402
import kalibraciq_xg_20260923 as kx  # noqa: E402

TAG = "20260923"
OLD_KEEP = {"england": 0.7, "spain": 0.7, "england2": 0.5}


def main():
    m = pd.read_csv(kx.SRC)
    m["d"] = pd.to_datetime(m["date"])
    xl = kx.xg_leagues()
    with Pool(len(xl)) as pool:
        bres = dict(pool.map(kx.model_b_preds, xl))
    bcols = pd.concat([v.assign(league=k) for k, v in bres.items()])
    m = m.merge(bcols, on=["league", "fixture_id"], how="left")
    early = (m["d"] < kx.CUT).to_numpy()
    has_b = m["lam_b"].notna().to_numpy()

    base = kx.probs_frame(m["lam"], m["mu"], m["rho"])
    br_cur = kx.brier_rows(base, m)
    br_cal = kx.brier_rows(kx.calibrated(base), m)

    br_w = {}
    for w in kx.WEIGHTS:
        lam = np.where(has_b, w * m["lam_b"].fillna(0) + (1 - w) * m["lam"], m["lam"])
        mu = np.where(has_b, w * m["mu_b"].fillna(0) + (1 - w) * m["mu"], m["mu"])
        pf = kx.probs_frame(lam, mu, m["rho"])
        br_w[w] = (kx.brier_rows(pf, m), kx.brier_rows(kx.calibrated(pf), m), lam, mu)

    chosen = {}
    for lg in xl:
        e = (m["league"] == lg).to_numpy() & early
        scores = {w: br_w[w][0][e].mean() for w in kx.WEIGHTS}
        chosen[lg] = min(scores, key=scores.get)

    with Pool(len(xl)) as pool:
        rng_all = dict(pool.map(kx.range_all_pairs, [(lg, chosen[lg]) for lg in xl]))

    rows = []
    for lg in xl:
        sel = (m["league"] == lg).to_numpy()
        w = chosen[lg]
        lam_x, mu_x = br_w[w][2][sel], br_w[w][3][sel]
        cmin = float(min(m["lam"][sel].min(), m["mu"][sel].min()))
        cmax = float(max(m["lam"][sel].max(), m["mu"][sel].max()))
        xmin, xmax = float(min(lam_x.min(), mu_x.min())), float(max(lam_x.max(), mu_x.max()))
        a = rng_all[lg]
        late = sel & ~early
        d, lo, hi = kx.ci(br_w[w][1][late], br_cal[late])
        ok_bench = xmin >= cmin and xmax <= cmax
        ok_today = a[2] >= a[0] and a[3] <= a[1]
        holds = w > 0 and d < 0
        rows.append({"league": lg, "w": w, "late_xg_minus_cal": d, "ci_lo": lo, "ci_hi": hi, "holds": holds,
                     "bench_cur_min": cmin, "bench_cur_max": cmax, "bench_mix_min": xmin, "bench_mix_max": xmax,
                     "today_cur_min": a[0], "today_cur_max": a[1], "today_mix_min": a[2], "today_mix_max": a[3],
                     "range_not_worse": ok_bench and ok_today, "keep": holds and ok_bench and ok_today})
    dec = pd.DataFrame(rows)
    dec.round(6).to_csv(f"validation/razpredelenie_a_{TAG}.csv", index=False)
    keep = {r.league: r.w for r in dec.itertuples() if r.keep}

    def variant(k):
        out = br_cal.copy()
        for lg, w in k.items():
            s = (m["league"] == lg).to_numpy()
            out[s] = br_w[w][1][s]
        return out

    br_old, br_new = variant(OLD_KEEP), variant(keep)
    fin = {}
    for part, mask in (("ранна", early), ("късна", ~early)):
        fin[part] = {"cur": br_cur[mask].mean(), "cal": br_cal[mask].mean(), "old": br_old[mask].mean(),
                     "new": br_new[mask].mean(), "new_vs_old": kx.ci(br_new[mask], br_old[mask]),
                     "new_vs_cur": kx.ci(br_new[mask], br_cur[mask]), "n": int(mask.sum())}
    per_lg = []
    for lg in ["germany", "france"]:
        mask = (m["league"] == lg).to_numpy() & ~early
        per_lg.append((lg, int(mask.sum()), br_cal[mask].mean(), br_new[mask].mean(), kx.ci(br_new[mask], br_cal[mask])))
    write_md(dec, keep, fin, per_lg)


def write_md(dec, keep, fin, per_lg):
    L = [f"# Разпределение, ЧАСТ А - Германия/Франция обратно - {TAG}", "",
         "ZADACHA_RAZPREDELENIE.md, ЧАСТ А. Скрипт: `validation/razpredelenie_a_20260923.py` (импортира",
         "`kalibraciq_xg_20260923.py` - модел Б, изборът на w и калибрацията са същите). Сурови числа:",
         "`razpredelenie_a_20260923.csv`.", "",
         "**Какво беше сбъркано:** правилото „сместа в 0.3 - 3.5“ е абсолютно. При Германия сегашният модел",
         "стига 4.69, сместа с xG - 4.19: диапазонът се ПОДОБРЯВА, а лигата пак беше отрязана. Същото за",
         "Франция (3.68 → 3.24).", "",
         "**Поправено правило:** сместа влиза, ако НЕ влошава диапазона спрямо сегашния модел - максимумът",
         "не расте и минимумът не пада - и в мерилото (всички 730 дни), и за всички двойки отбори днес. Без",
         "абсолютен праг. Другите две условия остават: избрано w > 0 (ранна половина) и подобрение на",
         "КЪСНАТА половина спрямо само калибрация.", "",
         "| лига | w | късна: xG − калибрация (95% инт.) | мерило: сегашен → смес | днес: сегашен → смес | диапазонът не се влошава | xG влиза |",
         "|---|---|---|---|---|---|---|"]
    for r in dec.itertuples():
        L.append(f"| {r.league} | {r.w} | {r.late_xg_minus_cal:+.5f} [{r.ci_lo:+.5f}, {r.ci_hi:+.5f}] | "
                 f"{r.bench_cur_min:.2f}-{r.bench_cur_max:.2f} → {r.bench_mix_min:.2f}-{r.bench_mix_max:.2f} | "
                 f"{r.today_cur_min:.2f}-{r.today_cur_max:.2f} → {r.today_mix_min:.2f}-{r.today_mix_max:.2f} | "
                 f"{'да' if r.range_not_worse else 'НЕ'} | **{'да' if r.keep else 'не'}** |")
    L += ["", "Причини за „не“: italy - не се задържа на късната половина; portugal - w = 0 (xG не помага",
          "още на ранната половина), диапазонът е без значение.", "",
          f"**Влизат сега:** {', '.join(f'{k} (w={v})' for k, v in keep.items())}.", "",
          "## Резултат - късна половина (извън всеки избор)", "",
          "| вариант | Brier |", "|---|---|"]
    F = fin["късна"]
    L += [f"| сегашен (без калибрация) | {F['cur']:.5f} |", f"| само калибрация | {F['cal']:.5f} |",
          f"| калибрация + xG за england/spain/england2 (досега) | {F['old']:.5f} |",
          f"| калибрация + xG с поправеното правило (сега) | {F['new']:.5f} |", "",
          f"Мачове: {F['n']}. Сега − досега: {F['new_vs_old'][0]:+.5f} [{F['new_vs_old'][1]:+.5f}, {F['new_vs_old'][2]:+.5f}]; "
          f"сега − сегашен: {F['new_vs_cur'][0]:+.5f} [{F['new_vs_cur'][1]:+.5f}, {F['new_vs_cur'][2]:+.5f}].", "",
          "По лига, късна половина:", "", "| лига | мачове | само калибрация | калибрация + xG | разлика (95% инт.) |",
          "|---|---|---|---|---|"]
    for lg, n, a, b, c in per_lg:
        L.append(f"| {lg} | {n} | {a:.5f} | {b:.5f} | {c[0]:+.5f} [{c[1]:+.5f}, {c[2]:+.5f}] |")
    E = fin["ранна"]
    L += ["", f"За справка, ранна половина (тук е избрано w): досега {E['old']:.5f}, сега {E['new']:.5f}."]
    with open(f"validation/razpredelenie_a_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
