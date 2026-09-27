"""
validation/otbrana_20260927.py - задачата „сила на състава, втори опит (отбрана + удари)“
(27.09.2026). Само измерване, животът не се пипа.

Въпрос: ако към сегашния модел добавим отсъстващите от отбранителната тройка (САМО за
допуснатите голове) и изгубените удари на най-полезните (САМО за вкараните), по-точна ли
става ОКОНЧАТЕЛНАТА прогноза (след обявяване на съставите)?

Настройки (записани в PROGRESS_OTBRANA.md т.2 ПРЕДИ резултатите, commit 04493e9):
  0 контрол - без ковариата; А def_abs; Б def_w; В def_abs + att_shots; Г def_dev;
  Д def_dev + att_dev. Ковариатите - validation/otbrana_features.py, фитърът -
  validation/otbrana_fit.py (отделни коефициенти за вкарани/допуснати).

МЕТОД = мерилото на Етап 4 (validation/sila_igrach_20260924.py): СЪЩИТЕ 6400 мача
(fixture_id от sila_igrach_20260924_matches.csv), префитване всяка седмица само от мачове
преди понеделника; първенствата - tri_fit с живите настройки (контузии, xG смес),
евротурнирите - общият евро модел (ковариатите влизат за всички мачове от историята му).
ИЗБОР - най-нисък Brier (11-те изхода) на ранната половина (< 2025-09-23) сред А-Д;
ПРОВЕРКА - късната, веднъж. КРИТЕРИЙ: 95% bootstrap интервал на разликата в Brier на
късната изцяло под 0 И наклон на калибрацията 0.9-1.1 за всеки пазар (суров и показван).

Изход: validation/otbrana_20260927.md, .csv (настройки), _leagues.csv (по лига и
първенства/евротурнири), _matches.csv (по мач).
Употреба: venv/bin/python3 validation/otbrana_20260927.py [--analyse]
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
import final_a_20260924 as fa  # noqa: E402
import final_b_20260924 as fb  # noqa: E402
import final_v_20260924 as fv  # noqa: E402
import football_lib as fl  # noqa: E402
import kalibraciq_xg_20260923 as kx  # noqa: E402
import otbrana_features as OFE  # noqa: E402
import otbrana_fit as OF  # noqa: E402
import razpredelenie_b_20260923 as rb  # noqa: E402
import tri_v_euro as E  # noqa: E402

TAG = "20260927"
S = fb.S
INJ = fb.INJ
LEAGUES = OFE.LEAGUES
BENCH = "validation/sila_igrach_20260924_matches.csv"
RES_PKL = f"/tmp/otbrana_{TAG}.pkl"
# (име, атакуващи ковариати, отбранителни ковариати)
SETTINGS = [
    ("0 контрол", [], []),
    ("А отбрана брой", [], ["def_abs"]),
    ("Б отбрана минути", [], ["def_w"]),
    ("В А + удари", ["att_shots"], ["def_abs"]),
    ("Г отбрана отклонение", [], ["def_dev"]),
    ("Д Г + удари отклонение", ["att_dev"], ["def_dev"]),
]
GROUPS4 = ["1x2", "ou25", "btts", "team_total"]


def bench_ids():
    return set(pd.read_csv(BENCH, usecols=["fixture_id"]).fixture_id)


def attach(df, F, cols):
    out = df.copy()
    for side, col in (("xh", "home_team"), ("xa", "away_team")):
        m = F.rename(columns={"team": col})[["fixture_id", col] + cols]
        out = out.merge(m.rename(columns={c: f"{side}_{c}" for c in cols}), on=["fixture_id", col], how="left")
        for c in cols:
            out[f"{side}_{c}"] = out[f"{side}_{c}"].fillna(0.0)
    return out


def names(own, opp):
    return ([f"xh_{c}" for c in own], [f"xa_{c}" for c in own], [f"xh_{c}" for c in opp], [f"xa_{c}" for c in opp])


def run_domestic(league, own, opp, F, ids):
    df = fl.load_league_data(league)
    if own or opp:
        df = attach(df, F, own + opp)
    teams, n, ti = fl.get_team_index(df)
    fin, test = fb.test_weeks(df)
    test = fin[fin.fixture_id.isin(ids)].copy()
    test["week"] = test["date"] - pd.to_timedelta(test["date"].dt.weekday, unit="D")
    xi = fl.LEAGUE_XI.get(league, fl.XI)
    cfg = S["FT_FIT_SETTINGS"].get(league, {})
    kw = dict(reg_mult=cfg.get("reg_mult", 1), intercept=cfg.get("intercept", False),
              tempo_mult=float(cfg.get("tempo_mult", 1.0)))
    direct = "home_injuries" in df.columns and league not in S["NO_INJURY_MODEL_LEAGUES"]
    xgw = S["XG_BLEND_WEIGHTS"].get(league, 0.0)
    xgdf = df.dropna(subset=["home_xg", "away_xg"]) if xgw else None
    oh, oa, dh, da = names(own, opp)
    cov = dict(own_h=oh, own_a=oa, opp_h=dh, opp_a=da)
    xa = xb = None
    rows = []
    for week, block in test.groupby("week", sort=True):
        hist = fin[fin["date"] < week]
        if direct:
            A = OF.fit_domestic(hist, week, ti, n, xi, kind="direct", cov_cols=INJ, x0=xa, **cov, **kw)
        else:
            A = OF.fit_domestic(hist, week, ti, n, xi, kind="goals", x0=xa, **cov, **kw)
        xa = A["x"]
        B = None
        if xgw:
            hx = xgdf[xgdf["date"] < week]
            if len(hx) >= kx.MIN_XG_HISTORY:
                from tri_fit import fit as tfit
                B = tfit(hx, week, ti, n, xi, kind="xg", obs_cols=("home_xg", "away_xg"), x0=xb, **kw)
                xb = B["x"]
        hc = block[INJ[0]].fillna(0.0).to_numpy(float) if direct else None
        ac = block[INJ[1]].fillna(0.0).to_numpy(float) if direct else None
        X = {k: (block[v].to_numpy(float) if v else None) for k, v in
             (("XHo", oh), ("XAo", oa), ("XHd", dh), ("XAd", da))}
        lam0, mu0 = OF.lambdas_domestic(A, ti, block["home_team"], block["away_team"], hc, ac)
        lam, mu = OF.lambdas_domestic(A, ti, block["home_team"], block["away_team"], hc, ac, **X)
        if B is not None:
            # xG смесът е върху очакваните голове; множителят на състава се прилага върху сместа
            lb, mb = fb._vec_lambdas(B, ti, block["home_team"], block["away_team"])
            lam = (xgw * lb + (1 - xgw) * lam0) * (lam / lam0)
            mu = (xgw * mb + (1 - xgw) * mu0) * (mu / mu0)
        rows.append(frame(league, block, lam, mu, A))
    return pd.concat(rows, ignore_index=True)


def frame(league, block, lam, mu, m):
    return pd.DataFrame({"league": league, "fixture_id": block["fixture_id"].to_numpy(),
                         "date": block["date"].dt.date.astype(str).to_numpy(),
                         "hg": block["home_goals"].astype(int).to_numpy(),
                         "ag": block["away_goals"].astype(int).to_numpy(),
                         "lam": lam, "mu": mu, "rho": m["rho"],
                         "b_own": [list(m["b_own"])] * len(block), "b_opp": [list(m["b_opp"])] * len(block)})


def run_cup(cup, own, opp, F, ids):
    g = dict(S["EURO_FIT_SETTINGS"][cup])
    allm, group = E.load_all(fl.load_league_data)
    if own or opp:
        allm = attach(allm, F, own + opp)
    ix = E.Index(allm, group)
    df = fl.load_league_data(cup)
    fin, _ = fb.test_weeks(df)
    test = fin[fin.fixture_id.isin(ids)].copy()
    test["week"] = test["date"] - pd.to_timedelta(test["date"].dt.weekday, unit="D")
    oh, oa, dh, da = names(own, opp)
    cupx = allm[allm.comp == cup].set_index("fixture_id")
    x0 = None
    rows = []
    for week, block in test.groupby("week", sort=True):
        m = OF.fit_euro(allm[allm["date"] < week], week, ix, x0=x0, own_h=oh, own_a=oa, opp_h=dh, opp_a=da, **g)
        x0 = m["x"]
        X = {k: (cupx.loc[block["fixture_id"], v].to_numpy(float) if v else None) for k, v in
             (("XHo", oh), ("XAo", oa), ("XHd", dh), ("XAd", da))}
        lam, mu = OF.lambdas_euro(m, ix, cup, block["home_team"], block["away_team"], **X)
        rows.append(frame(cup, block, lam, mu, m))
    return pd.concat(rows, ignore_index=True)


def job(args):
    name, own, opp, league = args
    F = pd.read_pickle(OFE.OUT_PKL) if (own or opp) else None
    ids = bench_ids()
    fn = run_cup if league in S["EURO_FIT_SETTINGS"] else run_domestic
    return fn(league, own, opp, F, ids).assign(setting=name)


def main():
    if not os.path.exists(OFE.OUT_PKL):
        OFE.build()
    order = sorted(LEAGUES, key=lambda x: x not in S["EURO_FIT_SETTINGS"])
    jobs = [(s[0], s[1], s[2], lg) for s in SETTINGS for lg in order]
    with Pool(15) as pool:
        parts = pool.map(job, jobs, chunksize=1)
    res = pd.concat(parts, ignore_index=True)
    res.to_pickle(RES_PKL)
    analyse(res)


def evaluate(t):
    P = fb.probs(t.lam.to_numpy(), t.mu.to_numpy(), t.rho.to_numpy())
    Y = fa.ytrue(t)
    return P, Y, rb.brier_rows(P, Y)


def calib(P, Y, early, mask):
    Pd = pd.DataFrame(np.asarray(P), columns=bf.CODES)
    Yd = pd.DataFrame(Y, columns=bf.CODES)
    Pc = fv.live_calibrate(Pd)
    raw = {g: fv.calib_a(Pd, Yd, early, mask, [c for c in bf.CODES if bf.GROUPS[c] == g]) for g in GROUPS4}
    shown = {g: fv.calib_a(Pc, Yd, early, mask, [c for c in bf.CODES if bf.GROUPS[c] == g]) for g in GROUPS4}
    return raw, shown


def analyse(res):
    bench = pd.read_csv(BENCH).set_index(["league", "fixture_id"])
    nm = [s[0] for s in SETTINGS]
    base = res[res.setting == nm[0]].sort_values(["league", "fixture_id"]).reset_index(drop=True)
    control = float(np.abs(bench.loc[list(zip(base.league, base.fixture_id)), "lam_сега"].to_numpy()
                           - base.lam.to_numpy()).max())
    early = (pd.to_datetime(base.date) < kx.CUT).to_numpy()
    F = pd.read_pickle(OFE.OUT_PKL)
    okset = set(zip(F[F.status == "ok"].fixture_id, F[F.status == "ok"].team))
    names_ = {}
    for lg in LEAGUES:
        m = pd.read_csv(f"{lg}_merged_full.csv", usecols=["fixture_id", "home_team", "away_team"])
        names_.update({int(f): (h, a) for f, h, a in zip(m.fixture_id, m.home_team, m.away_team)})
    known = np.array([(f, names_[f][0]) in okset and (f, names_[f][1]) in okset for f in base.fixture_id])
    P0, Y, b0 = evaluate(base)
    rows, briers = [], {}
    for s in nm:
        t = res[res.setting == s].sort_values(["league", "fixture_id"]).reset_index(drop=True)
        assert (t.fixture_id.to_numpy() == base.fixture_id.to_numpy()).all()
        P, _, br = evaluate(t)
        briers[s] = br
        raw_l, shown_l = calib(P, Y, early, ~early)
        raw_e, _ = calib(P, Y, early, early)
        d = kx.ci(br[~early], b0[~early])
        dk = kx.ci(br[~early & known], b0[~early & known])
        bo = np.array(t.b_own.tolist(), dtype=float)
        bd = np.array(t.b_opp.tolist(), dtype=float)
        rows.append({"настройка": s, "brier_ранна": br[early].mean(), "brier_късна": br[~early].mean(),
                     "d_ранна": br[early].mean() - b0[early].mean(), "d_късна": d[0], "d_късна_lo": d[1],
                     "d_късна_hi": d[2], "d_късна_известни": dk[0], "d_късна_известни_lo": dk[1],
                     "d_късна_известни_hi": dk[2],
                     **{f"a_{g}_късна": v for g, v in raw_l.items()},
                     **{f"a_{g}_късна_показ": v for g, v in shown_l.items()},
                     **{f"a_{g}_ранна": v for g, v in raw_e.items()},
                     "b_атака_ср": ";".join(f"{x:.4f}" for x in bo.mean(0)) if bo.ndim == 2 and bo.shape[1] else "",
                     "b_отбрана_ср": ";".join(f"{x:.4f}" for x in bd.mean(0)) if bd.ndim == 2 and bd.shape[1] else ""})
    tab = pd.DataFrame(rows)
    tab.round(6).to_csv(f"validation/otbrana_{TAG}.csv", index=False)
    cand = tab[tab["настройка"] != nm[0]]
    best = cand.loc[cand["d_ранна"].idxmin(), "настройка"]
    tb = res[res.setting == best].sort_values(["league", "fixture_id"]).reset_index(drop=True)
    bb = briers[best]
    kind = np.where(base.league.str.contains("league"), "евротурнири", "първенства")
    lg_rows = []
    for key, mask in [(lg, (base.league == lg).to_numpy()) for lg in LEAGUES] + \
                     [(k, kind == k) for k in ("първенства", "евротурнири")]:
        for half, hm in (("ранна", early), ("късна", ~early)):
            mm = mask & hm
            d = kx.ci(bb[mm], b0[mm])
            lg_rows.append({"разрез": key, "половина": half, "мачове": int(mm.sum()),
                            "с известен състав": int((mm & known).sum()),
                            "brier_сега": b0[mm].mean(), "brier_нова": bb[mm].mean(),
                            "разлика": d[0], "lo": d[1], "hi": d[2]})
    lgt = pd.DataFrame(lg_rows)
    lgt.round(6).to_csv(f"validation/otbrana_{TAG}_leagues.csv", index=False)
    mt = base[["league", "fixture_id", "date", "hg", "ag"]].copy()
    mt["lam_сега"], mt["mu_сега"] = base.lam, base.mu
    for s in nm[1:]:
        t = res[res.setting == s].sort_values(["league", "fixture_id"]).reset_index(drop=True)
        mt[f"lam_{s[0]}"], mt[f"mu_{s[0]}"] = t.lam, t.mu
    mt["brier_сега"], mt["brier_избрана"] = b0, bb
    mt.round(6).to_csv(f"validation/otbrana_{TAG}_matches.csv", index=False)
    print(tab.round(5).to_string())
    print(lgt.round(5).to_string())
    print("control", control, "best", best, "known", known.sum(), len(known))
    return tab, lgt, best, control, early, known, base


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--analyse":
        analyse(pd.read_pickle(RES_PKL))
    else:
        main()
