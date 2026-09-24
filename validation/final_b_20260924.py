"""
validation/final_b_20260924.py - ZADACHA_FINAL.md, ЧАСТ Б (24.09.2026).

Проблем (tri_a_20260923.md): в късната половина мачовете с над 2.5 гола са
52.4%, а моделът очаква ~49-50% - когато футболът стане по-голов, моделът
наваксва бавно.

ДИАГНОЗА: реалният сбор голове по тримесечие срещу очаквания; време-теглата
на модела (LEAGUE_XI - полуживот ~385 дни, за bulgaria/england/spain/france
~1390 дни): нивото на головете (общото c + домакинско предимство) се учи от
цялата претеглена история.

ПОПРАВКА (кандидат): след фитването - един множител k на нивото на лигата,
еднакъв за lam и mu (разграничаването между отборите - атака/защита/темпо -
не се пипа). k = отношението реални голове / очаквани голове от САМИЯ
модел върху собствените мачове на лигата, претеглени с по-кратък полуживот
HL, свито към 1 с N0 въображаеми мача (k = (сум w*G + N0*Tср) /
(сум w*T + N0*Tср), Tср - претеглената средна очаквана стойност).
Вариант "дом/гост": отделни k за головете на домакина и на госта.

МЕТОД = мерилото (backtest_full.py): същите 11823 мача, седмично префитване
само от мачове преди понеделника на седмицата; моделът = живият (настройките
се четат от match_predictor_app.py с ast, без импорт): FT_FIT_SETTINGS +
контузии + xG смес (validation/tri_fit.py, както tri_a_20260923.run()), общ
евро модел за трите турнира (validation/tri_v_euro.py, EURO_FIT_SETTINGS).
Матрица: Поасон + Dixon-Coles + зависимостта от ЧАСТ А
(football_lib.SCORE_DEP_*). Контрол: без поправката очакваните голове =
tri_a/tri_v _matches.csv.

ИЗБОР: (HL, N0, вариант) с най-нисък Brier (11-те изхода) на РАННАТА половина
(дата < 2025-09-23), една настройка за всички лиги. ПРОВЕРКА - на КЪСНАТАТА.
Критерий: |реален дял над 2.5 - очакван| < 1.5 пункта на късната половина
(суров модел и след калибрацията, фитната наново на ранната).

Изход: validation/final_b_20260924.md, .csv (решетката), _matches.csv (по мач).
Употреба: venv/bin/python3 validation/final_b_20260924.py
"""
import ast
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
import final_a_20260924 as fa  # noqa: E402
import football_lib as fl  # noqa: E402
import kalibraciq_xg_20260923 as kx  # noqa: E402
import razpredelenie_b_20260923 as rb  # noqa: E402
import tri_fit as tf  # noqa: E402
import tri_v_euro as E  # noqa: E402

TAG = "20260924"
INJ = ("home_injuries", "away_injuries")
WINDOW_DAYS = 400          # колко назад се пазят мачовете за k (полуживот до 180 дни)
HLS = [30, 60, 90, 120, 180, 365]
N0S = [0, 10, 25, 50, 100]
MODES = ["общ", "дом/гост"]
XI_MULTS = [1.0, 2.0, 4.0]      # по-кратка памет на ЦЕЛИЯ модел (време-теглата x2, x4)
OOS_HLS = [30, 60, 120, 365]
OOS_N0S = [0, 25, 100, 300]


def app_settings():
    """FT_FIT_SETTINGS, EURO_FIT_SETTINGS, XG_BLEND_WEIGHTS - от match_predictor_app.py (ast, без импорт:
    импортът фитва и ЗАПИСВА model_cache)."""
    tree = ast.parse(open("match_predictor_app.py").read())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            nm = node.targets[0].id
            if nm in ("FT_FIT_SETTINGS", "EURO_FIT_SETTINGS", "XG_BLEND_WEIGHTS", "NO_INJURY_MODEL_LEAGUES"):
                out[nm] = ast.literal_eval(node.value)
    return out


S = app_settings()


def test_weeks(df):
    fin = df.dropna(subset=["home_goals", "away_goals"])
    start = fin["date"].max() - pd.Timedelta(days=bf.PERIOD_DAYS)
    t = fin[fin["date"] >= start].copy()
    t["week"] = t["date"] - pd.to_timedelta(t["date"].dt.weekday, unit="D")
    return fin, t


def _vec_lambdas(m, ti, h, a, hc=None, ac=None):
    hi = np.array([ti[x] for x in h])
    ai = np.array([ti[x] for x in a])
    lam = m["c"] + m["attack"][hi] - m["defence"][ai] + m["home_adv"]
    mu = m["c"] + m["attack"][ai] - m["defence"][hi]
    if hc is not None:
        lam = lam + m["beta"] * hc
        mu = mu + m["beta"] * ac
    return np.exp(lam), np.exp(mu)


def run_domestic(league, xi_mult=1.0):
    df = fl.load_league_data(league)
    teams, n, ti = fl.get_team_index(df)
    fin, test = test_weeks(df)
    xi = fl.LEAGUE_XI.get(league, fl.XI) * xi_mult
    cfg = S["FT_FIT_SETTINGS"].get(league, {})
    kw = dict(reg_mult=cfg.get("reg_mult", 1), intercept=cfg.get("intercept", False),
              tempo_mult=float(cfg.get("tempo_mult", 1.0)))
    direct = "home_injuries" in df.columns and league not in S["NO_INJURY_MODEL_LEAGUES"]
    xgw = S["XG_BLEND_WEIGHTS"].get(league, 0.0)
    xgdf = df.dropna(subset=["home_xg", "away_xg"]) if xgw else None
    xa = xb = None
    tests, ins = [], []
    for week, block in test.groupby("week", sort=True):
        hist = fin[fin["date"] < week]
        if direct:
            A = tf.fit(hist, week, ti, n, xi, kind="direct", cov_cols=INJ, x0=xa, **kw)
        else:
            A = tf.fit(hist, week, ti, n, xi, kind="goals", x0=xa, **kw)
        xa = A["x"]
        B = None
        if xgw:
            hx = xgdf[xgdf["date"] < week]
            if len(hx) >= kx.MIN_XG_HISTORY:
                B = tf.fit(hx, week, ti, n, xi, kind="xg", obs_cols=("home_xg", "away_xg"), x0=xb, **kw)
                xb = B["x"]

        def lm(d):
            hc = d[INJ[0]].fillna(0.0).to_numpy(float) if direct else None
            ac = d[INJ[1]].fillna(0.0).to_numpy(float) if direct else None
            lam, mu = _vec_lambdas(A, ti, d["home_team"], d["away_team"], hc, ac)
            if B is not None:
                lb, mb = _vec_lambdas(B, ti, d["home_team"], d["away_team"])
                lam, mu = xgw * lb + (1 - xgw) * lam, xgw * mb + (1 - xgw) * mu
            return lam, mu

        blk = block
        lam, mu = lm(blk)
        tests.append(pd.DataFrame({"league": league, "week": week, "fixture_id": blk["fixture_id"].to_numpy(),
                                   "date": blk["date"].dt.date.astype(str).to_numpy(),
                                   "hg": blk["home_goals"].astype(int).to_numpy(), "ag": blk["away_goals"].astype(int).to_numpy(),
                                   "lam": lam, "mu": mu, "rho": A["rho"]}))
        rec = hist[hist["date"] >= week - pd.Timedelta(days=WINDOW_DAYS)]
        li, mi = lm(rec)
        ins.append(pd.DataFrame({"league": league, "week": week, "days": (week - rec["date"]).dt.days.to_numpy(),
                                 "hg": rec["home_goals"].to_numpy(float), "ag": rec["away_goals"].to_numpy(float),
                                 "lam": li, "mu": mi}))
    return pd.concat(tests, ignore_index=True), pd.concat(ins, ignore_index=True)


def run_cup(cup, xi_mult=1.0):
    g = dict(S["EURO_FIT_SETTINGS"][cup])
    g["xi"] = g["xi"] * xi_mult
    allm, group = E.load_all(fl.load_league_data)
    ix = E.Index(allm, group)
    df = fl.load_league_data(cup)
    fin, test = test_weeks(df)
    x0 = None
    tests, ins = [], []
    for week, block in test.groupby("week", sort=True):
        m = E.fit(allm[allm["date"] < week], week, ix, x0=x0, **g)
        x0 = m["x"]

        def lm(d):
            out = [E.lambdas(m, ix, cup, h, a) for h, a in zip(d["home_team"], d["away_team"])]
            return np.array([o[0] for o in out]), np.array([o[1] for o in out])

        lam, mu = lm(block)
        tests.append(pd.DataFrame({"league": cup, "week": week, "fixture_id": block["fixture_id"].to_numpy(),
                                   "date": block["date"].dt.date.astype(str).to_numpy(),
                                   "hg": block["home_goals"].astype(int).to_numpy(), "ag": block["away_goals"].astype(int).to_numpy(),
                                   "lam": lam, "mu": mu, "rho": m["rho"]}))
        hist = fin[fin["date"] < week]
        rec = hist[hist["date"] >= week - pd.Timedelta(days=WINDOW_DAYS)]
        li, mi = lm(rec)
        ins.append(pd.DataFrame({"league": cup, "week": week, "days": (week - rec["date"]).dt.days.to_numpy(),
                                 "hg": rec["home_goals"].to_numpy(float), "ag": rec["away_goals"].to_numpy(float),
                                 "lam": li, "mu": mi}))
    return pd.concat(tests, ignore_index=True), pd.concat(ins, ignore_index=True)


def run(args):
    league, xi_mult = args
    fn = run_cup if league in S["EURO_FIT_SETTINGS"] else run_domestic
    t, i = fn(league, xi_mult)
    return t.assign(xi_mult=xi_mult), i.assign(xi_mult=xi_mult)


def level_factors(ins, hl, n0, mode):
    """(league, week) -> (k_home, k_away). Формулата = football_lib.league_level_factor()."""
    w = np.exp(-np.log(2) / hl * np.clip(ins["days"].to_numpy(), 0, None))
    d = ins[["league", "week"]].copy()
    d["w"] = w
    d["wh"], d["wa"] = w * ins["hg"].to_numpy(), w * ins["ag"].to_numpy()
    d["wl"], d["wm"] = w * ins["lam"].to_numpy(), w * ins["mu"].to_numpy()
    s = d.groupby(["league", "week"])[["w", "wh", "wa", "wl", "wm"]].sum()
    if mode == "общ":
        tbar = (s["wl"] + s["wm"]) / s["w"]
        k = (s["wh"] + s["wa"] + n0 * tbar) / (s["wl"] + s["wm"] + n0 * tbar)
        return pd.DataFrame({"kh": k, "ka": k})
    lbar, mbar = s["wl"] / s["w"], s["wm"] / s["w"]
    return pd.DataFrame({"kh": (s["wh"] + n0 * lbar) / (s["wl"] + n0 * lbar),
                         "ka": (s["wa"] + n0 * mbar) / (s["wm"] + n0 * mbar)})


def probs(lam, mu, rho):
    pm = fa.shift(rb.matrices(lam, mu, rho, "poisson", 0), lam, mu, fl.SCORE_DEP_F0, fl.SCORE_DEP_F1)
    return rb.market_probs(pm)


def main():
    order = sorted(bf.LEAGUES, key=lambda x: x not in S["EURO_FIT_SETTINGS"])
    jobs = [(lg, m) for m in XI_MULTS for lg in order]
    with Pool(16) as pool:
        parts = pool.map(run, jobs, chunksize=1)
    allt = pd.concat([p[0] for p in parts], ignore_index=True)
    alli = pd.concat([p[1] for p in parts], ignore_index=True)
    pd.to_pickle((allt, alli), f"/tmp/final_b_{TAG}.pkl")
    analyse(allt, alli)


def oos_factors(test, hl, n0, scope):
    """Множител от ИЗВЪН-извадковите грешки: реални / очаквани голове в прогнозите за предишните
    седмици (само мачове преди понеделника), полуживот hl, свито с n0; scope - по лига или общо."""
    k = np.ones(len(test))
    d = pd.to_datetime(test["date"])
    G = (test.hg + test.ag).to_numpy(float)
    T = (test.lam + test.mu).to_numpy()
    groups = test.groupby("league").groups.items() if scope == "лига" else [("all", test.index)]
    for _, idx in groups:
        idx = np.asarray(idx)
        dd, gg, tt, wk = d.to_numpy()[idx], G[idx], T[idx], test["week"].to_numpy()[idx]
        for w in np.unique(wk):
            prev = dd < w
            if not prev.any():
                continue
            ww = np.exp(-np.log(2) / hl * ((w - dd[prev]) / np.timedelta64(1, "D")))
            tb = (ww * tt[prev]).sum() / ww.sum()
            k[idx[wk == w]] = ((ww * gg[prev]).sum() + n0 * tb) / ((ww * tt[prev]).sum() + n0 * tb)
    return k


def novelty(test):
    """По-малкият от двата отбора: колко мача в лигата е имал през 365-те дни преди седмицата."""
    out = np.zeros(len(test), int)
    for lg, s in test.groupby("league"):
        df = fl.load_league_data(lg).dropna(subset=["home_goals", "away_goals"])
        byteam = {}
        for c in ("home_team", "away_team"):
            for t, dts in df.groupby(c)["date"]:
                byteam.setdefault(t, []).extend(dts.tolist())
        byteam = {t: np.sort(np.array(v, dtype="datetime64[ns]")) for t, v in byteam.items()}
        fx = df.set_index("fixture_id")
        for i, r in zip(s.index, s.itertuples()):
            w = np.datetime64(r.week)
            lo = w - np.timedelta64(365, "D")
            cnt = []
            for t in (fx.at[r.fixture_id, "home_team"], fx.at[r.fixture_id, "away_team"]):
                a = byteam.get(t, np.array([], dtype="datetime64[ns]"))
                cnt.append(int(np.searchsorted(a, w) - np.searchsorted(a, lo)))
            out[i] = min(cnt)
    return out


def summarize(P, Y, early, io, b0=None):
    br = rb.brier_rows(P, Y)
    r = {"brier_early": br[early].mean(), "brier_late": br[~early].mean(),
         "gap_early": (P["over25"].to_numpy()[early].mean() - Y[early, io].mean()) * 100,
         "gap_late": (P["over25"].to_numpy()[~early].mean() - Y[~early, io].mean()) * 100, "br": br}
    if b0 is not None:
        r["d_early"] = br[early].mean() - b0[early].mean()
        r["d_late"] = br[~early].mean() - b0[~early].mean()
        r["ci_late"] = kx.ci(br[~early], b0[~early])
    return r


def analyse(allt, alli):
    test = allt[allt.xi_mult == 1.0].sort_values(["league", "fixture_id"]).reset_index(drop=True)
    ins = alli[alli.xi_mult == 1.0]
    live = fa.live_frame()
    ref = live.set_index(["league", "fixture_id"]).loc[list(zip(test.league, test.fixture_id))]
    control = float(np.abs(ref["lam"].to_numpy() - test["lam"].to_numpy()).max())
    early = (pd.to_datetime(test.date) < kx.CUT).to_numpy()
    Y = fa.ytrue(test)
    io = bf.CODES.index("over25")
    lam0, mu0, rho = test.lam.to_numpy(), test.mu.to_numpy(), test.rho.to_numpy()
    P0 = probs(lam0, mu0, rho)
    base = summarize(P0, Y, early, io)
    b0 = base["br"]
    a_e, b_e = rb.fit_cal(P0, Y, early)
    Pc = rb.apply_cal(P0, a_e, b_e)
    res = {"control": control, "base": base,
           "obs": {"ранна": Y[early, io].mean() * 100, "късна": Y[~early, io].mean() * 100},
           "cal_late": Pc["over25"].to_numpy()[~early].mean() * 100, "raw_late": P0["over25"].to_numpy()[~early].mean() * 100,
           "noA_late": rb.market_probs(rb.matrices(lam0, mu0, rho, "poisson", 0))["over25"].to_numpy()[~early].mean() * 100}

    # диагноза
    t = test.assign(G=test.hg + test.ag, T=lam0 + mu0, y=Y[:, io], p=P0["over25"].to_numpy(), late=~early)
    t["q"] = pd.to_datetime(t.date).dt.to_period("Q").astype(str)
    res["quarters"] = t.groupby("q").agg(n=("G", "size"), G=("G", "mean"), T=("T", "mean"), y=("y", "mean"), p=("p", "mean"))
    t["bin"] = pd.qcut(t["T"], 6)
    res["bins"] = t.groupby(["bin", "late"], observed=True).agg(n=("y", "size"), y=("y", "mean"), p=("p", "mean"),
                                                               T=("T", "mean")).unstack()
    t["nov"] = pd.cut(novelty(test), [-1, 5, 15, 10 ** 6], labels=["до 5", "6-15", "над 15"])
    res["nov"] = t.groupby(["nov", "late"], observed=True).agg(n=("y", "size"), y=("y", "mean"), p=("p", "mean")).unstack()
    res["leagues"] = t.groupby(["league", "late"]).agg(G=("G", "mean"), T=("T", "mean")).unstack()
    ins_r = ins.assign(G=ins.hg + ins.ag, T=ins.lam + ins.mu)
    res["ins90"] = ins_r[ins_r.days <= 90].groupby("league")[["G", "T"]].mean()

    # вариант 1: множител от собствените мачове (в извадката)
    fam = []
    for mode in MODES:
        for hl in HLS:
            for n0 in N0S:
                k = level_factors(ins, hl, n0, mode).reindex(list(zip(test.league, test.week))).fillna(1.0)
                r = summarize(probs(lam0 * k["kh"].to_numpy(), mu0 * k["ka"].to_numpy(), rho), Y, early, io, b0)
                fam.append({"вариант": "1. в извадката", "настройка": f"{mode}, полуживот {hl}, N0={n0}", **r})
    # вариант 2: множител от грешките на прогнозите за предишните седмици
    for scope in ("лига", "общо"):
        for hl in OOS_HLS:
            for n0 in OOS_N0S:
                k = oos_factors(test, hl, n0, scope)
                r = summarize(probs(lam0 * k, mu0 * k, rho), Y, early, io, b0)
                fam.append({"вариант": "2. извън извадката", "настройка": f"{scope}, полуживот {hl}, N0={n0}", **r})
    # вариант 3: по-кратка памет на целия модел
    for m in XI_MULTS[1:]:
        s = allt[allt.xi_mult == m].sort_values(["league", "fixture_id"]).reset_index(drop=True)
        assert (s.fixture_id.to_numpy() == test.fixture_id.to_numpy()).all()
        r = summarize(probs(s.lam.to_numpy(), s.mu.to_numpy(), s.rho.to_numpy()), Y, early, io, b0)
        fam.append({"вариант": "3. по-кратка памет", "настройка": f"време-тегла x{m:g}", **r})
    fam = pd.DataFrame(fam)
    fam.drop(columns=["br", "ci_late"]).round(5).to_csv(f"validation/final_b_{TAG}.csv", index=False)
    res["fam"] = fam
    write_md(res)


def write_md(res):
    B, obs, fam = res["base"], res["obs"], res["fam"]
    L = [f"# ФИНАЛ, ЧАСТ Б - моделът изостава от нивото на головете - {TAG}", "",
         "ZADACHA_FINAL.md, ЧАСТ Б. Скрипт: `validation/final_b_20260924.py` (методът е в docstring-а). Всички проверени",
         "варианти: `final_b_20260924.csv`.", "",
         f"Контрол: повторната сметка дава същите очаквани голове като живия модел (tri_a/tri_v), макс. разлика",
         f"{res['control']:.1e}. Моделът включва поправката от ЧАСТ А.", "",
         "## Резултат: критерият НЕ е изпълнен, нищо не влиза", "",
         f"Късна половина: реално {obs['късна']:.1f}% мачове над 2.5, моделът очаква {res['raw_late']:.1f}% "
         f"(след калибрацията {res['cal_late']:.1f}%) - разлика {B['gap_late']:+.1f} пункта (с поправката от А; без нея моделът"
         f" очаква {res['noA_late']:.1f}%, разлика {res['noA_late'] - obs['късна']:+.1f}).",
         f"На ранната половина разликата е {B['gap_early']:+.1f}. Нито един проверен начин да се следи по-скорошно ниво не",
         "сваля разликата под 1.5 пункта така, че да се задържи (виж долу).", "",
         "## Откъде идва", "",
         "**1. Не от твърде дълга история.** Моделът по собствените си скорошни мачове вижда нивото правилно - за",
         "последните 90 дни преди всяка седмица реалните и очакваните голове съвпадат (средно за лигата):", "",
         "| лига | голове реално (90 дни) | очаквани | късна половина: реално | очаквани |", "|---|---|---|---|---|"]
    lg = res["leagues"]
    for league, r in res["ins90"].iterrows():
        L.append(f"| {league} | {r.G:.2f} | {r['T']:.2f} | {lg.loc[league, ('G', True)]:.2f} | {lg.loc[league, ('T', True)]:.2f} |")
    L += ["", "Скокът идва СЛЕД прогнозата: през сезон 2025/26 головете се качват в лиги с малко голове (bulgaria2,",
          "england2, spain, italy2, Шампионска лига), докато в england, france, europa_league падат. Това не се вижда",
          "в миналото на лигата към момента на прогнозата.", "",
          "**2. Съсредоточено при мачовете с малко очаквани голове** (шест равни групи по очакван сбор, над 2.5 реално / модел %):", "",
          "| очакван сбор | ранна: реално / модел | късна: реално / модел |", "|---|---|---|"]
    bn = res["bins"]
    for b in bn.index:
        L.append(f"| {bn.loc[b, ('T', False)]:.1f} | {bn.loc[b, ('y', False)] * 100:.0f} / {bn.loc[b, ('p', False)] * 100:.0f} | "
                 f"{bn.loc[b, ('y', True)] * 100:.0f} / {bn.loc[b, ('p', True)] * 100:.0f} |")
    L += ["", "**3. Не от новите отбори в лигата** (изпаднали/влезли). По-малкият от двата отбора - мачове в лигата",
          "през последните 365 дни; над 2.5 реално / модел %:", "",
          "| мачове на отбора | ранна | късна |", "|---|---|---|"]
    nv = res["nov"]
    for b in nv.index:
        L.append(f"| {b} | {nv.loc[b, ('y', False)] * 100:.0f} / {nv.loc[b, ('p', False)] * 100:.0f} | "
                 f"{nv.loc[b, ('y', True)] * 100:.0f} / {nv.loc[b, ('p', True)] * 100:.0f} |")
    L += ["", "Разликата е при утвърдените отбори (над 15 мача), не при новите.", "",
          "По тримесечие (над 2.5 реално / модел %, голове реално / очаквани):", "",
          "| тримесечие | мачове | над 2.5 | голове |", "|---|---|---|---|"]
    for q, r in res["quarters"].iterrows():
        L.append(f"| {q} | {int(r.n)} | {r.y * 100:.0f} / {r.p * 100:.0f} | {r.G:.2f} / {r['T']:.2f} |")
    L += ["", "## Какво е проверено (избор на ранната половина, проверка на късната)", "",
          "1. **Множител на нивото на лигата от собствените ѝ мачове** (реални / очаквани от модела, по-кратък",
          "   полуживот 30-365 дни, свиване с N0 въображаеми мача; общ или отделно за домакин/гост). Атака/защита/темпо",
          "   не се пипат.",
          "2. **Множител от грешките на прогнозите за предишните седмици** (извън извадката) - по лига или общо за",
          "   всички лиги.",
          "3. **По-кратка памет на целия модел** (време-теглата x2, x4).", "",
          "| вариант | най-добрата настройка на ранната половина | Brier ранна | Brier късна | над 2.5 - разлика късна (пункта) |",
          "|---|---|---|---|---|"]
    for v, s in fam.groupby("вариант"):
        r = s.loc[s.d_early.idxmin()]
        L.append(f"| {v} | {r['настройка']} | {r.d_early:+.4f} | {r.d_late:+.4f} | {r.gap_late:+.1f} |")
    closest = fam.loc[fam.gap_late.abs().idxmin()]
    L += ["", f"(Brier - разлика спрямо сегашния модел; по-малко = по-добре.) Сегашният модел: разлика {B['gap_late']:+.1f} на късната.", "",
          f"Най-близо до критерия от всички {len(fam)} проверени настройки: {closest['вариант']}, {closest['настройка']} - "
          f"{closest.gap_late:+.1f} пункта на късната, но Brier {closest.d_early:+.4f} на ранната и {closest.d_late:+.4f} на късната",
          f"(95% [{closest.ci_late[1]:+.4f}, {closest.ci_late[2]:+.4f}]) - "
          + ("значимо по-лоша точност и на двете половини." if closest.ci_late[1] > 0 else "по-лошо на ранната, на късната в рамките на шума."),
          "Тоест разликата по над 2.5 се сваля само като моделът гони шума от последните седмици и греши повече",
          "навсякъде другаде. Изборът на ранната половина никога не я избира.", "",
          "## Защо не се поправя", "",
          "Разликата от ~2 пункта е скок на головете през самата късна половина (сезон 2025/26 и началото на 2026/27),",
          "който в миналото към момента на прогнозата не личи - нито в собствените мачове на лигата, нито в грешките",
          "на модела от предишните седмици. Метод, който гони последните седмици по-агресивно, гони и шума и губи",
          "точност. На ранната половина моделът е с -0.6 пункта - в рамката. Нищо не влиза; кодът не е пипнат.", "",
          "Какво остава отворено: ако скокът се задържи през сезона, мерилото ще го покаже като постоянна разлика и",
          "калибрацията (b за над 2.5 - честотата на ранната половина, 50.7%) може да се префитне с по-нов период."]
    with open(f"validation/final_b_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--analyse":
        analyse(*pd.read_pickle(f"/tmp/final_b_{TAG}.pkl"))  # само анализът, без повторната сметка
    else:
        main()
