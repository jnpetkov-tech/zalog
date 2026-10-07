"""validation/top4_yadro_20261007.py - ZADACHA_MODELI, ЧАСТ 2 (07.10.2026): ядрото за england/germany/spain/france.

Настройките и критерият - validation/top4_yadro_nastroyki_20261007.md (записани преди пускането).
Варианти: А (сегашното), Б (контузии + rho + свиване), В (fit_goals_model без контузии), Г (Б + intercept/tempo_mult).
Методът = validation/final_b_20260924.run_domestic (walk-forward, седмично префитване, tri_fit), само ядрото на 4-те лиги.

Употреба (по ред):
  venv/bin/python3 validation/top4_yadro_20261007.py --check   # tri_fit (нови опции) срещу football_lib; А срещу features/core_lam_mu.csv
  venv/bin/python3 validation/top4_yadro_20261007.py --early   # всички варианти, ранната половина -> избор (записва се, commit)
  venv/bin/python3 validation/top4_yadro_20261007.py --late    # А и избраният, късната половина (веднъж) -> отчет
  venv/bin/python3 validation/top4_yadro_20261007.py --report  # ако няма избран: отчет само от ранната (късната не се пуска)
Изход: validation/top4_yadro_20261007_{check.txt,early.csv,early.md,late.csv,late_matches.csv}, validation/top4_yadro_20261007.md
"""
import json
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
import football_lib as fl  # noqa: E402
import kalibraciq_xg_20260923 as kx  # noqa: E402
import razpredelenie_b_20260923 as rb  # noqa: E402
import tri_fit as tf  # noqa: E402

TAG = "20261007"
V = os.path.join(ROOT, "validation")
LEAGUES = ["england", "germany", "spain", "france"]
VARIANTS = ["А", "Б", "В", "Г"]
EARLY_END = "2025-09-23"
INJ = fb.INJ
S = fb.S
LDR = 15.0
SEL = os.path.join(V, f"top4_yadro_{TAG}_izbor.json")
GROUPS = ["1x2", "ou25", "btts", "team_total"]


def kw_of(league):
    cfg = S["FT_FIT_SETTINGS"].get(league, {})
    return dict(reg_mult=cfg.get("reg_mult", 1), intercept=cfg.get("intercept", False), tempo_mult=float(cfg.get("tempo_mult", 1.0)))


def fit_variant(v, hist, week, ti, n, xi, kw, x0):
    if v == "А":
        return tf.fit(hist, week, ti, n, xi, kind="direct", cov_cols=INJ, x0=x0, **kw)
    if v == "Б":
        return tf.fit(hist, week, ti, n, xi, kind="direct", cov_cols=INJ, dc=True, direct_low_data_extra_reg=LDR,
                      reg_mult=kw["reg_mult"], x0=x0)
    if v == "В":
        return tf.fit(hist, week, ti, n, xi, kind="goals", x0=x0, **kw)
    if v == "Г":
        return tf.fit(hist, week, ti, n, xi, kind="direct", cov_cols=INJ, dc=True, direct_low_data_extra_reg=LDR, x0=x0, **kw)
    raise ValueError(v)


def run(args):
    """(лига, вариант, половина) -> мачовете на половината с lam, mu, rho (като fb.run_domestic, само тестовите мачове)."""
    league, v, half = args
    df = fl.load_league_data(league)
    teams, n, ti = fl.get_team_index(df)
    fin, test = fb.test_weeks(df)
    test = test[(test["date"] < EARLY_END) if half == "early" else (test["date"] >= EARLY_END)]
    xi = fl.LEAGUE_XI.get(league, fl.XI)
    kw = kw_of(league)
    direct = v != "В"
    xgw = S["XG_BLEND_WEIGHTS"].get(league, 0.0)
    xgdf = df.dropna(subset=["home_xg", "away_xg"]) if xgw else None
    xa = xb = None
    out = []
    for week, blk in test.groupby("week", sort=True):
        hist = fin[fin["date"] < week]
        A = fit_variant(v, hist, week, ti, n, xi, kw, xa)
        xa = A["x"]
        B = None
        if xgw:
            hx = xgdf[xgdf["date"] < week]
            if len(hx) >= kx.MIN_XG_HISTORY:
                B = tf.fit(hx, week, ti, n, xi, kind="xg", obs_cols=("home_xg", "away_xg"), x0=xb, **kw)
                xb = B["x"]
        hc = blk[INJ[0]].fillna(0.0).to_numpy(float) if direct else None
        ac = blk[INJ[1]].fillna(0.0).to_numpy(float) if direct else None
        lam, mu = fb._vec_lambdas(A, ti, blk["home_team"], blk["away_team"], hc, ac)
        if B is not None:
            lb, mb = fb._vec_lambdas(B, ti, blk["home_team"], blk["away_team"])
            lam, mu = xgw * lb + (1 - xgw) * lam, xgw * mb + (1 - xgw) * mu
        out.append(pd.DataFrame({"league": league, "variant": v, "week": week, "fixture_id": blk["fixture_id"].to_numpy(),
                                 "date": blk["date"].dt.date.astype(str).to_numpy(), "home": blk["home_team"].to_numpy(),
                                 "away": blk["away_team"].to_numpy(),
                                 "hg": blk["home_goals"].astype(int).to_numpy(), "ag": blk["away_goals"].astype(int).to_numpy(),
                                 "lam": lam, "mu": mu, "rho": A["rho"]}))
    return pd.concat(out, ignore_index=True)


# ----------------------------------------------------------------------------------------------- мерки
def probs(d):
    lam, mu, rho = d["lam"].to_numpy(float), d["mu"].to_numpy(float), d["rho"].to_numpy(float)
    pm = fa.shift(rb.matrices(lam, mu, rho, "poisson", 0), lam, mu, fl.SCORE_DEP_F0, fl.SCORE_DEP_F1)
    return rb.market_probs(pm), pm[:, 1, 1]


def ymat(d):
    from features import layer_lib as L
    return L.y_matrix(d["hg"], d["ag"])


def per_match(d):
    """-> DataFrame по мач: b11, b1x2, ll1x2, b_<група>, p_draw, p_11, p_<изход>."""
    P, p11 = probs(d)
    Y = ymat(d)
    p = P.to_numpy()
    o = pd.DataFrame({"b11": ((p - Y) ** 2).mean(1)})
    i3 = [bf.CODES.index(c) for c in ("home_win", "draw", "away_win")]
    o["b1x2"] = ((p[:, i3] - Y[:, i3]) ** 2).mean(1)
    o["ll1x2"] = -np.log(np.maximum((p[:, i3] * Y[:, i3]).sum(1), 1e-12))
    for g in GROUPS:
        idx = [i for i, c in enumerate(bf.CODES) if bf.GROUPS[c] == g]
        o[f"b_{g}"] = ((p[:, idx] - Y[:, idx]) ** 2).mean(1)
    o["p_11"] = p11
    for i, c in enumerate(bf.CODES):
        o[f"p_{c}"] = p[:, i]
        o[f"y_{c}"] = Y[:, i]
    return o


def boot(x, n=2000, seed=42):
    rng = np.random.default_rng(seed)
    x = np.asarray(x, float)
    m = x[rng.integers(0, len(x), size=(n, len(x)))].mean(1)
    return float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def calib_a(m, base):
    a = {}
    for g in GROUPS:
        num = den = 0.0
        for c in bf.CODES:
            if bf.GROUPS[c] != g:
                continue
            dd = m[f"p_{c}"] - base[c]
            num += (dd * (m[f"y_{c}"] - base[c])).sum()
            den += (dd * dd).sum()
        a[g] = num / den
    return a


def describe(d, m, base):
    real11 = ((d["hg"] == 1) & (d["ag"] == 1)).mean()
    a = calib_a(m, base)
    return {"n": len(d), "b11": m["b11"].mean(), "b1x2": m["b1x2"].mean(), "ll1x2": m["ll1x2"].mean(),
            "draw_model": m["p_draw"].mean(), "draw_real": m["y_draw"].mean(), "p11_model": m["p_11"].mean(), "p11_real": real11,
            **{f"a_{g}": a[g] for g in GROUPS}, "rho_mean": d["rho"].mean()}


def fmt_ci(ci, k=5):
    return f"{ci[0]:+.{k}f} [{ci[1]:+.{k}f}; {ci[2]:+.{k}f}]"


def base_freq(early_all):
    m = per_match(early_all)
    return {c: m[f"y_{c}"].mean() for c in bf.CODES}


# ----------------------------------------------------------------------------------------------- стъпки
def check():
    """1) tri_fit (direct + dc + свиване) срещу новия football_lib.fit_goals_direct_covariate - една седмица на лига, вариант Б и Г;
    2) А от този скрипт срещу features/core_lam_mu.csv (същият път, друг начален прозорец -> малки разлики от топлия старт)."""
    lines = ["# Проверка на бързия фитър за новите опции (ZADACHA_МОДЕЛИ, ЧАСТ 2)", ""]
    for league in LEAGUES:
        df = fl.load_league_data(league)
        teams, n, ti = fl.get_team_index(df)
        fin = df.dropna(subset=["home_goals", "away_goals"])
        ref = pd.Timestamp("2025-10-20")   # понеделник след международната пауза (на 06.10 няма мачове)
        hist = fin[fin["date"] < ref]
        xi = fl.LEAGUE_XI.get(league, fl.XI)
        kw = kw_of(league)
        for v, flkw in (("А", dict(intercept=kw["intercept"], tempo_mult=kw["tempo_mult"])), ("Б", dict(use_dc=True, low_data_extra_reg=LDR)),
                        ("Г", dict(use_dc=True, low_data_extra_reg=LDR, intercept=kw["intercept"], tempo_mult=kw["tempo_mult"]))):
            a = fit_variant(v, hist, ref, ti, n, xi, kw, None)
            b = fl.fit_goals_direct_covariate(hist, ref, ti, n, INJ[0], INJ[1], xi=xi, **flkw)
            blk = fin[(fin["date"] >= ref) & (fin["date"] < ref + pd.Timedelta(days=7))]
            hc, ac = blk[INJ[0]].fillna(0).to_numpy(float), blk[INJ[1]].fillna(0).to_numpy(float)
            l1, m1 = fb._vec_lambdas(a, ti, blk["home_team"], blk["away_team"], hc, ac)
            l2 = np.array([fl.get_lambdas_direct(b, ti, h, w, x, y)[0] for h, w, x, y in zip(blk["home_team"], blk["away_team"], hc, ac)])
            m2 = np.array([fl.get_lambdas_direct(b, ti, h, w, x, y)[1] for h, w, x, y in zip(blk["home_team"], blk["away_team"], hc, ac)])
            d = max(np.abs(l1 - l2).max(), np.abs(m1 - m2).max())
            lines.append(f"- {league} {v} ({len(blk)} мача от {ref.date()}): макс. разлика lam/mu tri_fit − football_lib {d:.1e}; "
                         f"rho {a['rho']:.4f} / {b['rho']:.4f}")
            print(lines[-1], flush=True)
    core = pd.read_csv(os.path.join(ROOT, "features", "core_lam_mu.csv"))
    with Pool(4) as pool:
        parts = pool.map(run, [(lg, "А", "early") for lg in LEAGUES], chunksize=1)
    a = pd.concat(parts).merge(core[["fixture_id", "lam", "mu", "rho"]], on="fixture_id", suffixes=("", "_core"))
    lines += ["", f"А (ранната половина, {len(a)} общи мача) срещу features/core_lam_mu.csv: макс. |Δlam| {np.abs(a.lam - a.lam_core).max():.1e}, "
              f"макс. |Δmu| {np.abs(a.mu - a.mu_core).max():.1e}, средно |Δlam| {np.abs(a.lam - a.lam_core).mean():.1e}; rho в core = "
              f"{a.rho_core.abs().max():.1f} (0 = няма rho, както каза прегледът)."]
    print(lines[-1])
    open(os.path.join(V, f"top4_yadro_{TAG}_check.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


def early():
    jobs = [(lg, v, "early") for v in VARIANTS for lg in LEAGUES]
    with Pool(16) as pool:
        parts = pool.map(run, jobs, chunksize=1)
    d = pd.concat(parts, ignore_index=True)
    d.to_csv(os.path.join(V, f"top4_yadro_{TAG}_early_matches.csv"), index=False)
    base = base_freq(d[d.variant == "А"])
    rows = []
    for v in VARIANTS:
        x = d[d.variant == v].reset_index(drop=True)
        rows.append({"variant": v, **describe(x, per_match(x), base)})
    r = pd.DataFrame(rows)
    r.to_csv(os.path.join(V, f"top4_yadro_{TAG}_early.csv"), index=False)
    a_b11 = r.loc[r.variant == "А", "b11"].iloc[0]
    cand = r[r.variant != "А"].sort_values("b11").iloc[0]
    chosen = cand["variant"] if cand["b11"] < a_b11 else None
    json.dump({"chosen": chosen, "early_b11": dict(zip(r.variant, r.b11)), "rule": "най-нисък Brier 11 на ранната сред Б/В/Г, ако < А"},
              open(SEL, "w"), ensure_ascii=False, indent=1)
    md = ["# ЧАСТ 2 — ранна половина (избор)", "", f"Мачове: {len(d) // len(VARIANTS)} (4-те лиги, дата < {EARLY_END}). Само ранната половина.", "",
          "| вариант | Brier 11 | Brier 1X2 | log-loss 1X2 | равни модел / реално | 1-1 модел / реално | a 1x2 | a ou25 | a btts | a team_total | ср. rho |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, x in r.iterrows():
        md.append(f"| {x.variant} | {x.b11:.5f} | {x.b1x2:.5f} | {x.ll1x2:.5f} | {x.draw_model * 100:.1f}% / {x.draw_real * 100:.1f}% | "
                  f"{x.p11_model * 100:.1f}% / {x.p11_real * 100:.1f}% | {x.a_1x2:.3f} | {x.a_ou25:.3f} | {x.a_btts:.3f} | {x.a_team_total:.3f} | {x.rho_mean:+.3f} |")
    md += ["", f"**Избор (правило от настройките):** {'вариант ' + chosen if chosen else 'нито един от Б/В/Г не е по-добър от А на ранната - нищо не се избира'}."]
    open(os.path.join(V, f"top4_yadro_{TAG}_early.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))


def late():
    sel = json.load(open(SEL))
    chosen = sel["chosen"]
    if not chosen:
        print("няма избран вариант - късната не се пуска")
        return
    jobs = [(lg, v, "late") for v in ("А", chosen) for lg in LEAGUES]
    with Pool(8) as pool:
        parts = pool.map(run, jobs, chunksize=1)
    d = pd.concat(parts, ignore_index=True)
    d.to_csv(os.path.join(V, f"top4_yadro_{TAG}_late_matches.csv"), index=False)
    e = pd.read_csv(os.path.join(V, f"top4_yadro_{TAG}_early_matches.csv"))
    base = base_freq(e[e.variant == "А"])
    A = d[d.variant == "А"].sort_values("fixture_id").reset_index(drop=True)
    X = d[d.variant == chosen].sort_values("fixture_id").reset_index(drop=True)
    assert (A.fixture_id.to_numpy() == X.fixture_id.to_numpy()).all()
    mA, mX = per_match(A), per_match(X)
    dA, dX = describe(A, mA, base), describe(X, mX, base)
    ci = {k: boot(mX[k] - mA[k]) for k in ("b11", "b1x2", "ll1x2") + tuple(f"b_{g}" for g in GROUPS)}
    lg_ci = {lg: boot((mX["b11"] - mA["b11"])[A.league == lg]) for lg in LEAGUES}
    c1 = ci["b11"][2] < 0 or (ci["b1x2"][2] < 0 and all(ci[f"b_{g}"][1] <= 0 for g in GROUPS))
    c2 = all(lg_ci[lg][1] <= 0 for lg in LEAGUES)
    passed = c1 and c2
    rows = [{"variant": v, **dd} for v, dd in (("А", dA), (chosen, dX))]
    pd.DataFrame(rows).to_csv(os.path.join(V, f"top4_yadro_{TAG}_late.csv"), index=False)
    per_lg = []
    for lg in LEAGUES:
        s = A.league == lg
        per_lg.append((lg, int(s.sum()), describe(A[s], mA[s], base), describe(X[s], mX[s], base), lg_ci[lg]))
    json.dump({"chosen": chosen, "passed": bool(passed), "c1": bool(c1), "c2": bool(c2), "ci": ci, "league_ci": lg_ci},
              open(os.path.join(V, f"top4_yadro_{TAG}_late.json"), "w"), ensure_ascii=False, indent=1)
    write_md(chosen, dA, dX, ci, per_lg, passed, c1, c2, len(A))


def write_md(chosen, dA, dX, ci, per_lg, passed, c1, c2, n):
    early_md = open(os.path.join(V, f"top4_yadro_{TAG}_early.md"), encoding="utf-8").read().split("\n", 2)[2]
    L = ["# ЧАСТ 2 (ZADACHA_MODELI) — ядрото за england / germany / spain / france", "",
         f"**Решение: {'КРИТЕРИЯТ Е ИЗПЪЛНЕН — вариант ' + chosen + ' влиза' if passed else 'КРИТЕРИЯТ НЕ Е ИЗПЪЛНЕН — нищо не влиза'}.**", "",
         "Настройки и критерий — `validation/top4_yadro_nastroyki_20261007.md` (записани преди пускането); проверка на фитъра — "
         "`validation/top4_yadro_20261007_check.txt`; скрипт `validation/top4_yadro_20261007.py`.", "",
         "## Ранна половина (избор)", "", early_md.strip(), "",
         f"## Късна половина (пусната веднъж): А срещу {chosen}, {n} мача", "",
         "| мярка | А | " + chosen + " | разлика (" + chosen + " − А), 95% |", "|---|---|---|---|",
         f"| Brier 11 изхода | {dA['b11']:.5f} | {dX['b11']:.5f} | {fmt_ci(ci['b11'])} |",
         f"| Brier 1X2 | {dA['b1x2']:.5f} | {dX['b1x2']:.5f} | {fmt_ci(ci['b1x2'])} |",
         f"| log-loss 1X2 | {dA['ll1x2']:.5f} | {dX['ll1x2']:.5f} | {fmt_ci(ci['ll1x2'])} |"]
    for g in GROUPS:
        L.append(f"| Brier група {g} | | | {fmt_ci(ci['b_' + g])} |")
    L += [f"| равни: модел / реално | {dA['draw_model'] * 100:.1f}% / {dA['draw_real'] * 100:.1f}% | {dX['draw_model'] * 100:.1f}% / "
          f"{dX['draw_real'] * 100:.1f}% | |",
          f"| 1-1: модел / реално | {dA['p11_model'] * 100:.1f}% / {dA['p11_real'] * 100:.1f}% | {dX['p11_model'] * 100:.1f}% / "
          f"{dX['p11_real'] * 100:.1f}% | |"]
    for g in GROUPS:
        L.append(f"| калибрация a {g} (1 = идеално) | {dA['a_' + g]:.3f} | {dX['a_' + g]:.3f} | |")
    L += ["", "### По лига (Brier 11 изхода)", "", "| лига | мачове | А | " + chosen + " | разлика, 95% | равни модел А / " + chosen + " / реално |",
          "|---|---|---|---|---|---|"]
    for lg, k, a, x, c in per_lg:
        L.append(f"| {lg} | {k} | {a['b11']:.5f} | {x['b11']:.5f} | {fmt_ci(c)} | {a['draw_model'] * 100:.1f}% / {x['draw_model'] * 100:.1f}% / "
                 f"{a['draw_real'] * 100:.1f}% |")
    L += ["", "### Критерий", "",
          f"- (1) Brier 11 с интервал под нулата: {'да' if ci['b11'][2] < 0 else 'не'}; или Brier 1X2 под нулата ({'да' if ci['b1x2'][2] < 0 else 'не'}) "
          f"и нито една група значимо по-зле ({'да' if all(ci['b_' + g][1] <= 0 for g in GROUPS) else 'не'}) → **{'изпълнено' if c1 else 'не е изпълнено'}**",
          f"- (2) нито една лига значимо по-зле: **{'изпълнено' if c2 else 'не е изпълнено'}**", ""]
    open(os.path.join(V, f"top4_yadro_{TAG}.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


def report_no_choice():
    """Ако на ранната няма избран вариант: отчет само от ранната (разлики спрямо А с интервали, по група и лига) - защо и кой е най-близо.
    Късната половина НЕ се пуска."""
    sel = json.load(open(SEL))
    if sel["chosen"]:
        print("има избран вариант - ползвай --late")
        return
    d = pd.read_csv(os.path.join(V, f"top4_yadro_{TAG}_early_matches.csv"))
    A = d[d.variant == "А"].sort_values("fixture_id").reset_index(drop=True)
    mA = per_match(A)
    base = base_freq(A)
    early_md = open(os.path.join(V, f"top4_yadro_{TAG}_early.md"), encoding="utf-8").read().split("\n", 2)[2]
    L = ["# ЧАСТ 2 (ZADACHA_MODELI) — ядрото за england / germany / spain / france", "",
         "**Решение: КРИТЕРИЯТ НЕ Е ИЗПЪЛНЕН — нищо не влиза.** На ранната половина нито един от Б/В/Г не е по-добър от сегашния А, затова "
         "по записаното правило (`validation/top4_yadro_nastroyki_20261007.md`) няма избран вариант и **късната половина не е пускана**. "
         "`football_lib.fit_goals_direct_covariate()` има новите параметри (по подразбиране — старото бит по бит, "
         "`validation/top4_yadro_20261007_default.txt`), но живият код ги не ползва; `TOP4_CORE` не е въведен.", "",
         "Проверка на бързия фитър: `validation/top4_yadro_20261007_check.txt`. Скрипт: `validation/top4_yadro_20261007.py`. По мач: "
         "`validation/top4_yadro_20261007_early_matches.csv`.", "", "## Ранна половина (дата < 2025-09-23)", "", early_md.strip(), "",
         "## Разлика спрямо А на ранната (вариант − А, 95% bootstrap по мач; положително = по-лошо)", "",
         "| вариант | Brier 11 | Brier 1X2 | log-loss 1X2 | 1x2 | ou25 | btts | team_total |", "|---|---|---|---|---|---|---|---|"]
    lg_rows = []
    for v in VARIANTS[1:]:
        X = d[d.variant == v].sort_values("fixture_id").reset_index(drop=True)
        mX = per_match(X)
        c = {k: boot(mX[k] - mA[k]) for k in ("b11", "b1x2", "ll1x2") + tuple(f"b_{g}" for g in GROUPS)}
        L.append(f"| {v} | {fmt_ci(c['b11'])} | {fmt_ci(c['b1x2'])} | {fmt_ci(c['ll1x2'], 4)} | " +
                 " | ".join(fmt_ci(c[f'b_{g}']) for g in GROUPS) + " |")
        for lg in LEAGUES:
            s = A.league == lg
            dx, da = describe(X[s], mX[s], base), describe(A[s], mA[s], base)
            lg_rows.append(f"| {v} | {lg} | {int(s.sum())} | {fmt_ci(boot((mX['b11'] - mA['b11'])[s]))} | {da['draw_model'] * 100:.1f}% → "
                           f"{dx['draw_model'] * 100:.1f}% (реално {da['draw_real'] * 100:.1f}%) | {X[s].rho.mean():+.3f} |")
    L += ["", "### По лига (Brier 11, вариант − А)", "", "| вариант | лига | мачове | разлика, 95% | равни модел А → вариант | ср. rho |",
          "|---|---|---|---|---|---|"] + lg_rows
    open(os.path.join(V, f"top4_yadro_{TAG}.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--early" in sys.argv:
        early()
    elif "--late" in sys.argv:
        late()
    elif "--report" in sys.argv:
        report_no_choice()
    else:
        print(__doc__)
