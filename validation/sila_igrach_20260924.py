"""
validation/sila_igrach_20260924.py - ZADACHA_GOLQMA.md, Етап 4 (24.09.2026).
Силата на конкретните единайсет като ковариата в модела - само измерване.

Въпрос: ако към сегашния модел (живите настройки: FT_FIT_SETTINGS, контузии, xG смес,
общ евро модел - повторната сметка от validation/final_b_20260924.py) добавим силата
на състава (validation/sila_features.py - "с него / без него" и производителност,
смятани само от мачове преди седмицата), по-точни ли стават прогнозите?

МЕТОД = мерилото (backtest_full.py): последните 730 дни на всяка лига, префитване всяка
седмица само от мачове преди понеделника. Лиги: 10-те със статистика по играчи
(7 първи дивизии + 3 евротурнира; евротурнирите - общият евро модел, в който
ковариатите влизат за всички мачове от историята му). Ковариатите - validation/sila_fit.py
(log lam += X_дом.b_свои + X_гост.b_чужди; същото огледално за mu).

ИЗБОР на настройката (свиване K, K2, кои ковариати) - САМО по ранната половина
(дата < 2025-09-23, kalibraciq_xg_20260923.CUT): най-нисък Brier (11-те изхода).
ПРОВЕРКА - късната половина, чиста. КРИТЕРИЙ (задачата): Brier значимо по-добър на
късната (95% bootstrap интервал на разликата изцяло под 0) И коефициентът на
калибрация a (наклонът; b - честотата на ранната половина, final_v.calib_a) за
1X2 в 0.9-1.1 (показани и останалите пазари).

Изход: validation/sila_igrach_20260924.md, sila_igrach_20260924.csv (всички настройки),
sila_igrach_20260924_leagues.csv (по лига), sila_igrach_20260924_matches.csv (по мач).
Употреба: venv/bin/python3 validation/sila_igrach_20260924.py [--analyse]
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
import razpredelenie_b_20260923 as rb  # noqa: E402
import sila_features as sf  # noqa: E402
import sila_fit as SF  # noqa: E402
import tri_v_euro as E  # noqa: E402

TAG = "20260924"
S = fb.S
INJ = fb.INJ
FEAT_DIR = "/tmp/sila_feat"
# (име, K, K2, ковариати); "сума" = суровата сила на единайсетте, без "минус обичайната"
SETTINGS = [
    ("без състав", None, None, []),
    ("с/без K=10", 10.0, 10.0, ["onoff"]),
    ("с/без K=30", 30.0, 10.0, ["onoff"]),
    ("с/без K=100", 100.0, 10.0, ["onoff"]),
    ("произв. K2=5", 30.0, 5.0, ["prod"]),
    ("произв. K2=20", 30.0, 20.0, ["prod"]),
    ("двете K=30 K2=10", 30.0, 10.0, ["onoff", "prod"]),
    ("с/без сума K=30", 30.0, 10.0, ["onoff_raw"]),
    ("произв. сума K2=5", 30.0, 5.0, ["prod_raw"]),
    ("произв. сума K2=20", 30.0, 20.0, ["prod_raw"]),
    ("двете сума K=30 K2=10", 30.0, 10.0, ["onoff_raw", "prod_raw"]),
    ("всички четири K=30 K2=10", 30.0, 10.0, ["onoff", "prod", "onoff_raw", "prod_raw"]),
]

def feat_path(K, K2):
    return f"{FEAT_DIR}/F_{K:g}_{K2:g}.pkl"


def build_features():
    os.makedirs(FEAT_DIR, exist_ok=True)
    PM, TM = sf.load_tables()
    for K, K2 in sorted({(s[1], s[2]) for s in SETTINGS if s[1] is not None}):
        p = feat_path(K, K2)
        if not os.path.exists(p):
            sf.lineup_features(PM, TM, K=K, K2=K2).to_pickle(p)
    return PM, TM


def attach(df, F, feats):
    """Колони xh_<f>, xa_<f> към мачовете (0, ако съставът не е известен)."""
    out = df.copy()
    for side, col in (("xh", "home_team"), ("xa", "away_team")):
        m = F.rename(columns={"team": col})[["fixture_id", col] + [f"x_{f}" for f in feats]]
        out = out.merge(m, on=["fixture_id", col], how="left")
        for f in feats:
            out[f"{side}_{f}"] = out.pop(f"x_{f}").fillna(0.0)
    return out


def run_domestic(league, feats, F):
    df = fl.load_league_data(league)
    if feats:
        df = attach(df, F, feats)
    teams, n, ti = fl.get_team_index(df)
    fin, test = fb.test_weeks(df)
    xi = fl.LEAGUE_XI.get(league, fl.XI)
    cfg = S["FT_FIT_SETTINGS"].get(league, {})
    kw = dict(reg_mult=cfg.get("reg_mult", 1), intercept=cfg.get("intercept", False),
              tempo_mult=float(cfg.get("tempo_mult", 1.0)))
    direct = "home_injuries" in df.columns and league not in S["NO_INJURY_MODEL_LEAGUES"]
    xgw = S["XG_BLEND_WEIGHTS"].get(league, 0.0)
    xgdf = df.dropna(subset=["home_xg", "away_xg"]) if xgw else None
    eh = [f"xh_{f}" for f in feats]
    ea = [f"xa_{f}" for f in feats]
    xa = xb = None
    rows = []
    for week, block in test.groupby("week", sort=True):
        hist = fin[fin["date"] < week]
        if direct:
            A = SF.fit_domestic(hist, week, ti, n, xi, kind="direct", cov_cols=INJ, x0=xa,
                                extra_h=eh, extra_a=ea, **kw)
        else:
            A = SF.fit_domestic(hist, week, ti, n, xi, kind="goals", x0=xa, extra_h=eh, extra_a=ea, **kw)
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
        XH = block[eh].to_numpy(float) if feats else None
        XA = block[ea].to_numpy(float) if feats else None
        lam, mu = SF.lambdas_domestic(A, ti, block["home_team"], block["away_team"], hc, ac, XH, XA)
        if B is not None:
            lb, mb = fb._vec_lambdas(B, ti, block["home_team"], block["away_team"])
            lam, mu = xgw * lb + (1 - xgw) * lam, xgw * mb + (1 - xgw) * mu
        rows.append(pd.DataFrame({"league": league, "fixture_id": block["fixture_id"].to_numpy(),
                                  "date": block["date"].dt.date.astype(str).to_numpy(),
                                  "hg": block["home_goals"].astype(int).to_numpy(),
                                  "ag": block["away_goals"].astype(int).to_numpy(),
                                  "lam": lam, "mu": mu, "rho": A["rho"],
                                  "b_own": [list(A["b_own"])] * len(block), "b_opp": [list(A["b_opp"])] * len(block)}))
    return pd.concat(rows, ignore_index=True)


def run_cup(cup, feats, F):
    g = dict(S["EURO_FIT_SETTINGS"][cup])
    allm, group = E.load_all(fl.load_league_data)
    if feats:
        allm = attach(allm, F, feats)
    ix = E.Index(allm, group)
    df = fl.load_league_data(cup)
    fin, test = fb.test_weeks(df)
    eh = [f"xh_{f}" for f in feats]
    ea = [f"xa_{f}" for f in feats]
    cupx = allm[allm.comp == cup].set_index("fixture_id")
    x0 = None
    rows = []
    for week, block in test.groupby("week", sort=True):
        m = SF.fit_euro(allm[allm["date"] < week], week, ix, x0=x0, extra_h=eh, extra_a=ea, **g)
        x0 = m["x"]
        XH = cupx.loc[block["fixture_id"], eh].to_numpy(float) if feats else None
        XA = cupx.loc[block["fixture_id"], ea].to_numpy(float) if feats else None
        lam, mu = SF.lambdas_euro(m, ix, cup, block["home_team"], block["away_team"], XH, XA)
        rows.append(pd.DataFrame({"league": cup, "fixture_id": block["fixture_id"].to_numpy(),
                                  "date": block["date"].dt.date.astype(str).to_numpy(),
                                  "hg": block["home_goals"].astype(int).to_numpy(),
                                  "ag": block["away_goals"].astype(int).to_numpy(),
                                  "lam": lam, "mu": mu, "rho": m["rho"],
                                  "b_own": [list(m["b_own"])] * len(block), "b_opp": [list(m["b_opp"])] * len(block)}))
    return pd.concat(rows, ignore_index=True)


def job(args):
    name, K, K2, feats, league = args
    F = pd.read_pickle(feat_path(K, K2)) if feats else None
    fn = run_cup if league in S["EURO_FIT_SETTINGS"] else run_domestic
    return fn(league, feats, F).assign(setting=name)


def main():
    PM, TM = build_features()
    order = sorted(sf.LEAGUES, key=lambda x: x not in S["EURO_FIT_SETTINGS"])
    jobs = [(s[0], s[1], s[2], s[3], lg) for s in SETTINGS for lg in order]
    with Pool(15) as pool:
        parts = pool.map(job, jobs, chunksize=1)
    res = pd.concat(parts, ignore_index=True)
    res.to_pickle(f"/tmp/sila_igrach_{TAG}.pkl")
    analyse(res, PM)


def evaluate(t, base_br, early):
    P = fb.probs(t.lam.to_numpy(), t.mu.to_numpy(), t.rho.to_numpy())
    Y = fa.ytrue(t)
    br = rb.brier_rows(P, Y)
    return P, Y, br


def calib(P, Y, early, mask):
    Pd = pd.DataFrame(P, columns=bf.CODES) if not isinstance(P, pd.DataFrame) else P
    Yd = pd.DataFrame(Y, columns=bf.CODES)
    out = {}
    for g in ["1x2", "ou25", "btts", "team_total"]:
        codes = [c for c in bf.CODES if bf.GROUPS[c] == g]
        out[g] = fv.calib_a(Pd, Yd, early, mask, codes)
    return out


def analyse(res, PM=None):
    allt, _ = pd.read_pickle(sf.PKL)
    live = allt[allt.xi_mult == 1.0].set_index(["league", "fixture_id"])
    names = [s[0] for s in SETTINGS]
    base = res[res.setting == names[0]].sort_values(["league", "fixture_id"]).reset_index(drop=True)
    control = float(np.abs(live.loc[list(zip(base.league, base.fixture_id)), "lam"].to_numpy() - base.lam.to_numpy()).max())
    early = (pd.to_datetime(base.date) < kx.CUT).to_numpy()
    if PM is None:
        PM, _ = sf.load_tables()
    has_players = base.fixture_id.isin(set(PM.fixture_id)).to_numpy()
    P0, Y, b0 = evaluate(base, None, early)
    rows, per_match = [], {"base": b0}
    for nm in names:
        t = res[res.setting == nm].sort_values(["league", "fixture_id"]).reset_index(drop=True)
        assert (t.fixture_id.to_numpy() == base.fixture_id.to_numpy()).all()
        P, _, br = evaluate(t, b0, early)
        per_match[nm] = br
        cl = calib(P, Y, early, ~early)
        ce = calib(P, Y, early, early)
        lo_hi = kx.ci(br[~early], b0[~early])
        lo_hi_p = kx.ci(br[~early & has_players], b0[~early & has_players])
        bo = np.array(t.b_own.tolist(), dtype=float) if len(t.b_own.iloc[0]) else np.zeros((len(t), 0))
        bd = np.array(t.b_opp.tolist(), dtype=float) if len(t.b_opp.iloc[0]) else np.zeros((len(t), 0))
        rows.append({"настройка": nm, "brier_ранна": br[early].mean(), "brier_късна": br[~early].mean(),
                     "d_ранна": br[early].mean() - b0[early].mean(), "d_късна": lo_hi[0],
                     "d_късна_lo": lo_hi[1], "d_късна_hi": lo_hi[2],
                     "d_късна_с_играчи": lo_hi_p[0], "d_късна_с_играчи_lo": lo_hi_p[1], "d_късна_с_играчи_hi": lo_hi_p[2],
                     **{f"a_{g}_късна": v for g, v in cl.items()}, **{f"a_{g}_ранна": v for g, v in ce.items()},
                     "b_свои_ср": ";".join(f"{x:.3f}" for x in bo.mean(0)) if bo.shape[1] else "",
                     "b_чужди_ср": ";".join(f"{x:.3f}" for x in bd.mean(0)) if bd.shape[1] else ""})
    tab = pd.DataFrame(rows)
    tab.round(6).to_csv(f"validation/sila_igrach_{TAG}.csv", index=False)
    cand = tab[tab["настройка"] != names[0]]
    best = cand.loc[cand["d_ранна"].idxmin(), "настройка"]
    tb = res[res.setting == best].sort_values(["league", "fixture_id"]).reset_index(drop=True)
    Pb, _, bb = evaluate(tb, b0, early)
    lg_rows = []
    for lg in sf.LEAGUES:
        m = (base.league == lg).to_numpy()
        for half, hm in (("ранна", early), ("късна", ~early)):
            mm = m & hm
            if mm.sum() < 5:
                continue
            d = kx.ci(bb[mm], b0[mm])
            lg_rows.append({"лига": lg, "половина": half, "мачове": int(mm.sum()),
                            "с играчи": int((mm & has_players).sum()),
                            "brier_сега": b0[mm].mean(), "brier_със_състав": bb[mm].mean(),
                            "разлика": d[0], "lo": d[1], "hi": d[2]})
    lgt = pd.DataFrame(lg_rows)
    lgt.round(6).to_csv(f"validation/sila_igrach_{TAG}_leagues.csv", index=False)
    mt = base[["league", "fixture_id", "date", "hg", "ag"]].copy()
    mt["lam_сега"], mt["mu_сега"] = base.lam, base.mu
    mt["lam_състав"], mt["mu_състав"] = tb.lam, tb.mu
    mt["brier_сега"], mt["brier_състав"] = b0, bb
    mt.round(6).to_csv(f"validation/sila_igrach_{TAG}_matches.csv", index=False)
    write_md(tab, lgt, best, control, early, has_players, base)


def write_md(tab, lgt, best, control, early, has_players, base):
    r = tab.set_index("настройка").loc[best]
    sig = r.d_късна_hi < 0
    a1 = r["a_1x2_късна"]
    ok = sig and 0.9 <= a1 <= 1.1
    b = tab.iloc[0]
    L = [f"# Сила на играч / състав като ковариата - {TAG}", "",
         "ZADACHA_GOLQMA.md, Етап 4. Скриптове: `validation/sila_igrach_20260924.py` (метод в docstring-а),",
         "`validation/sila_features.py` (силата на играч и на единайсетте), `validation/sila_fit.py` (фитърите).",
         "Всички настройки: `sila_igrach_20260924.csv`; по лига: `sila_igrach_20260924_leagues.csv`; по мач:",
         "`sila_igrach_20260924_matches.csv`.", "",
         f"Мачове: {len(base)} (10-те лиги със статистика по играчи, последните 730 дни), от тях {int(has_players.sum())}",
         f"със статистика по играчи за самия мач. Ранна половина (избор): {int(early.sum())}, късна (проверка): {int((~early).sum())}.",
         f"Контрол: повторната сметка без състав = сегашния модел (final_b), макс. разлика в очакваните голове {control:.1e}.", "",
         "## Резултат", "",
         f"Избрана по ранната половина: **{best}**. На късната половина: Brier {r.brier_късна:.5f} срещу {b.brier_късна:.5f} сега,",
         f"разлика {r.d_късна:+.5f} (95% [{r.d_късна_lo:+.5f}, {r.d_късна_hi:+.5f}]); само мачовете със статистика по играчи:",
         f"{r.d_късна_с_играчи:+.5f} [{r.d_късна_с_играчи_lo:+.5f}, {r.d_късна_с_играчи_hi:+.5f}].",
         f"Коефициент на калибрация (наклон) на късната: 1X2 {a1:.3f} (сега {b['a_1x2_късна']:.3f}), над/под 2.5",
         f"{r['a_ou25_късна']:.3f} ({b['a_ou25_късна']:.3f}), двата отбора {r['a_btts_късна']:.3f} ({b['a_btts_късна']:.3f}),",
         f"отборни голове {r['a_team_total_късна']:.3f} ({b['a_team_total_късна']:.3f}).", "",
         ("**КРИТЕРИЯТ Е ИЗПЪЛНЕН** - значимо по-добър Brier на късната и 1X2 наклон в 0.9-1.1." if ok else
          "**КРИТЕРИЯТ НЕ Е ИЗПЪЛНЕН** - " + ("разликата на късната не е значима (интервалът минава през 0)"
                                               if not sig else "наклонът за 1X2 е извън 0.9-1.1")
          + ". Не се предлага влизане в живия код."), "",
         "## Всички настройки (разлика в Brier спрямо сегашния модел; по-малко = по-добре)", "",
         "| настройка | ранна | късна | 95% късна | късна, с играчи | 1X2 наклон късна | b свои | b чужди |",
         "|---|---|---|---|---|---|---|---|"]
    for _, x in tab.iterrows():
        L.append(f"| {x['настройка']} | {x.d_ранна:+.5f} | {x.d_късна:+.5f} | [{x.d_късна_lo:+.5f}, {x.d_късна_hi:+.5f}] | "
                 f"{x.d_късна_с_играчи:+.5f} | {x['a_1x2_късна']:.3f} | {x['b_свои_ср']} | {x['b_чужди_ср']} |")
    L += ["", "(b - средните коефициенти пред ковариатите през седмиците; onoff/prod по реда на колоната.)", "",
          f"## По лига (избраната настройка „{best}“ срещу сегашния модел)", "",
          "| лига | половина | мачове | с играчи | Brier сега | със състав | разлика | 95% |", "|---|---|---|---|---|---|---|---|"]
    for _, x in lgt.iterrows():
        L.append(f"| {x['лига']} | {x['половина']} | {x['мачове']} | {x['с играчи']} | {x.brier_сега:.5f} | "
                 f"{x.brier_със_състав:.5f} | {x.разлика:+.5f} | [{x.lo:+.5f}, {x.hi:+.5f}] |")
    with open(f"validation/sila_igrach_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--analyse":
        analyse(pd.read_pickle(f"/tmp/sila_igrach_{TAG}.pkl"))
    else:
        main()
