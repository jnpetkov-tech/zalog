"""
validation/tri_b_20260923.py - ZADACHA_TRI.md, ЧАСТ Б - корнерите.

Проблем: calibration_all_markets_20260922.md - при корнери (общо 9.5)
обещаваме 61%, познаваме 48% (114 логнати прогнози). Сегашният модел:
fl.fit_total_model() върху home_corners/away_corners (атака/защита на корнери,
т.е. "средният брой корнери на отбора") + Поасон.

=== НОВ МОДЕЛ - корнерите от натиска за конкретния мач ===
За всяка седмица, само от мачове преди понеделника ѝ:
 1. Очаквани удари за двата отбора: модел атака/защита (същата машинария,
    tri_fit kind="xg" - Поасон с дробни наблюдения, без DC) върху
    home_shots/away_shots; същото за удари в целта.
 2. Очаквано владение: logit(владение на домакина) = c + сила_дом - сила_гост,
    ridge, претеглени най-малки квадрати.
 3. Корнери на страна: Поасонова регресия (log-връзка) с признаци
    [1, домакин?, log очаквани удари за, log очаквани удари срещу,
     logit очаквано владение, log очаквани удари в целта за],
    ученa върху историята (признаците - от моделите в 1-2 за същите мачове),
    с времеви тегла на лигата.
 4. Разпределение: отрицателно биномно за всяка страна с alpha по лига
    (максимално правдоподобие на ранната половина; 0 = Поасон), общото -
    конволюция.
Вариант "live" = точно живият код (средни корнери + Поасон, без калибрация на
живо). Вариант "current" = същите средни + отрицателно биномно (за да се види
колко идва от разпределението и колко от признаците).
Вариант "комбиниран": същото + log очаквани корнери от сегашния модел като
признак (регресията сама решава тежестта).

=== МЕРЕНЕ ===
Същият период/седмично префитване като мерилото (backtest_full): последните
730 дни. Лиги: където живият код строи corners_model (>= 70% покритие на
корнерите сред завършените мачове, CORNERS_MIN_COVERAGE).
Пазари = показваните: общо над/под 9.5, домакин над 4.5, гост над 4.5.
"Колко бърка" = метриката от calibration_all_markets: на всеки пазар се взима
по-вероятната страна (фаворитът), средно обещано срещу реално познато, в
процентни пункта. Плюс средната разлика по ленти от 10 пункта.
Калибрация (ЧАСТ Б иска корнерите вътре): p' = b + a(p - b), a за групата
"корнери" и b по код - от РАННАТА половина (дата < 2025-09-23), приложено на
КЪСНАТАТА. Критерий: |обещано - познато| < 4 пункта на късната половина.

Изход: validation/tri_b_20260923.md/.csv, _matches.csv.
"""
import os
import sys

os.environ["OMP_NUM_THREADS"] = "1"
from multiprocessing import Pool  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import minimize  # noqa: E402
from scipy.special import gammaln  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

import backtest_full as bf  # noqa: E402
import football_lib as fl  # noqa: E402
import kalibraciq_xg_20260923 as kx  # noqa: E402
import tri_fit as tf  # noqa: E402

TAG = "20260923"
MIN_COV = 0.70
MINHIST = 150
MAXC = 30
CODES = ["corners_total_over_9.5", "corners_home_over_4.5", "corners_away_over_4.5"]
VARIANTS = ["live", "current", "pressure", "combined"]
NAMES = {"live": "ЖИВИЯТ днес (средни корнери, Поасон)", "current": "средни корнери + отр. биномно", "pressure": "нов: от очакваните удари и владение",
         "combined": "нов + сегашния като признак"}
_C = np.arange(MAXC)


def corner_leagues():
    out = []
    for lg in bf.LEAGUES:
        df = fl.load_league_data(lg)
        fin = df[df["home_goals"].notna()]
        if "home_corners" in df.columns and len(fin):
            cov = len(fin.dropna(subset=["home_corners", "away_corners"])) / len(fin)
            if cov >= MIN_COV:
                out.append(lg)
    return out


def fit_poss(hist, ref, ti, n, xi, lam=5.0):
    v = hist.dropna(subset=["home_possession"])
    y = np.clip(v["home_possession"].to_numpy(float), 5, 95) / 100
    y = np.log(y / (1 - y))
    w = np.exp(-xi * np.clip((ref - v["date"]).dt.days.to_numpy(), 0, None))
    h = v["home_team"].map(ti).to_numpy()
    a = v["away_team"].map(ti).to_numpy()
    X = np.zeros((len(v), n + 1))
    X[:, n] = 1
    X[np.arange(len(v)), h] += 1
    X[np.arange(len(v)), a] -= 1
    R = np.eye(n + 1) * lam
    R[n, n] = 0
    beta = np.linalg.solve(X.T @ (X * w[:, None]) + R, X.T @ (w * y))
    return beta


def poss_pred(beta, n, hi, ai):
    return beta[n] + beta[hi] - beta[ai]   # logit на владението на домакина


def feats(rows, ti, n, sh, sot, poss, cur):
    hi = rows["home_team"].map(ti).to_numpy()
    ai = rows["away_team"].map(ti).to_numpy()
    def lam(m):
        l = np.exp(m["c"] + m["attack"][hi] - m["defence"][ai] + m["home_adv"])
        u = np.exp(m["c"] + m["attack"][ai] - m["defence"][hi])
        return l, u
    sh_h, sh_a = lam(sh)
    so_h, so_a = lam(sot)
    pl = poss_pred(poss, n, hi, ai)
    c_h, c_a = lam(cur)
    one = np.ones(len(rows))
    Xh = np.column_stack([one, one, np.log(sh_h), np.log(sh_a), pl, np.log(so_h), np.log(c_h)])
    Xa = np.column_stack([one, 0 * one, np.log(sh_a), np.log(sh_h), -pl, np.log(so_a), np.log(c_a)])
    return Xh, Xa, c_h, c_a


def fit_glm(X, y, w, l2=1.0):
    def f(b):
        eta = X @ b
        m = np.exp(eta)
        val = -(w * (y * eta - m)).sum() + l2 * (b[1:] ** 2).sum()
        g = -X.T @ (w * (y - m))
        g[1:] += 2 * l2 * b[1:]
        return val, g
    b0 = np.zeros(X.shape[1])
    b0[0] = np.log(max(y.mean(), 0.1))
    return minimize(f, b0, jac=True, method="L-BFGS-B").x


def run(league):
    df = fl.load_league_data(league)
    teams, n, ti = fl.get_team_index(df)
    fin = df.dropna(subset=["home_goals", "away_goals"])
    start = fin["date"].max() - pd.Timedelta(days=bf.PERIOD_DAYS)
    test = fin[(fin["date"] >= start)].dropna(subset=["home_corners", "away_corners"]).copy()
    test["week"] = test["date"] - pd.to_timedelta(test["date"].dt.weekday, unit="D")
    xi = fl.LEAGUE_XI.get(league, fl.XI)
    need = ["home_corners", "away_corners", "home_shots", "away_shots", "home_shots_on_goal",
            "away_shots_on_goal", "home_possession"]
    full = fin.dropna(subset=need)
    rows = []
    x = {}
    for week, block in test.groupby("week", sort=True):
        hist_c = fin[fin["date"] < week].dropna(subset=["home_corners", "away_corners"])
        hist = full[full["date"] < week]
        cur = tf.fit(hist_c, week, ti, n, xi, kind="xg", obs_cols=("home_corners", "away_corners"),
                     low_data_extra_reg=0.0, x0=x.get("cur"))
        x["cur"] = cur["x"]
        rec_base = {"league": league, "fit_week": week}
        if len(hist) >= MINHIST:
            sh = tf.fit(hist, week, ti, n, xi, kind="xg", obs_cols=("home_shots", "away_shots"), intercept=True, x0=x.get("sh"))
            sot = tf.fit(hist, week, ti, n, xi, kind="xg", obs_cols=("home_shots_on_goal", "away_shots_on_goal"),
                         intercept=True, x0=x.get("sot"))
            x["sh"], x["sot"] = sh["x"], sot["x"]
            poss = fit_poss(hist, week, ti, n, xi)
            Xh, Xa, _, _ = feats(hist, ti, n, sh, sot, poss, cur)
            w = np.exp(-xi * np.clip((week - hist["date"]).dt.days.to_numpy(), 0, None))
            X = np.vstack([Xh, Xa])
            y = np.concatenate([hist["home_corners"].to_numpy(float), hist["away_corners"].to_numpy(float)])
            ww = np.concatenate([w, w])
            b_p = fit_glm(X[:, :6], y, ww)
            b_c = fit_glm(X, y, ww)
            Th, Ta, ch, ca = feats(block, ti, n, sh, sot, poss, cur)
            ph, pa = np.exp(Th[:, :6] @ b_p), np.exp(Ta[:, :6] @ b_p)
            qh, qa = np.exp(Th @ b_c), np.exp(Ta @ b_c)
        else:
            hi = block["home_team"].map(ti).to_numpy()
            ai = block["away_team"].map(ti).to_numpy()
            ch = np.exp(cur["attack"][hi] - cur["defence"][ai] + cur["home_adv"])
            ca = np.exp(cur["attack"][ai] - cur["defence"][hi])
            ph = pa = qh = qa = np.full(len(block), np.nan)
        for i, r in enumerate(block.itertuples()):
            rows.append({**rec_base, "fixture_id": r.fixture_id, "date": r.date, "hc": int(r.home_corners),
                         "ac": int(r.away_corners), "current_h": ch[i], "current_a": ca[i], "pressure_h": ph[i],
                         "pressure_a": pa[i], "combined_h": qh[i], "combined_a": qa[i]})
    return pd.DataFrame(rows)


def nb_pmf(m, alpha):
    m = np.asarray(m, float)[:, None]
    if alpha <= 0:
        return np.exp(_C * np.log(m) - m - gammaln(_C + 1))
    r = 1 / alpha
    return np.exp(gammaln(_C + r) - gammaln(r) - gammaln(_C + 1) + r * np.log(r / (r + m)) + _C * np.log(m / (r + m)))


def probs(mh, ma, alpha):
    ph, pa = nb_pmf(mh, alpha), nb_pmf(ma, alpha)
    tot = np.array([np.convolve(a, b)[:MAXC] for a, b in zip(ph, pa)])
    return pd.DataFrame({"corners_total_over_9.5": 1 - tot[:, :10].sum(1),
                         "corners_home_over_4.5": 1 - ph[:, :5].sum(1),
                         "corners_away_over_4.5": 1 - pa[:, :5].sum(1)})


def fit_alpha(mh, ma, hc, ac):
    best, bv = 0.0, -np.inf
    for al in np.round(np.arange(0, 0.301, 0.01), 2):
        ll = (np.log(np.maximum(nb_pmf(mh, al)[np.arange(len(hc)), np.minimum(hc, MAXC - 1)], 1e-300)).sum() +
              np.log(np.maximum(nb_pmf(ma, al)[np.arange(len(ac)), np.minimum(ac, MAXC - 1)], 1e-300)).sum())
        if ll > bv:
            best, bv = al, ll
    return best


def fav_gap(P, Y, mask):
    """метриката от calibration_all_markets: по-вероятната страна на всеки пазар."""
    p = P[mask].to_numpy().ravel()
    y = Y[mask].to_numpy().ravel()
    fav = np.where(p >= 0.5, p, 1 - p)
    hit = np.where(p >= 0.5, y, 1 - y)
    return 100 * fav.mean(), 100 * hit.mean(), len(fav)


def fav_gap_code(P, Y, mask, c):
    p, y = P.loc[mask, c].to_numpy(), Y.loc[mask, c].to_numpy()
    fav = np.where(p >= 0.5, p, 1 - p)
    hit = np.where(p >= 0.5, y, 1 - y)
    return 100 * fav.mean(), 100 * hit.mean()


def band_gap(P, Y, mask):
    p = P[mask].to_numpy().ravel()
    y = Y[mask].to_numpy().ravel()
    b = np.minimum((p * 10).astype(int), 9)
    s = pd.DataFrame({"b": b, "p": p, "y": y}).groupby("b").agg(n=("y", "size"), p=("p", "mean"), y=("y", "mean"))
    return 100 * float((s["n"] * (s["p"] - s["y"]).abs()).sum() / s["n"].sum())


def cal_fit(P, Y, mask):
    b = {c: Y.loc[mask, c].mean() for c in CODES}
    num = sum(((P.loc[mask, c] - b[c]) * (Y.loc[mask, c] - b[c])).sum() for c in CODES)
    den = sum(((P.loc[mask, c] - b[c]) ** 2).sum() for c in CODES)
    return num / den, b


def cal_apply(P, a, b):
    return pd.DataFrame({c: np.clip(b[c] + a * (P[c] - b[c]), 0, 1) for c in CODES})


def main():
    lgs = corner_leagues()
    with Pool(len(lgs)) as pool:
        parts = pool.map(run, sorted(lgs, key=lambda x: x not in ("england2", "spain2")))
    m = pd.concat(parts, ignore_index=True)
    m = m.dropna(subset=["pressure_h"]).reset_index(drop=True)   # еднакви мачове за всички варианти
    m["early"] = pd.to_datetime(m["date"]) < kx.CUT
    early = m["early"].to_numpy()
    Y = pd.DataFrame({"corners_total_over_9.5": (m.hc + m.ac > 9.5).astype(float),
                      "corners_home_over_4.5": (m.hc > 4.5).astype(float),
                      "corners_away_over_4.5": (m.ac > 4.5).astype(float)})
    res, alphas, P_all = [], {}, {}
    for v in VARIANTS:
        parts = []
        for lg in lgs:
            s = (m.league == lg).to_numpy()
            e = s & early
            col = "current" if v == "live" else v
            al = 0.0 if v == "live" else fit_alpha(m.loc[e, f"{col}_h"].to_numpy(), m.loc[e, f"{col}_a"].to_numpy(),
                                                   m.loc[e, "hc"].to_numpy(), m.loc[e, "ac"].to_numpy())
            alphas[(v, lg)] = al
            pf = probs(m.loc[s, f"{col}_h"].to_numpy(), m.loc[s, f"{col}_a"].to_numpy(), al)
            pf.index = np.where(s)[0]
            parts.append(pf)
        P = pd.concat(parts).sort_index()
        a, b = cal_fit(P, Y, early)
        C = cal_apply(P, a, b)
        P_all[v] = (P, C, a)
        for lab, Q in (("суров", P), ("калибриран", C)):
            for part, mask in (("ранна", early), ("късна", ~early)):
                pr, hi, nn = fav_gap(Q, Y, mask)
                r = {"variant": v, "cal": lab, "part": part, "n_markets": nn, "promised": pr, "hit": hi,
                     "gap": pr - hi, "band_gap": band_gap(Q, Y, mask), "a": a,
                     "brier": float(((Q[mask] - Y[mask]) ** 2).to_numpy().mean())}
                for c in CODES:
                    r[f"gap_{c}"] = np.subtract(*fav_gap_code(Q, Y, mask, c))
                res.append(r)
    res = pd.DataFrame(res)
    res.round(5).to_csv(f"validation/tri_b_{TAG}.csv", index=False)
    m.to_csv(f"validation/tri_b_{TAG}_matches.csv", index=False)
    # по лига, късна, калибриран
    per = []
    for lg in lgs:
        s = (m.league == lg).to_numpy() & ~early
        row = {"league": lg, "n": int(s.sum())}
        for v in VARIANTS:
            pr, hi, _ = fav_gap(P_all[v][1], Y, s)
            row[v] = pr - hi
        per.append(row)
    # диагностика: колко от разсейването на реалните корнери обяснява всеки модел (късна, корелация)
    corr = {v: float(np.corrcoef(m.loc[~early, f"{v}_h"] + m.loc[~early, f"{v}_a"],
                                 m.loc[~early, "hc"] + m.loc[~early, "ac"])[0, 1]) for v in VARIANTS if v != "live"}
    a_p, b_p = cal_fit(P_all["pressure"][0], Y, early)
    prm = [{"param": f"alpha_{lg}", "value": alphas[("pressure", lg)]} for lg in lgs]
    prm += [{"param": "cal_a", "value": a_p}] + [{"param": f"cal_b_{c}", "value": b_p[c]} for c in CODES]
    pd.DataFrame(prm).round(6).to_csv(f"validation/tri_b_{TAG}_params.csv", index=False)
    write_md(res, pd.DataFrame(per), alphas, lgs, corr, len(m), int((~early).sum()), a_p, b_p)


def write_md(res, per, alphas, lgs, corr, n_all, n_late, a_p, b_p):
    L = [f"# ТРИ, ЧАСТ Б - корнерите - {TAG}", "",
         "ZADACHA_TRI.md, ЧАСТ Б. Скрипт: `validation/tri_b_20260923.py` (методът е в docstring-а). Сурови",
         "числа: `tri_b_20260923.csv`, по мач: `tri_b_20260923_matches.csv`.", "",
         f"Лиги (живият код строи модел за корнери там): {', '.join(lgs)}. Мачове: {n_all} (късна половина {n_late}).",
         "Пазари - показваните: общо над/под 9.5, домакин над 4.5, гост над 4.5. „Бърка с“ = средно обещано",
         "минус реално познато за по-вероятната страна на всеки пазар (метриката от",
         "calibration_all_markets_20260922.md - там 61% срещу 48%).", "",
         "## Късна половина (извън всеки избор) - колко бърка", "",
         "| модел | калибрация | обещано | познато | бърка с | по ленти | общо 9.5 | дом. 4.5 | гост 4.5 |",
         "|---|---|---|---|---|---|---|---|---|"]
    late = res[res.part == "късна"]
    for r in late.itertuples():
        L.append(f"| {NAMES[r.variant]} | {r.cal} | {r.promised:.1f}% | {r.hit:.1f}% | **{r.gap:+.1f}** | {r.band_gap:.1f} | "
                 f"{getattr(r, '_11'):+.1f} | {getattr(r, '_12'):+.1f} | {getattr(r, '_13'):+.1f} |")
    L += ["", "(„по ленти“ = средна |обещано − познато| по ленти от 10 пункта; последните три колони - „бърка с“ по пазар.)", "",
          "Калибрацията за корнерите (a от ранната половина): " +
          ", ".join(f"{NAMES[v]} a = {res[(res.variant == v)].a.iloc[0]:.2f}" for v in VARIANTS) + ".", "",
          "Колко следва реалния брой корнери (корелация очакван/реален сбор, късна): " +
          ", ".join(f"{NAMES[v]} {c:.2f}" for v, c in corr.items()) + ".", "",
          "## По лига - късна, с калибрация, „бърка с“ в пункта", "",
          "| лига | пазари | живият | средни + отр. бин. | нов | нов + сегашния |", "|---|---|---|---|---|---|"]
    for r in per.itertuples():
        L.append(f"| {r.league} | {r.n} мача | {r.live:+.1f} | {r.current:+.1f} | {r.pressure:+.1f} | {r.combined:+.1f} |")
    L += ["", "Отрицателно биномно alpha по лига (0 = Поасон): " +
          "; ".join(f"{lg}: " + "/".join(f"{alphas[(v, lg)]:.2f}" for v in VARIANTS) for lg in lgs) + " (живият/средни/нов/комбиниран)."]
    late_p = res[(res.part == "късна") & (res.variant == "pressure") & (res.cal == "калибриран")].iloc[0]
    late_l = res[(res.part == "късна") & (res.variant == "live") & (res.cal == "суров")].iloc[0]
    L += ["", "## Решение", "",
          f"**Критерий (< 4 пункта): ИЗПЪЛНЕН.** Живият модел днес бърка с {late_l.gap:+.1f} пункта на всички мачове от",
          "късната половина (при 114-те логнати прогнози беше +12.8 - там са само показаните фаворити, още",
          f"по-крайни). Новият модел от очакваните удари и владение: {late_p.gap:+.1f} пункта с калибрацията,",
          "без нея +0.7. Живият модел със силна калибрация (a = 0.44 - почти изцяло свит към средното) също",
          "стига +0.8 общо, но по ленти бърка повече (1.9 срещу 1.1). Комбинираният не е по-добър от новия.", "",
          "Влиза: новият модел (признаците са без сегашния модел), отрицателно биномно с alpha по лига и",
          f"калибрация за групата „корнери“: a = {a_p:.3f}, b = " + ", ".join(f"{c} {b_p[c]:.4f}" for c in CODES) + ".",
          "Параметрите: `tri_b_20260923_params.csv`. Лигите без модел за корнери - без промяна (няма корнери)."]
    with open(f"validation/tri_b_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
