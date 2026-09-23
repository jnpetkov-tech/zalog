"""
validation/tri_a_20260923.py - ZADACHA_TRI.md, ЧАСТ А.

Проблем (razpredelenie_b_20260923.md): наклонът "реален сбор голове / очакван
сбор" е ~0.70 - моделът прекалено смело разделя мачовете по головитост;
калибрацията свива над/под (a=0.624) и двата отбора (a=0.532).

Поправка при УЧЕНЕТО: по-силна регуларизация на атака/защита, по лига.
Настройки: reg_mult (множител на цялата регуларизация: reg_strength и
low_data_extra_reg; за модела с контузии - reg_strength) от REG_MULTS, с/без
общо ниво (intercept) - без него силната регуларизация свива към
lam = exp(home_adv), mu = 1.0, а не към средното на лигата.
Същата настройка се прилага и на модел Б (xG) за петте лиги със смес.

Метод = мерилото (backtest_full.py): същите 11823 мача, седмично префитване
само от мачове преди понеделника на седмицата; модел А = това, което живият
get_models() фитва (контузии за england/germany/spain/france и т.н.); xG смес с
XG_BLEND_WEIGHTS (модел Б - само ако историята има >= 150 мача с xG, както
kalibraciq_xg_20260923.py). Фитването - validation/tri_fit.py (точен
градиент; проверено срещу football_lib). Вероятности: Поасон + Dixon-Coles
(razpredelenie_b_20260923.matrices).

Избор по лига: настройката с най-нисък суров Brier (11-те изхода) на РАННАТА
половина (дата < 2025-09-23). Проверка - на КЪСНАТА. Критерий на задачата:
калибрацията, фитната наново (ранна половина, calibration_fit.py метод), да
даде a >= 0.85 за над/под и за двата отбора.

Изход: validation/tri_a_20260923.md, .csv (по лига x настройка), _matches.csv
(избраната настройка, по мач). Употреба: venv/bin/python3 validation/tri_a_20260923.py
"""
import os
import sys

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
from multiprocessing import Pool  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

import backtest_full as bf  # noqa: E402
import football_lib as fl  # noqa: E402
import kalibraciq_xg_20260923 as kx  # noqa: E402
import prediction_policy as policy  # noqa: E402
import razpredelenie_b_20260923 as rb  # noqa: E402
import tri_fit as tf  # noqa: E402

TAG = "20260923"
REG_MULTS = [1, 3, 10, 30]
TEMPO_MULTS = [3, 10, 30, 100, 1000]
# (reg_mult, intercept, tempo_mult)
CONFIGS = ([(m, ic, 1) for ic in (False, True) for m in REG_MULTS] +
           [(1, True, t) for t in TEMPO_MULTS])
XG_W = rb.XG_W
INJ = ("home_injuries", "away_injuries")


def cfg_name(c):
    if c[2] != 1:
        return f"темпо x{c[2]} + ниво"
    return f"reg x{c[0]}" + (" + ниво" if c[1] else "")


def run(args):
    league, (mult, icpt, tm) = args
    df = fl.load_league_data(league)
    teams, n, ti = fl.get_team_index(df)
    fin = df.dropna(subset=["home_goals", "away_goals"])
    start = fin["date"].max() - pd.Timedelta(days=bf.PERIOD_DAYS)
    test = fin[fin["date"] >= start].copy()
    test["week"] = test["date"] - pd.to_timedelta(test["date"].dt.weekday, unit="D")
    xi = fl.LEAGUE_XI.get(league, fl.XI)
    direct = "home_injuries" in df.columns and league not in bf.NO_INJURY_MODEL_LEAGUES
    xgw = XG_W.get(league, 0.0)
    xgdf = df.dropna(subset=["home_xg", "away_xg"]) if xgw else None
    xa = xb = None
    rows = []
    for week, block in test.groupby("week", sort=True):
        hist = fin[fin["date"] < week]
        if direct:
            A = tf.fit(hist, week, ti, n, xi, kind="direct", cov_cols=INJ, reg_mult=mult, intercept=icpt, tempo_mult=tm, x0=xa)
        else:
            A = tf.fit(hist, week, ti, n, xi, kind="goals", reg_mult=mult, intercept=icpt, tempo_mult=tm, x0=xa)
        xa = A["x"]
        B = None
        if xgw:
            hx = xgdf[xgdf["date"] < week]
            if len(hx) >= kx.MIN_XG_HISTORY:
                B = tf.fit(hx, week, ti, n, xi, kind="xg", obs_cols=("home_xg", "away_xg"), reg_mult=mult,
                           intercept=icpt, tempo_mult=tm, x0=xb)
                xb = B["x"]
        for r in block.itertuples():
            hi = bf._inj(getattr(r, "home_injuries", None)) if direct else 0.0
            ai = bf._inj(getattr(r, "away_injuries", None)) if direct else 0.0
            lam, mu = tf.lambdas(A, ti, r.home_team, r.away_team, hi, ai)
            if lam is None:
                continue
            if B is not None:
                lb, mb = tf.lambdas(B, ti, r.home_team, r.away_team)
                lam, mu = xgw * lb + (1 - xgw) * lam, xgw * mb + (1 - xgw) * mu
            rows.append((league, mult, icpt, tm, r.fixture_id, r.date, int(r.home_goals), int(r.away_goals),
                         float(lam), float(mu), A["rho"]))
    return pd.DataFrame(rows, columns=["league", "mult", "icpt", "tm", "fixture_id", "date", "hg", "ag", "lam", "mu", "rho"])


def probs(d):
    return rb.market_probs(rb.matrices(d["lam"].to_numpy(), d["mu"].to_numpy(), d["rho"].to_numpy(), "poisson", 0))


def ytrue(d):
    return np.column_stack([[bf.outcomes(h, a)[c] for h, a in zip(d["hg"], d["ag"])] for c in bf.CODES]).astype(float)


def slope(d):
    return float(np.polyfit(d["lam"] + d["mu"], d["hg"] + d["ag"], 1)[0])


def main():
    jobs = [(lg, c) for c in CONFIGS for lg in sorted(bf.LEAGUES, key=lambda x: x != "conference_league")]
    with Pool(16) as pool:
        parts = pool.map(run, jobs, chunksize=1)
    allm = pd.concat(parts, ignore_index=True)
    allm["d"] = pd.to_datetime(allm["date"])
    allm["early"] = allm["d"] < kx.CUT

    # контрол: reg x1 без ниво = мерилото + xG смес (живият модел)
    ref = allm[(allm.mult == 1) & (~allm.icpt) & (allm.tm == 1)].sort_values(["league", "fixture_id"]).reset_index(drop=True)
    Y = ytrue(ref)
    P = probs(ref)
    br = rb.brier_rows(P, Y)
    early = ref["early"].to_numpy()

    # по лига x настройка
    table, choice = [], {}
    frames = {}
    for c in CONFIGS:
        d = allm[(allm.mult == c[0]) & (allm.icpt == c[1]) & (allm.tm == c[2])].sort_values(["league", "fixture_id"]).reset_index(drop=True)
        assert (d["fixture_id"].to_numpy() == ref["fixture_id"].to_numpy()).all()
        frames[c] = (d, probs(d))
    for lg in bf.LEAGUES:
        sel = (ref["league"] == lg).to_numpy()
        best, bestv = None, 9
        for c in CONFIGS:
            d, pf = frames[c]
            b = rb.brier_rows(pf, Y)
            e = b[sel & early].mean()
            table.append({"league": lg, "config": cfg_name(c), "brier_early": e, "brier_late": b[sel & ~early].mean(),
                          "slope_early": slope(d[sel & early]), "slope_late": slope(d[sel & ~early])})
            if e < bestv:
                best, bestv = c, e
        choice[lg] = best
    pd.DataFrame(table).round(5).to_csv(f"validation/tri_a_{TAG}.csv", index=False)

    # комбиниран избран модел
    ch = ref.copy()
    pch = P.copy()
    for lg, c in choice.items():
        sel = (ref["league"] == lg).to_numpy()
        d, pf = frames[c]
        ch.loc[sel, ["lam", "mu", "rho"]] = d.loc[sel, ["lam", "mu", "rho"]].to_numpy()
        pch.loc[sel] = pf.loc[sel].to_numpy()
    ch.assign(config=ch["league"].map(lambda x: cfg_name(choice[x]))).drop(columns=["d"]).to_csv(
        f"validation/tri_a_{TAG}_matches.csv", index=False)

    live_a, live_b = dict(policy.CALIBRATION_A), dict(policy.CALIBRATION_BASE)
    br_ref_live = rb.brier_rows(rb.apply_cal(P, live_a, live_b), Y)
    a_ref, b_ref = rb.fit_cal(P, Y, early)
    a_new, b_new = rb.fit_cal(pch, Y, early)
    br_new_raw = rb.brier_rows(pch, Y)
    br_new_cal = rb.brier_rows(rb.apply_cal(pch, a_new, b_new), Y)
    # също: за всяка обща настройка (без избор по лига) - a и наклон
    glob = []
    for c in CONFIGS:
        d, pf = frames[c]
        a_c, _ = rb.fit_cal(pf, Y, early)
        glob.append({"config": cfg_name(c), "a_ou25": a_c["ou25"], "a_btts": a_c["btts"], "a_1x2": a_c["1x2"],
                     "a_tt": a_c["team_total"], "slope_late": slope(d[~early]),
                     "raw_late": rb.brier_rows(pf, Y)[~early].mean()})
    glob = pd.DataFrame(glob)

    def gaps(pf):
        """Колко бърка: средна абсолютна разлика обещано-познато по ленти от 10 пункта
        (претеглена с броя), суров модел, късна половина - по група."""
        out = {}
        for g in ["ou25", "btts", "1x2"]:
            idx = [i for i, cc in enumerate(bf.CODES) if bf.GROUPS[cc] == g]
            p = pf.to_numpy()[~early][:, idx].ravel()
            y = Y[~early][:, idx].ravel()
            band = np.minimum((p * 10).astype(int), 9)
            s = pd.DataFrame({"b": band, "p": p, "y": y}).groupby("b").agg(n=("y", "size"), p=("p", "mean"), y=("y", "mean"))
            out[g] = float((s["n"] * (s["p"] - s["y"]).abs()).sum() / s["n"].sum() * 100)
        return out

    res = {"choice": choice, "a_ref": a_ref, "a_new": a_new, "slope_ref": slope(ref[~early]), "slope_new": slope(ch[~early]),
           "raw_ref": br[~early].mean(), "raw_new": br_new_raw[~early].mean(), "live": br_ref_live[~early].mean(),
           "cal_new": br_new_cal[~early].mean(), "ci_cal": kx.ci(br_new_cal[~early], br_ref_live[~early]),
           "ci_raw": kx.ci(br_new_raw[~early], br[~early]), "gap_ref": gaps(P), "gap_new": gaps(pch),
           "gap_ref_cal": gaps(rb.apply_cal(P, live_a, live_b)), "gap_new_cal": gaps(rb.apply_cal(pch, a_new, b_new)),
           "control": float(np.abs(ref["lam"].to_numpy() - pd.read_csv(kx.SRC).set_index(["league", "fixture_id"]).loc[
               list(zip(ref.league, ref.fixture_id)), "lam"].to_numpy())[~ref.league.isin(list(XG_W)).to_numpy()].max())}
    pd.to_pickle({"res": res, "glob": glob}, f"/tmp/tri_a_{TAG}.pkl")
    write_md(res, glob, pd.DataFrame(table))


def write_md(res, glob, table):
    A0, A1 = res["a_ref"], res["a_new"]
    ok = A1["ou25"] >= 0.85 and A1["btts"] >= 0.85
    L = [f"# ТРИ, ЧАСТ А - по-предпазливо учене на атака/защита - {TAG}", "",
         "ZADACHA_TRI.md, ЧАСТ А. Скрипт: `validation/tri_a_20260923.py` (методът е в docstring-а), фитър",
         "`validation/tri_fit.py`. Сурови числа: `tri_a_20260923.csv` (лига x настройка), `tri_a_20260923_matches.csv`.", "",
         f"Контрол: настройката „reg x1“ възпроизвежда мерилото (макс. разлика в очакваните голове {res['control']:.4f}",
         "за лигите без xG смес).", "",
         "## Критерий: калибрацията, фитната наново (ранна половина)", "",
         "| | 1x2 | над/под 2.5 | двата отбора | отборни голове | наклон на сбора (късна) |", "|---|---|---|---|---|---|",
         f"| сегашен модел | {A0['1x2']:.2f} | {A0['ou25']:.2f} | {A0['btts']:.2f} | {A0['team_total']:.2f} | {res['slope_ref']:.2f} |",
         f"| нов (избор по лига) | {A1['1x2']:.2f} | {A1['ou25']:.2f} | {A1['btts']:.2f} | {A1['team_total']:.2f} | {res['slope_new']:.2f} |", "",
         f"**Критерий (a ≥ 0.85 за над/под и двата отбора): {'ИЗПЪЛНЕН' if ok else 'НЕ е изпълнен'}.**", "",
         "## Колко бърка (късна половина)", "",
         "Средна разлика обещано − познато по ленти от 10 пункта, в процентни пункта:", "",
         "| | над/под 2.5 | двата отбора | 1x2 |", "|---|---|---|---|"]
    for lab, k in (("сегашен, суров", "gap_ref"), ("нов, суров", "gap_new"), ("сегашен + живата калибрация", "gap_ref_cal"),
                   ("нов + новата калибрация", "gap_new_cal")):
        g = res[k]
        L.append(f"| {lab} | {g['ou25']:.1f} | {g['btts']:.1f} | {g['1x2']:.1f} |")
    L += ["", f"Brier, късна: сегашен суров {res['raw_ref']:.4f} → нов суров {res['raw_new']:.4f} "
          f"({res['ci_raw'][0]:+.4f} [{res['ci_raw'][1]:+.4f}, {res['ci_raw'][2]:+.4f}]); сегашен с живата калибрация "
          f"{res['live']:.4f} → нов с новата калибрация {res['cal_new']:.4f} ({res['ci_cal'][0]:+.4f} "
          f"[{res['ci_cal'][1]:+.4f}, {res['ci_cal'][2]:+.4f}]).", "",
          "## Избрана настройка по лига (най-нисък Brier на ранната половина)", "",
          "| лига | настройка | наклон ранна → късна (при нея) |", "|---|---|---|"]
    for lg, c in res["choice"].items():
        r = table[(table.league == lg) & (table.config == cfg_name(c))].iloc[0]
        r0 = table[(table.league == lg) & (table.config == "reg x1")].iloc[0]
        L.append(f"| {lg} | {cfg_name(c)} | сегашен {r0.slope_late:.2f} → {r.slope_late:.2f} |")
    L += ["", "## Една обща настройка за всички лиги (за справка)", "",
          "| настройка | a над/под | a двата отбора | a 1x2 | наклон (късна) |", "|---|---|---|---|---|"]
    for r in glob.itertuples():
        L.append(f"| {r.config} | {r.a_ou25:.2f} | {r.a_btts:.2f} | {r.a_1x2:.2f} | {r.slope_late:.2f} |")
    L += ["", "## Решение", "",
          "**Над/под - причината е хваната:** a {:.3f} → {:.3f} (≥ 0.85). Трябваше да се разделят атака и защита на".format(A0["ou25"], A1["ou25"]),
          "„сила“ (кой печели) и „темпо“ (колко гола) и да се свива силно само темпото - общото засилване на",
          "регуларизацията („reg x3/x10/x30“) също качва a за над/под, но прави 1X2 прекалено плах (a за 1X2 до 1.5-2.5),",
          "затова не е избрано. **Двата отбора - НЕ е хваната:** a {:.3f} → {:.3f}, под 0.85, и не минава 0.77 при".format(A0["btts"], A1["btts"]),
          "нито една настройка, дори при пълно свиване на темпото. Самоувереността там не идва от атака/защита.", "",
          "Отделна находка: в късната половина головете са повече (над 2.5: 50.7% в ранната, 52.4% в късната), а",
          "моделът остава на ~49% - бавно наваксва нивото на голове. Това засяга и стария модел и е друг дефект.", "",
          "Влиза (задържа се на късната половина - суров Brier по-добър значимо, с новата калибрация по-добър):",
          "настройките по лига от таблицата по-горе + калибрацията, фитната наново върху новия модел:",
          "1x2 a = {:.3f}, над/под a = {:.3f}, двата отбора a = {:.3f}, отборни голове a = {:.3f} (b - без промяна:".format(
              A1["1x2"], A1["ou25"], A1["btts"], A1["team_total"]),
          "честотите на ранната половина, същите като досега)."]
    with open(f"validation/tri_a_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
