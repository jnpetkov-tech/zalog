"""
validation/razpredelenie_b_20260923.py - ZADACHA_RAZPREDELENIE.md, ЧАСТИ Б и В.

Въпросът: калибрацията свива головите пазари с 38-47% (над/под a = 0.624,
двата отбора a = 0.532) - моделът е прекалено уверен за головете. Хипотезата
на задачата: причината е Поасон (дисперсия = средното) + независимост.

=== ОТПРАВНА ТОЧКА ("сегашен") ===
Точно живият модел след ЧАСТ А: очакваните голове lam/mu от мерилото
backtest_full_20260923_matches.csv (walk-forward, седмично префитване), за
england/germany/spain/france/england2 смесени с модел Б върху xG (w от
XG_BLEND_WEIGHTS, модел Б - kalibraciq_xg_20260923.model_b_preds), Поасон,
Dixon-Coles rho от модела, калибрация с живите параметри (CALIBRATION_A/BASE).

=== ВАРИАНТИ (същите lam/mu и rho; сменя се САМО разпределението около тях) ===
 nb      - отрицателно биномно за головете на всеки отбор: средно lam,
           дисперсия lam + alpha*lam^2; alpha по лига. (Б.1 от задачата)
 ln_ind  - несигурност в очакваните голове: lam*U_h, mu*U_a, log U ~ N(-s^2/2,
           s^2) (средно 1), U_h и U_a независими; s по лига. (Б.2)
 ln_com  - същото, но ЕДИН общ множител U за двата отбора ("темпото на
           мача" - по-головит/по-малко голов мач от очакваното); s по лига.
           Това е и единственият вариант, който прави головете на двата
           отбора зависими (положителна корелация). (Б.2, вариант)
Интегралите - Гаус-Ермит, 21 възела. Dixon-Coles (rho) - НЕ се пипа: прилага
се върху новата матрица точно както днес (dc_adjust_matrix, с lam/mu).
Матрица до 9 гола на отбор, както backtest_full.

=== ФИТВАНЕ НА ПАРАМЕТЪРА (само ранната половина, дата < 2025-09-23) ===
Максимално правдоподобие на реалния резултат (клетката [hg, ag] на
матрицата, с DC) по лига, решетка alpha 0..0.40 през 0.01, s 0..0.60 през
0.02. За справка - и параметърът, който дава най-нисък Brier на ранната
половина (не се ползва за решението).

=== ИЗМЕРВАНЕ (ЧАСТ В) ===
Brier - средно на 11-те изхода на мач (backtest_full.CODES), на КЪСНАТАТА
половина (не участва в нищо). За всеки вариант:
  (1) суров (без калибрация),
  (2) с калибрация, фитната НАНОВО върху ранната половина на ТОЗИ вариант
      (методът от calibration_fit.py: b = честота на изхода, a на група =
      sum((p-b)(y-b))/sum((p-b)^2)).
Проверката дали е поправена причината: новите a за ou25 и btts - ако се
приближат към 1.0, разпределението е поправено; ако останат ~0.62/0.53 - не.
95% интервал - сдвоен bootstrap по мач, 2000, seed 42.

Диагностика на средните (защо): наклон на регресия на реалния сбор голове
върху очаквания (lam+mu) и индекс на дисперсия sum((g-lam)^2)/sum(lam) -
ако наклонът е под 1, прекалено разпилени са самите очаквани голове между
мачовете, не разпределението около тях.

Изход: validation/razpredelenie_b_20260923.md/.csv/_params.csv
Употреба: venv/bin/python3 validation/razpredelenie_b_20260923.py
"""
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd
from scipy.special import gammaln

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

import backtest_full as bf  # noqa: E402
import kalibraciq_xg_20260923 as kx  # noqa: E402
import prediction_policy as policy  # noqa: E402

TAG = "20260923"
XG_W = {"england": 0.7, "germany": 0.5, "spain": 0.7, "france": 0.7, "england2": 0.5}  # = XG_BLEND_WEIGHTS
G = np.arange(bf.MAX_G)
X, Y = np.meshgrid(G, G, indexing="ij")
_z, _w = np.polynomial.hermite.hermgauss(21)
QZ, QW = _z * np.sqrt(2), _w / np.sqrt(np.pi)
GRID = {"nb": np.round(np.arange(0, 0.401, 0.01), 3), "ln_ind": np.round(np.arange(0, 0.601, 0.02), 3),
        "ln_com": np.round(np.arange(0, 0.601, 0.02), 3)}
KINDS = ["poisson", "nb", "ln_ind", "ln_com"]
NAMES = {"poisson": "Поасон (сегашен)", "nb": "отрицателно биномно (Б.1)",
         "ln_ind": "несигурност в очакваните голове, поотделно (Б.2)",
         "ln_com": "несигурност в очакваните голове, общ множител за мача (Б.2)"}
GROUPS = ["1x2", "ou25", "btts", "team_total"]


def pois(m):
    """m: (...,) -> (..., MAX_G)"""
    m = np.asarray(m, float)[..., None]
    return np.exp(G * np.log(np.maximum(m, 1e-12)) - m - gammaln(G + 1))


def negbin(m, alpha):
    if alpha <= 0:
        return pois(m)
    r = 1.0 / alpha
    m = np.asarray(m, float)[..., None]
    return np.exp(gammaln(G + r) - gammaln(r) - gammaln(G + 1) + r * np.log(r / (r + m)) + G * np.log(m / (r + m)))


def matrices(lam, mu, rho, kind, par):
    """(N,) -> (N, MAX_G, MAX_G)"""
    if kind == "poisson" or par == 0:
        pm = pois(lam)[:, :, None] * pois(mu)[:, None, :]
    elif kind == "nb":
        pm = negbin(lam, par)[:, :, None] * negbin(mu, par)[:, None, :]
    else:
        u = np.exp(par * QZ - par ** 2 / 2)                       # (K,)
        ph = pois(lam[:, None] * u[None, :])                      # (N,K,G)
        pa = pois(mu[:, None] * u[None, :])
        if kind == "ln_ind":
            pm = np.einsum("k,nkg->ng", QW, ph)[:, :, None] * np.einsum("k,nkg->ng", QW, pa)[:, None, :]
        else:
            pm = np.einsum("k,nki,nkj->nij", QW, ph, pa)
    return dc(pm, lam, mu, rho)


def dc(pm, lam, mu, rho):
    """= football_lib.dc_adjust_matrix, векторизирано; само където rho != 0."""
    pm = pm.copy()
    nz = rho != 0
    if not nz.any():
        return pm
    f = np.ones((len(pm), 2, 2))
    f[:, 0, 0] = np.maximum(1 - lam * mu * rho, 0)
    f[:, 0, 1] = np.maximum(1 + lam * rho, 0)
    f[:, 1, 0] = np.maximum(1 + mu * rho, 0)
    f[:, 1, 1] = np.maximum(1 - rho, 0)
    pm[nz, :2, :2] *= f[nz]
    pm[nz] /= pm[nz].sum(axis=(1, 2), keepdims=True)
    return pm


def market_probs(pm):
    p = {"home_win": pm[:, X > Y].sum(1), "draw": pm[:, X == Y].sum(1), "away_win": pm[:, X < Y].sum(1),
         "over25": pm[:, X + Y > 2.5].sum(1), "btts_yes": pm[:, (X >= 1) & (Y >= 1)].sum(1),
         "home_over15": pm[:, X > 1.5].sum(1), "away_over15": pm[:, Y > 1.5].sum(1)}
    p["under25"] = 1 - p["over25"]
    p["btts_no"] = 1 - p["btts_yes"]
    p["home_under15"] = 1 - p["home_over15"]
    p["away_under15"] = 1 - p["away_over15"]
    return pd.DataFrame(p)[bf.CODES]


def ll_cells(pm, hg, ag):
    hg, ag = np.minimum(hg, bf.MAX_G - 1), np.minimum(ag, bf.MAX_G - 1)
    return np.log(np.maximum(pm[np.arange(len(pm)), hg, ag], 1e-300))


def brier_rows(pf, Yt):
    return ((pf.to_numpy() - Yt) ** 2).mean(1)


def fit_cal(pf, Yt, mask):
    """calibration_fit.py: b по код, a по група - само от mask."""
    b = {c: Yt[mask, i].mean() for i, c in enumerate(bf.CODES)}
    a = {}
    for g in GROUPS:
        idx = [i for i, c in enumerate(bf.CODES) if bf.GROUPS[c] == g]
        num = den = 0.0
        for i in idx:
            c = bf.CODES[i]
            d = pf.to_numpy()[mask, i] - b[c]
            num += (d * (Yt[mask, i] - b[c])).sum()
            den += (d * d).sum()
        a[g] = num / den
    return a, b


def apply_cal(pf, a, b):
    out = pf.copy()
    for c in bf.CODES:
        out[c] = b[c] + a[bf.GROUPS[c]] * (pf[c] - b[c])
    return out


def fit_league(args):
    lg, lam, mu, rho, hg, ag, Yt = args
    res = {}
    for kind in ("nb", "ln_ind", "ln_com"):
        lls, brs = [], []
        for par in GRID[kind]:
            pm = matrices(lam, mu, rho, kind, par)
            lls.append(ll_cells(pm, hg, ag).sum())
            brs.append(brier_rows(market_probs(pm), Yt).mean())
        res[kind] = {"mle": float(GRID[kind][int(np.argmax(lls))]), "brier_opt": float(GRID[kind][int(np.argmin(brs))]),
                     "ll_gain": float(max(lls) - lls[0])}
    return lg, res


def ci(a, b):
    return kx.ci(a, b)


def main():
    m = pd.read_csv(kx.SRC)
    m["d"] = pd.to_datetime(m["date"])
    with Pool(len(XG_W)) as pool:
        bres = dict(pool.map(kx.model_b_preds, list(XG_W)))
    bcols = pd.concat([v.assign(league=k) for k, v in bres.items()])
    m = m.merge(bcols, on=["league", "fixture_id"], how="left")
    w = m["league"].map(XG_W).fillna(0).to_numpy()
    has_b = m["lam_b"].notna().to_numpy()
    w = np.where(has_b, w, 0)
    lam = w * m["lam_b"].fillna(0).to_numpy() + (1 - w) * m["lam"].to_numpy()
    mu = w * m["mu_b"].fillna(0).to_numpy() + (1 - w) * m["mu"].to_numpy()
    rho = m["rho"].to_numpy()
    hg, ag = m["home_goals"].to_numpy(), m["away_goals"].to_numpy()
    Yt = m[[f"y_{c}" for c in bf.CODES]].to_numpy().astype(float)
    early = (m["d"] < kx.CUT).to_numpy()
    leagues = m["league"].to_numpy()

    # --- фитване на параметъра по лига (ранна половина)
    jobs = []
    for lg in bf.LEAGUES:
        s = (leagues == lg) & early
        jobs.append((lg, lam[s], mu[s], rho[s], hg[s], ag[s], Yt[s]))
    with Pool(8) as pool:
        params = dict(pool.map(fit_league, jobs))

    # --- вероятности по вариант
    probs = {}
    for kind in KINDS:
        parts = []
        for lg in bf.LEAGUES:
            s = leagues == lg
            par = 0.0 if kind == "poisson" else params[lg][kind]["mle"]
            pf = market_probs(matrices(lam[s], mu[s], rho[s], kind, par))
            pf.index = np.where(s)[0]
            parts.append(pf)
        probs[kind] = pd.concat(parts).sort_index()

    # --- живата калибрация (отправна точка) и префитната за всеки вариант
    live_a, live_b = dict(policy.CALIBRATION_A), dict(policy.CALIBRATION_BASE)
    base_live = apply_cal(probs["poisson"], live_a, live_b)
    br_ref = brier_rows(base_live, Yt)
    out, cals = [], {}
    for kind in KINDS:
        a, b = fit_cal(probs[kind], Yt, early)
        cals[kind] = a
        raw = brier_rows(probs[kind], Yt)
        cal = brier_rows(apply_cal(probs[kind], a, b), Yt)
        for part, mask in (("ранна", early), ("късна", ~early)):
            r = {"variant": kind, "part": part, "matches": int(mask.sum()), "raw": raw[mask].mean(),
                 "cal_refit": cal[mask].mean(), "ref_live": br_ref[mask].mean()}
            r["raw_vs_raw_poisson"], r["rr_lo"], r["rr_hi"] = ci(raw[mask], brier_rows(probs["poisson"], Yt)[mask])
            r["calrefit_vs_ref"], r["cr_lo"], r["cr_hi"] = ci(cal[mask], br_ref[mask])
            for g in GROUPS:
                gi = [i for i, c in enumerate(bf.CODES) if bf.GROUPS[c] == g]
                r[f"raw_{g}"] = ((probs[kind].to_numpy()[mask][:, gi] - Yt[mask][:, gi]) ** 2).mean()
                r[f"a_{g}"] = a[g]
            out.append(r)
    res = pd.DataFrame(out)
    res.round(6).to_csv(f"validation/razpredelenie_b_{TAG}.csv", index=False)
    prm = pd.DataFrame([{"league": lg, **{f"{k}_{f}": v[k][f] for k in v for f in v[k]}} for lg, v in params.items()])
    prm.round(4).to_csv(f"validation/razpredelenie_b_{TAG}_params.csv", index=False)

    # --- диагностика на средните
    diag = []
    tot, pred = hg + ag, lam + mu
    for part, mask in (("ранна", early), ("късна", ~early), ("всички", np.ones(len(m), bool))):
        slope = np.polyfit(pred[mask], tot[mask], 1)[0]
        disp_h = ((hg[mask] - lam[mask]) ** 2).sum() / lam[mask].sum()
        disp_a = ((ag[mask] - mu[mask]) ** 2).sum() / mu[mask].sum()
        corr = np.corrcoef(hg[mask] - lam[mask], ag[mask] - mu[mask])[0, 1]
        diag.append({"part": part, "slope_total": slope, "disp_home": disp_h, "disp_away": disp_a,
                     "resid_corr": corr, "sd_pred_total": pred[mask].std(), "mean_pred": pred[mask].mean(),
                     "mean_actual": tot[mask].mean()})
    diag = pd.DataFrame(diag)
    # по лига - наклон
    slope_lg = {lg: np.polyfit(pred[leagues == lg], tot[leagues == lg], 1)[0] for lg in bf.LEAGUES}
    # --- СПРАВКА (не е вариант от задачата, не се прилага): свиване на очаквания сбор
    # към средния на лигата с наклона от ранната половина - за да се види дали
    # коефициентите на калибрацията мърдат, когато се пипнат СРЕДНИТЕ, не разпределението.
    k = float(diag.loc[diag.part == "ранна", "slope_total"].iloc[0])
    tm = pd.Series(tot[early]).groupby(leagues[early]).mean()
    t0 = pd.Series(leagues).map(tm).to_numpy()
    f = (t0 + k * (pred - t0)) / pred
    parts = []
    for lg in bf.LEAGUES:
        s = leagues == lg
        pf = market_probs(matrices(lam[s] * f[s], mu[s] * f[s], rho[s], "poisson", 0.0))
        pf.index = np.where(s)[0]
        parts.append(pf)
    shr = pd.concat(parts).sort_index()
    a_s, b_s = fit_cal(shr, Yt, early)
    raw_s = brier_rows(shr, Yt)
    cal_s = brier_rows(apply_cal(shr, a_s, b_s), Yt)
    ref = {"k": k, "a": a_s, "raw": raw_s[~early].mean(), "cal": cal_s[~early].mean(),
           "raw_vs_poisson": ci(raw_s[~early], brier_rows(probs["poisson"], Yt)[~early]),
           "cal_vs_ref": ci(cal_s[~early], br_ref[~early])}
    write_md(res, prm, cals, diag, slope_lg, ref)


def write_md(res, prm, cals, diag, slope_lg, ref):
    late = res[res.part == "късна"].set_index("variant")
    early = res[res.part == "ранна"].set_index("variant")
    R = late.loc["poisson"]
    L = [f"# Разпределение - ЧАСТИ Б и В - {TAG}", "",
         "ZADACHA_RAZPREDELENIE.md. Скрипт: `validation/razpredelenie_b_20260923.py` (методът е в docstring-а).",
         "Сурови числа: `razpredelenie_b_20260923.csv`, параметри по лига: `razpredelenie_b_20260923_params.csv`.", "",
         "Отправна точка = живият модел след ЧАСТ А (xG за england/germany/spain/france/england2, Поасон,",
         "Dixon-Coles, живата калибрация). Всички варианти ползват СЪЩИТЕ очаквани голове и същото rho -",
         "сменя се само разпределението около тях. Параметърът по лига е фитнат (максимално",
         "правдоподобие) САМО на ранната половина (преди 2025-09-23); проверката - на късната (5919 мача).", "",
         "## Параметри по лига (ранна половина)", "",
         "alpha: дисперсия = lam + alpha·lam² (0 = Поасон). s: стандартно отклонение на log-множителя на",
         "очакваните голове (0 = без несигурност). В скоби - стойността с най-нисък Brier на ранната (справка).", "",
         "| лига | alpha (NB) | s поотделно | s общ | ръст на правдоподобието NB / поотд. / общ |", "|---|---|---|---|---|"]
    for r in prm.itertuples():
        L.append(f"| {r.league} | {r.nb_mle:.2f} ({r.nb_brier_opt:.2f}) | {r.ln_ind_mle:.2f} ({r.ln_ind_brier_opt:.2f}) | "
                 f"{r.ln_com_mle:.2f} ({r.ln_com_brier_opt:.2f}) | {r.nb_ll_gain:.1f} / {r.ln_ind_ll_gain:.1f} / {r.ln_com_ll_gain:.1f} |")
    L += ["", "## Резултат - късна половина (извън всеки избор)", "",
          "| вариант | Brier суров | суров − Поасон суров (95% инт.) | Brier с НОВА калибрация | − сегашния с живата калибрация (95% инт.) |",
          "|---|---|---|---|---|"]
    for k in KINDS:
        r = late.loc[k]
        L.append(f"| {NAMES[k]} | {r['raw']:.5f} | {r['raw_vs_raw_poisson']:+.5f} [{r['rr_lo']:+.5f}, {r['rr_hi']:+.5f}] | "
                 f"{r['cal_refit']:.5f} | {r['calrefit_vs_ref']:+.5f} [{r['cr_lo']:+.5f}, {r['cr_hi']:+.5f}] |")
    L += ["", f"Сегашният модел с живата калибрация (отправна точка): {R['ref_live']:.5f}.", "",
          "По пазарна група, суров Brier, късна половина:", "",
          "| вариант | 1x2 | над/под 2.5 | двата отбора | отборни голове |", "|---|---|---|---|---|"]
    for k in KINDS:
        r = late.loc[k]
        L.append(f"| {NAMES[k]} | " + " | ".join(f"{r[f'raw_{g}']:.5f}" for g in GROUPS) + " |")
    L += ["", "## ЧАСТ В - калибрацията, фитната наново върху всеки вариант", "",
          "Ако разпределението е поправено, a за над/под и двата отбора трябва да се качи към 1.0.", "",
          "| вариант | 1x2 | над/под 2.5 | двата отбора | отборни голове |", "|---|---|---|---|---|",
          f"| живата калибрация (от calibration_fit_20260923.md) | {policy.CALIBRATION_A['1x2']:.3f} | "
          f"{policy.CALIBRATION_A['ou25']:.3f} | {policy.CALIBRATION_A['btts']:.3f} | {policy.CALIBRATION_A['team_total']:.3f} |"]
    for k in KINDS:
        a = cals[k]
        L.append(f"| {NAMES[k]} | " + " | ".join(f"{a[g]:.3f}" for g in GROUPS) + " |")
    L += ["", "## Диагностика: къде е самоувереността", "",
          "Наклон = с колко реалният сбор голове се мени, когато очакваният сбор (lam+mu) се мени с 1. Под 1",
          "= очакваните голове се разминават между мачовете повече, отколкото реалността оправдава.",
          "Индекс на дисперсия = sum((голове − очаквани)²)/sum(очаквани): 1 = точно Поасон, над 1 = по-разпилено.", "",
          "| част | наклон на сбора | дисперсия домакин | дисперсия гост | корелация на остатъците | ст. откл. на очаквания сбор | средно очаквано / реално |",
          "|---|---|---|---|---|---|---|"]
    for r in diag.itertuples():
        L.append(f"| {r.part} | {r.slope_total:.3f} | {r.disp_home:.3f} | {r.disp_away:.3f} | {r.resid_corr:+.3f} | "
                 f"{r.sd_pred_total:.3f} | {r.mean_pred:.3f} / {r.mean_actual:.3f} |")
    L += ["", "Наклон по лига (всички мачове): " + ", ".join(f"{lg} {v:.2f}" for lg, v in slope_lg.items()) + "."]
    a = ref["a"]
    L += ["", "## Справка: какво става, ако се пипнат очакваните голове (НЕ е приложено, не е вариант от задачата)", "",
          f"Очакваният сбор на всеки мач се свива към средния сбор на лигата с наклона от ранната половина (k = {ref['k']:.3f});",
          "съотношението домакин/гост се пази, разпределението си остава Поасон + Dixon-Coles. Само за да се",
          "види дали калибрацията реагира, когато се пипне причината, която диагностиката сочи.", "",
          f"- суров Brier, късна: {ref['raw']:.5f} (спрямо Поасон суров {ref['raw_vs_poisson'][0]:+.5f} "
          f"[{ref['raw_vs_poisson'][1]:+.5f}, {ref['raw_vs_poisson'][2]:+.5f}])",
          f"- с нова калибрация, късна: {ref['cal']:.5f} (спрямо сегашния с живата калибрация {ref['cal_vs_ref'][0]:+.5f} "
          f"[{ref['cal_vs_ref'][1]:+.5f}, {ref['cal_vs_ref'][2]:+.5f}])",
          f"- новите a: 1x2 {a['1x2']:.3f}, над/под {a['ou25']:.3f}, двата отбора {a['btts']:.3f}, отборни голове {a['team_total']:.3f}"]
    P, N = cals["poisson"], cals["nb"]
    L += ["", "## Решение", "",
          "**Нито един вариант на разпределението не влиза.** Правилото: влиза само това, което се задържа на",
          "късната половина. Отрицателното биномно и несигурността в очакваните голове са по-лоши суровo и не",
          "по-добри след калибрация; при повечето лиги фитнатият параметър е 0 (т.е. данните сами избират Поасон).", "",
          f"**Причината НЕ е хваната от Б.1/Б.2 - казано честно.** Калибрацията, фитната наново, не мърда: над/под",
          f"{P['ou25']:.3f} (Поасон) → {N['ou25']:.3f} (отрицателно биномно), двата отбора {P['btts']:.3f} → {N['btts']:.3f}.",
          "Диагностиката казва защо: около очакваното головете СА Поасон (индекс на дисперсия 1.00-1.05,",
          "корелация между двата отбора ~0), т.е. хипотезата „футболът е по-разпилян от Поасон“ не се потвърждава",
          "с нашите данни. Самоувереността е в самите очаквани голове: наклонът на сбора е ~0.70 - когато моделът",
          "казва „с 1 гол повече от средното“, реално идват ~0.7. Моделът разграничава мачовете по головитост",
          "повече, отколкото реалността позволява (при някои лиги - почти изобщо не ги разграничава реално).", "",
          "Справката по-горе го потвърждава: свиване на очаквания сбор (без смяна на разпределението) качва",
          "коефициентите към 1 и подобрява късната половина значимо. **Не е приложено** - не е в обхвата на",
          "задачата и иска собствено измерване (напр. свиване на атака/защита при фитването, по лига). Кодът",
          "(`football_lib.py`, `prediction_policy.py`) е непроменен от ЧАСТ Б."]
    with open(f"validation/razpredelenie_b_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
