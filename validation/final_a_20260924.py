"""
validation/final_a_20260924.py - ZADACHA_FINAL.md, ЧАСТ А (24.09.2026).

"Двата отбора отбелязват" (btts) - последният самоуверен пазар: коефициент
на калибрация a = 0.772 (tri_a_20260923.md), не мърда при настройка на
атака/защита.

Моделът днес (живият, без калибрация): очакваните голове по мач от
tri_a_20260923_matches.csv (FT_FIT_SETTINGS + xG смес, 14-те лиги) и
tri_v_20260924_matches.csv (общият евро модел, трите турнира) - същите
11823 мача като мерилото backtest_full, седмично префитване. Матрица:
Поасон x Поасон + Dixon-Coles rho (razpredelenie_b_20260923.matrices).

1. ХИПОТЕЗА 1 (rho): наблюдавана честота на 0-0, 1-0, 0-1, 1-1 срещу
   модела, по лига.
2. ХИПОТЕЗА 2: остатъчна зависимост между "домакинът вкара" и "гостът
   вкара" по нива на очаквания сбор голове (шест равни групи), плюс
   калибрацията на двете поотделно.
3. ПОПРАВКА (избрана от 1-2): при мач с малко очаквани голове част f от
   вероятността на всеки резултат, в който някой отбор е с 0 гола (x-0,
   0-y, 0-0), се мести в (x+1, y+1) - същата голова разлика, и двата
   отбора вкарали. 1X2 не се променя (разликата в головете е същата).
   f = clip(f0 + f1 * ln((lam+mu)/2.6), 0, 0.9); f0, f1 - максимално
   правдоподобие на изхода btts, само РАННАТА половина (дата < 2025-09-23).
   Проверка - КЪСНАТА половина. За справка: същото, но f0, f1 от пълното
   правдоподобие на точния резултат.
4. Калибрацията, фитната наново (calibration_fit метод, ранна половина),
   върху модела с поправката - новите CALIBRATION_A.

Критерий на задачата: a за btts >= 0.90.
Изход: validation/final_a_20260924.md, .csv (по лига).
Употреба: venv/bin/python3 validation/final_a_20260924.py
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

import backtest_full as bf  # noqa: E402
import kalibraciq_xg_20260923 as kx  # noqa: E402
import razpredelenie_b_20260923 as rb  # noqa: E402

TAG = "20260924"
T0 = 2.6
GROUPS = ["1x2", "ou25", "btts", "team_total"]
GN = {"1x2": "1x2", "ou25": "над/под 2.5", "btts": "двата отбора", "team_total": "отборни голове"}


def live_frame():
    a = pd.read_csv("validation/tri_a_20260923_matches.csv")
    v = pd.read_csv("validation/tri_v_20260924_matches.csv")
    v = v.rename(columns={"lam_new": "lam", "mu_new": "mu", "rho_new": "rho"})
    cols = ["league", "fixture_id", "date", "hg", "ag", "lam", "mu", "rho"]
    a = a[~a.league.isin(v.league.unique())][cols]
    return pd.concat([a, v[cols]], ignore_index=True).sort_values(["league", "fixture_id"]).reset_index(drop=True)


def shift(pm, lam, mu, f0, f1):
    """= football_lib.score_dependence_adjust, векторизирано (N, G, G)."""
    f = np.clip(f0 + f1 * np.log((lam + mu) / T0), 0.0, 0.9)
    mv = np.zeros_like(pm)
    mv[:, 0, :] = pm[:, 0, :] * f[:, None]
    mv[:, 1:, 0] = pm[:, 1:, 0] * f[:, None]
    mv[:, -1, 0] = 0.0   # (x+1, y+1) извън матрицата - не се мести
    mv[:, 0, -1] = 0.0
    out = pm - mv
    out[:, 1:, 1:] += mv[:, :-1, :-1]
    return out


def corr_adjust(pm, lam, mu, f0, f1):
    """Отхвърленият вариант: пази P(домакинът вкарва) и P(гостът вкарва), добавя d към 0-0 и към
    блока „двата вкарват“, вади d от x-0 и 0-y; d = phi * sqrt(qh(1-qh)qa(1-qa)), phi = f0 + f1*ln(T/2.6)."""
    A = pm[:, 0, 0]
    B = pm[:, 0, 1:].sum(1)
    C = pm[:, 1:, 0].sum(1)
    D = pm[:, 1:, 1:].sum((1, 2))
    qh, qa = A + B, A + C
    d = (f0 + f1 * np.log((lam + mu) / T0)) * np.sqrt(qh * (1 - qh) * qa * (1 - qa))
    d = np.clip(d, -0.95 * np.minimum(A, D), 0.95 * np.minimum(B, C))
    out = pm.copy()
    out[:, 0, 0] *= (A + d) / A
    out[:, 0, 1:] *= ((B - d) / B)[:, None]
    out[:, 1:, 0] *= ((C - d) / C)[:, None]
    out[:, 1:, 1:] *= ((D + d) / D)[:, None, None]
    return out


def ytrue(m):
    return np.column_stack([[bf.outcomes(h, g)[c] for h, g in zip(m.hg, m.ag)] for c in bf.CODES]).astype(float)


def slope_a(p, y, mask):
    b = y[mask].mean()
    d = p[mask] - b
    return float((d * (y[mask] - b)).sum() / (d * d).sum())


def group_brier(P, Y, g):
    idx = [i for i, c in enumerate(bf.CODES) if bf.GROUPS[c] == g]
    return ((P.to_numpy()[:, idx] - Y[:, idx]) ** 2).mean(1)


def band_gap(p, y):
    """Средна |обещано - познато| по ленти от 10 пункта, претеглена с броя, в пункта."""
    band = np.minimum((p * 10).astype(int), 9)
    s = pd.DataFrame({"b": band, "p": p, "y": y}).groupby("b").agg(n=("y", "size"), p=("p", "mean"), y=("y", "mean"))
    return float((s["n"] * (s["p"] - s["y"]).abs()).sum() / s["n"].sum() * 100)


def main():
    m = live_frame()
    early = (pd.to_datetime(m.date) < kx.CUT).to_numpy()
    lam, mu, rho = m.lam.to_numpy(), m.mu.to_numpy(), m.rho.to_numpy()
    hg, ag = m.hg.to_numpy(), m.ag.to_numpy()
    pm0 = rb.matrices(lam, mu, rho, "poisson", 0)
    Y = ytrue(m)
    ib = bf.CODES.index("btts_yes")
    yb = Y[:, ib]

    # 1. клетките на Dixon-Coles по лига
    cells = []
    for lg, s in list(m.groupby("league")) + [("ALL", m)]:
        idx = s.index.to_numpy()
        r = {"league": lg, "n": len(s), "rho": float(s.rho.mean())}
        for i, j in [(0, 0), (1, 0), (0, 1), (1, 1)]:
            r[f"obs_{i}{j}"] = float(((s.hg == i) & (s.ag == j)).mean() * 100)
            r[f"mod_{i}{j}"] = float(pm0[idx, i, j].mean() * 100)
        cells.append(r)
    cells = pd.DataFrame(cells)

    # 2. поотделно и по нива
    ph1 = 1 - pm0[:, 0, :].sum(1)
    pa1 = 1 - pm0[:, :, 0].sum(1)
    pb = pm0[:, 1:, 1:].sum((1, 2))
    yh, ya = (hg >= 1).astype(float), (ag >= 1).astype(float)
    marg = {nm: (slope_a(p, y, early), slope_a(p, y, ~early), p.mean() * 100, y.mean() * 100)
            for nm, p, y in [("домакинът вкарва", ph1, yh), ("гостът вкарва", pa1, ya), ("двата отбора", pb, yb)]}
    T = lam + mu
    q = pd.qcut(T, 6)
    lev = pd.DataFrame({"q": q, "T": T, "yb": yb, "pb": pb, "yh": yh, "ph": ph1, "ya": ya, "pa": pa1,
                        "cov": (yh - ph1) * (ya - pa1)}).groupby("q", observed=True).agg(
        n=("yb", "size"), T=("T", "mean"), yb=("yb", "mean"), pb=("pb", "mean"), yh=("yh", "mean"), ph=("ph", "mean"),
        ya=("ya", "mean"), pa=("pa", "mean"), cov=("cov", "mean")).reset_index(drop=True)

    # 3. поправката
    def nll(p, full, fn=shift):
        pm = fn(pm0[early], lam[early], mu[early], p[0], p[1])
        if full:
            return -rb.ll_cells(pm, hg[early], ag[early]).sum()
        pp = np.clip(pm[:, 1:, 1:].sum((1, 2)), 1e-9, 1 - 1e-9)
        y = yb[early]
        return -(y * np.log(pp) + (1 - y) * np.log(1 - pp)).sum()

    fits = {}
    for nm, full in (("btts", False), ("резултат", True)):
        r = minimize(nll, [0.02, 0.0], args=(full,), method="Nelder-Mead", options={"xatol": 1e-5, "fatol": 1e-4})
        fits[nm] = (round(float(r.x[0]), 3), round(float(r.x[1]), 3))
    r = minimize(nll, [0.0, 0.0], args=(False, corr_adjust), method="Nelder-Mead", options={"xatol": 1e-5, "fatol": 1e-4})
    fit_corr = (round(float(r.x[0]), 3), round(float(r.x[1]), 3))
    P0 = rb.market_probs(pm0)
    variants = {"сега": P0}
    for nm, (a0, a1) in fits.items():
        variants[nm] = rb.market_probs(shift(pm0, lam, mu, a0, a1))
    variants["корелация"] = rb.market_probs(corr_adjust(pm0, lam, mu, *fit_corr))
    P1 = variants["btts"]
    res = {}
    for nm, P in variants.items():
        a_e, b_e = rb.fit_cal(P, Y, early)
        a_l, _ = rb.fit_cal(P, Y, ~early)
        res[nm] = {"a_e": a_e, "a_l": a_l, "b": b_e,
                   "gb": {g: (group_brier(P, Y, g)[early].mean(), group_brier(P, Y, g)[~early].mean()) for g in GROUPS},
                   "all": rb.brier_rows(P, Y), "gap_btts": band_gap(P["btts_yes"].to_numpy()[~early], yb[~early]),
                   "gap_ou": band_gap(P["over25"].to_numpy()[~early], Y[~early, bf.CODES.index("over25")])}
    ci_all = kx.ci(res["btts"]["all"][~early], res["сега"]["all"][~early])
    ci_btts = kx.ci(group_brier(P1, Y, "btts")[~early], group_brier(P0, Y, "btts")[~early])
    # 1x2 непроменен - проверка
    d1x2 = float(np.abs(P1[["home_win", "draw", "away_win"]].to_numpy() - P0[["home_win", "draw", "away_win"]].to_numpy()).max())

    # по лига, късна половина
    per = []
    for lg in bf.LEAGUES:
        sel = (m.league == lg).to_numpy()
        e, l_ = sel & early, sel & ~early
        per.append({"league": lg, "n_late": int(l_.sum()),
                    "a_btts_now_late": slope_a(P0["btts_yes"].to_numpy(), yb, l_),
                    "a_btts_new_late": slope_a(P1["btts_yes"].to_numpy(), yb, l_),
                    "btts_obs_late": yb[l_].mean() * 100, "btts_now_late": P0["btts_yes"].to_numpy()[l_].mean() * 100,
                    "btts_new_late": P1["btts_yes"].to_numpy()[l_].mean() * 100,
                    "brier_btts_diff_late": float((group_brier(P1, Y, "btts") - group_brier(P0, Y, "btts"))[l_].mean()),
                    "brier_all_diff_late": float((res["btts"]["all"] - res["сега"]["all"])[l_].mean()),
                    "brier_all_diff_early": float((res["btts"]["all"] - res["сега"]["all"])[e].mean())})
    per = pd.DataFrame(per)
    per.round(5).to_csv(f"validation/final_a_{TAG}.csv", index=False)
    write_md(cells, marg, lev, fits, res, ci_all, ci_btts, d1x2, per)


def write_md(cells, marg, lev, fits, res, ci_all, ci_btts, d1x2, per):
    f0, f1 = fits["btts"]
    A0, A1 = res["сега"], res["btts"]
    ok = A1["a_e"]["btts"] >= 0.90 and A1["a_l"]["btts"] >= 0.90
    al = cells[cells.league == "ALL"].iloc[0]
    L = [f"# ФИНАЛ, ЧАСТ А - „двата отбора отбелязват“ - {TAG}", "",
         "ZADACHA_FINAL.md, ЧАСТ А. Скрипт: `validation/final_a_20260924.py` (методът е в docstring-а).",
         "Сурови числа по лига: `final_a_20260924.csv`. Моделът = живият днес (свито темпо, xG смес, общ евро",
         "модел), 11823 мача, седмично префитване; ранна половина - до 23.09.2025, късна - след.", "",
         "## Хипотеза 1: rho (Dixon-Coles) не си върши работата - ОТХВЪРЛЕНА", "",
         "Четирите резултата, които rho коригира, общо за всички лиги (% от мачовете):", "",
         "| резултат | реално | модел |", "|---|---|---|"]
    for i, j in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        L.append(f"| {i}-{j} | {al[f'obs_{i}{j}']:.1f} | {al[f'mod_{i}{j}']:.1f} |")
    L += ["", "Моделът НЕ ги подценява - дава малко повече 0-0 и 0-1, отколкото реално има, а 1-1 почти точно.",
          "По лига разликите са в двете посоки без обща посока (виж таблицата долу). В четирите лиги с модела с",
          "контузиите (england, germany, spain, france) rho е 0 - там rho изобщо не се фитва; но и там картината е",
          "смесена (spain: 0-0 реално 4.5% срещу 7.8%, 1-1 15.3% срещу 11.6%; germany: обратното при 1-0).", "",
          "| лига | 0-0 реално / модел | 1-0 | 0-1 | 1-1 | rho |", "|---|---|---|---|---|---|"]
    for r in cells.itertuples():
        if r.league == "ALL":
            continue
        L.append(f"| {r.league} | {r.obs_00:.1f} / {r.mod_00:.1f} | {r.obs_10:.1f} / {r.mod_10:.1f} | "
                 f"{r.obs_01:.1f} / {r.mod_01:.1f} | {r.obs_11:.1f} / {r.mod_11:.1f} | {r.rho:+.2f} |")
    L += ["", "## Хипотеза 2: зависимост, която се появява при определени нива на головете - ПОТВЪРДЕНА", "",
          "Поотделно „домакинът вкарва“ и „гостът вкарва“ са калибрирани (a около 1), а заедно - не:", "",
          "| | a ранна | a късна | модел % | реално % |", "|---|---|---|---|---|"]
    for nm, (ae, al_, pm_, ym) in marg.items():
        L.append(f"| {nm} | {ae:.2f} | {al_:.2f} | {pm_:.1f} | {ym:.1f} |")
    L += ["", "По нива на очаквания сбор голове (шест равни групи, всички мачове):", "",
          "| очакван сбор | мачове | двата вкарват: реално / модел | домакин вкарва: реално / модел | гост вкарва: реално / модел |",
          "|---|---|---|---|---|"]
    for r in lev.itertuples():
        L.append(f"| {r.T:.1f} | {r.n} | {r.yb * 100:.0f} / {r.pb * 100:.0f} | {r.yh * 100:.0f} / {r.ph * 100:.0f} | "
                 f"{r.ya * 100:.0f} / {r.pa * 100:.0f} |")
    L += ["", "В мачовете с малко очаквани голове двата отбора вкарват с ~5 пункта по-често, отколкото моделът допуска;",
          "при много очаквани голове - точно. Моделът разпилява „двата вкарват“ между 43% и 58%, реалността - между",
          "48% и 58%. Оттам е самоувереността. По клетки: при малко очаквани голове реално има повече 2-1, 1-2, 2-2 и",
          "по-малко 0-0, 1-0, 0-1, 2-0 - а победител/равен (1X2) е точен. Тоест в тези мачове по-често има „отговор“",
          "на гола, без да се мени кой печели.", "",
          "## Поправката", "",
          "Част f от вероятността на всеки резултат с нула за някой отбор (x-0, 0-y, 0-0) се мести в (x+1, y+1) -",
          "същата голова разлика, и двата отбора вкарали. 1X2 не се мени (проверено: макс. разлика "
          f"{d1x2:.1e}).", f"f = {f0:.3f} {f1:+.3f} x ln(очакван сбор / 2.6), не по-малко от 0: при сбор 1.7 f = "
          f"{max(0, f0 + f1 * np.log(1.7 / T0)):.2f}, при 2.6 - {max(0, f0):.2f}, над ~{T0 * np.exp(-f0 / f1):.1f} - 0.",
          "Двата параметъра - от ранната половина (правдоподобие на изхода „двата вкарват“).", "",
          "## Критерий: коефициентът на калибрация (a)", "",
          "| | 1x2 | над/под 2.5 | двата отбора | отборни голове |", "|---|---|---|---|---|"]
    for lab, R, k in (("сега, ранна", A0, "a_e"), ("сега, късна", A0, "a_l"), ("с поправката, ранна", A1, "a_e"),
                      ("с поправката, късна", A1, "a_l")):
        L.append(f"| {lab} | {R[k]['1x2']:.2f} | {R[k]['ou25']:.2f} | {R[k]['btts']:.2f} | {R[k]['team_total']:.2f} |")
    L += ["", f"**Критерий (a за двата отбора ≥ 0.90): {'ИЗПЪЛНЕН' if ok else 'НЕ е изпълнен'}** - "
          f"{A0['a_e']['btts']:.2f} → {A1['a_e']['btts']:.2f} на ранната, {A0['a_l']['btts']:.2f} → {A1['a_l']['btts']:.2f}"
          " на късната (невиждана при избора).", "",
          f"Колко бърка „двата отбора“ (късна, средна разлика обещано − познато по ленти от 10 пункта): "
          f"{A0['gap_btts']:.1f} → {A1['gap_btts']:.1f} пункта. Над/под 2.5: {A0['gap_ou']:.1f} → {A1['gap_ou']:.1f}.", "",
          "Brier на късната половина по група (по-малко = по-добре; разлика с поправката):", "",
          "| група | разлика ранна | разлика късна |", "|---|---|---|"]
    for g in GROUPS:
        L.append(f"| {GN[g]} | {A1['gb'][g][0] - A0['gb'][g][0]:+.4f} | {A1['gb'][g][1] - A0['gb'][g][1]:+.4f} |")
    L += ["", f"Общо (11-те изхода), късна: {ci_all[0]:+.4f} [{ci_all[1]:+.4f}, {ci_all[2]:+.4f}] - значимо по-добре; само",
          f"„двата отбора“: {ci_btts[0]:+.4f} [{ci_btts[1]:+.4f}, {ci_btts[2]:+.4f}].", "",
          "По лига (късна половина): коефициент за „двата отбора“ сега → с поправката, и дял „двата вкарват“:", "",
          "| лига | мачове | a сега → нов | реално / сега / нов % | Brier общо (късна) |", "|---|---|---|---|---|"]
    for r in per.itertuples():
        L.append(f"| {r.league} | {r.n_late} | {r.a_btts_now_late:.2f} → {r.a_btts_new_late:.2f} | {r.btts_obs_late:.0f} / "
                 f"{r.btts_now_late:.0f} / {r.btts_new_late:.0f} | {r.brier_all_diff_late:+.4f} |")
    better = int((per.brier_all_diff_late < 0).sum())
    rf = fits["резултат"]
    Ar = res["резултат"]
    L += ["", f"Общият Brier на късната е по-добър в {better} от 17 лиги. По отделни лиги коефициентът скача (малки извадки,",
          "~300 мача) - критерият е за общия.", "",
          f"За справка: ако f0, f1 се фитнат от точния резултат (всички клетки), излизат по-малки ({rf[0]:.3f}, {rf[1]:+.3f})",
          f"и a за двата отбора стига само {Ar['a_e']['btts']:.2f} / {Ar['a_l']['btts']:.2f} (ранна/късна) - точният резултат",
          "тежи повече на клетките с много голове, където корекция не е нужна. Избрана е версията по изхода.", "",
          "## Калибрацията, фитната наново (ранна половина) - новите CALIBRATION_A", "",
          f"1x2 {A1['a_e']['1x2']:.3f}, над/под {A1['a_e']['ou25']:.3f}, двата отбора {A1['a_e']['btts']:.3f}, "
          f"отборни голове {A1['a_e']['team_total']:.3f} (b - без промяна: същите честоти на ранната половина).",
          "Корнерите (0.855) - отделен модел, не се пипат тук.", "",
          "## Какво е изключено", "",
          "- rho: четирите клетки не са подценени (виж хипотеза 1) - по-силно rho би влошило 0-0 и 0-1.",
          "- обща корелация между головете: вече мерена, нула (tri_a); тук зависимостта е само при малко голове.",
          "- атака/защита: мерено в tri_a, a не минава 0.77 при никоя настройка.",
          "- вариант, който пази поотделните вероятности „вкарва“ и мести и 0-0 нагоре (класическа корелация на",
          f"  двата изхода): a за двата отбора {res['корелация']['a_e']['btts']:.2f} / {res['корелация']['a_l']['btts']:.2f}"
          f" (ранна/късна), но добавя равни - 1X2 на късната {res['корелация']['gb']['1x2'][1] - A0['gb']['1x2'][1]:+.4f}"
          " (по-зле) - отхвърлен."]
    with open(f"validation/final_a_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
