"""
validation/final_v_20260924.py - ZADACHA_FINAL.md, ЧАСТ В (24.09.2026). Пълното сравнение.

1. МЕРИЛОТО (методът на backtest_full.py - последните 730 дни на лигата,
   седмично префитване само от мачове преди понеделника, 11823 мача) с
   ДНЕШНИЯ модел: повторната сметка от final_b_20260924.run() (свито темпо,
   контузии, xG смес, общ евро модел; контрол срещу tri_a/tri_v - виж
   final_b_20260924.md) + матрицата на живия код (Dixon-Coles + зависимостта
   от ЧАСТ А) + живата калибрация (prediction_policy.calibrate). Корнерите -
   повторната сметка tri_b_20260923.run(), вариантът "натиск" (= живия
   fl.fit_corners_pressure), отрицателно биномно с CORNERS_NB_ALPHA от живия
   код, калибрацията за корнерите.
   Показвани пазари: 1X2, над/под 2.5, двата отбора, отборни голове (над/под
   1.5), двоен шанс и чиста мрежа (от матрицата, некалибрирани - както на
   живо), корнери (общо 9.5, домакин/гост 4.5). Полувреме/край - не е мерено
   (друг модел, не е в мерилото).

2. КОЕФИЦИЕНТ НА КАЛИБРАЦИЯ (calibration_fit метод): a = сума (p-b)(y-b) /
   сума (p-b)^2, b - честотата на изхода на ранната половина (дата <
   2025-09-23), по пазарна група. За суровия модел на ранната половина -
   числото, което стои в CALIBRATION_A; на късната - проверка; за
   ПОКАЗВАНОТО число (след калибрацията) на късната - дали на сайта
   процентите са честни. Рамка: 0.9-1.1.

3. КОЛКО БЪРКА: на всеки пазар в мача се взима по-вероятната страна;
   средно обещано срещу реално познато, в пункта (както calibration_all_
   markets / tri_b), късна половина, показваното число.

4. СРЕЩУ ПАЗАРА: редовете на model_vs_market.build_rows() (уредени,
   логнати, с обезвиговано пазарно число; без двоен шанс/полувреме-край -
   там пазарът е суров implied). Пазарното число и изходът - същите; НАШЕТО
   число се преизчислява с днешния модел от седмичната прогноза за същия мач
   (както tri_v_20260924). Разлика = Brier наш - Brier пазар; 95% интервал
   с bootstrap по мач (2000, seed 42); "значимо" - интервалът не съдържа 0.
   Изходна точка: model_vs_market_baseline_20260923.md, +0.0098 (записаните
   числа, 840 мача). Отделно model_vs_market.py се пуска както е (--tag
   final) - той мери ЗАПИСАНИТЕ проценти (стари версии на модела).

Изход: validation/final_v_20260924.md (докладът), final_v_20260924_calib.csv,
final_v_20260924_leagues.csv, final_v_20260924_market.csv,
final_v_20260924_matches.csv (вероятностите по мач - новата отправна точка).
Употреба: venv/bin/python3 validation/final_v_20260924.py
"""
import ast
import os
import subprocess
import sys

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
from collections import defaultdict  # noqa: E402
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
import prediction_policy as policy  # noqa: E402
import razpredelenie_b_20260923 as rb  # noqa: E402
import tri_b_20260923 as tb  # noqa: E402

TAG = "20260924"
G = np.arange(bf.MAX_G)
X, Yg = np.meshgrid(G, G, indexing="ij")
GOAL_CODES = bf.CODES + ["dc_1x", "dc_x2", "dc_12", "home_clean_sheet", "away_clean_sheet"]
CORNER_CODES = tb.CODES
GROUP = {**bf.GROUPS, "dc_1x": "double_chance", "dc_x2": "double_chance", "dc_12": "double_chance",
         "home_clean_sheet": "clean_sheet", "away_clean_sheet": "clean_sheet",
         **{c: "corners" for c in CORNER_CODES}}
GN = {"1x2": "1X2", "ou25": "над/под 2.5", "btts": "двата отбора", "team_total": "отборни голове (1.5)",
      "double_chance": "двоен шанс", "clean_sheet": "чиста мрежа", "corners": "корнери"}
ORDER = ["1x2", "ou25", "btts", "team_total", "double_chance", "clean_sheet", "corners"]
# пазар в мача -> кодовете му (за "по-вероятната страна"); двойка с един код = (p, 1-p)
INSTANCES = {"1x2": ["home_win", "draw", "away_win"], "ou25": ["over25", "under25"], "btts": ["btts_yes", "btts_no"],
             "tt_home": ["home_over15", "home_under15"], "tt_away": ["away_over15", "away_under15"],
             "dc": ["dc_1x", "dc_x2", "dc_12"], "cs_home": ["home_clean_sheet"], "cs_away": ["away_clean_sheet"],
             "c_tot": ["corners_total_over_9.5"], "c_home": ["corners_home_over_4.5"], "c_away": ["corners_away_over_4.5"]}
INST_GROUP = {"1x2": "1x2", "ou25": "ou25", "btts": "btts", "tt_home": "team_total", "tt_away": "team_total",
              "dc": "double_chance", "cs_home": "clean_sheet", "cs_away": "clean_sheet",
              "c_tot": "corners", "c_home": "corners", "c_away": "corners"}


def goal_probs(lam, mu, rho):
    pm = fa.shift(rb.matrices(lam, mu, rho, "poisson", 0), lam, mu, fl.SCORE_DEP_F0, fl.SCORE_DEP_F1)
    P = rb.market_probs(pm)
    P["dc_1x"] = P["home_win"] + P["draw"]
    P["dc_x2"] = P["draw"] + P["away_win"]
    P["dc_12"] = P["home_win"] + P["away_win"]
    P["home_clean_sheet"] = pm[:, :, 0].sum(1)
    P["away_clean_sheet"] = pm[:, 0, :].sum(1)
    return P


def goal_outcomes(hg, ag):
    Y = pd.DataFrame([bf.outcomes(h, a) for h, a in zip(hg, ag)])[bf.CODES].astype(float)
    Y["dc_1x"] = (hg >= ag).astype(float)
    Y["dc_x2"] = (hg <= ag).astype(float)
    Y["dc_12"] = (hg != ag).astype(float)
    Y["home_clean_sheet"] = (ag == 0).astype(float)
    Y["away_clean_sheet"] = (hg == 0).astype(float)
    return Y


def live_calibrate(P):
    """= prediction_policy.calibrate() за всеки код (кодовете без b/a - непроменени, както на живо)."""
    out = P.copy()
    for c in P.columns:
        b = policy.CALIBRATION_BASE.get(c)
        a = policy.CALIBRATION_A.get(policy.market_group(c), 1.0)
        if b is None or a == 1.0:
            continue
        out[c] = np.clip(b + a * (P[c] - b), 0.0, 1.0)
    return out


def calib_a(P, Y, early, mask, codes):
    num = den = 0.0
    for c in codes:
        b = Y.loc[early, c].mean()
        d = P.loc[mask, c].to_numpy() - b
        num += (d * (Y.loc[mask, c].to_numpy() - b)).sum()
        den += (d * d).sum()
    return num / den


def fav_gap(P, Y, mask, inst_names):
    """(обещано %, познато %) за по-вероятната страна, всички пазари от inst_names."""
    prom, hit, var = [], [], []
    for nm in inst_names:
        codes = INSTANCES[nm]
        if codes[0] not in P.columns:
            continue
        p = P.loc[mask, codes].to_numpy()
        y = Y.loc[mask, codes].to_numpy()
        if len(codes) == 1:
            p = np.column_stack([p[:, 0], 1 - p[:, 0]])
            y = np.column_stack([y[:, 0], 1 - y[:, 0]])
        ok = ~np.isnan(p).any(1)
        k = p[ok].argmax(1)
        prom.append(p[ok][np.arange(ok.sum()), k])
        hit.append(y[ok][np.arange(ok.sum()), k])
    pr = np.concatenate(prom)
    se = float(np.sqrt((pr * (1 - pr)).sum()) / len(pr) * 100)   # ако обещаното е вярно
    return float(pr.mean() * 100), float(np.concatenate(hit).mean() * 100), se


def boot_ci(d, fx):
    """d - разлика на ред, fx - мач: bootstrap по мач."""
    s = pd.DataFrame({"d": d, "fx": fx}).groupby("fx")["d"].agg(["sum", "size"])
    su, cn = s["sum"].to_numpy(), s["size"].to_numpy()
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(su), size=(2000, len(su)))
    v = su[idx].sum(1) / cn[idx].sum(1)
    return float(su.sum() / cn.sum()), float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def run_corners(league):
    d = tb.run(league)
    return d.dropna(subset=["pressure_h", "pressure_a"])


def main():
    # 1. повторни сметки
    with Pool(16) as pool:
        goals = pool.map(fb.run, [(lg, 1.0) for lg in sorted(bf.LEAGUES, key=lambda x: x not in fb.S["EURO_FIT_SETTINGS"])],
                         chunksize=1)
        corners = pool.map(run_corners, tb.corner_leagues(), chunksize=1)
    t = pd.concat([g[0] for g in goals], ignore_index=True).sort_values(["league", "fixture_id"]).reset_index(drop=True)
    cr = pd.concat(corners, ignore_index=True)
    early = (pd.to_datetime(t.date) < kx.CUT).to_numpy()
    hg, ag = t.hg.to_numpy(), t.ag.to_numpy()
    P = goal_probs(t.lam.to_numpy(), t.mu.to_numpy(), t.rho.to_numpy())
    Y = goal_outcomes(hg, ag)
    Pc = live_calibrate(P)
    # корнери към същите редове
    cr = cr.set_index(["league", "fixture_id"])
    key = list(zip(t.league, t.fixture_id))
    has_c = np.array([k in cr.index for k in key])
    cc = cr.reindex(key)
    alpha = {}
    tree = ast.parse(open("match_predictor_app.py").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "CORNERS_NB_ALPHA":
            alpha = ast.literal_eval(node.value)
    for c in CORNER_CODES:
        P[c] = np.nan
        Y[c] = np.nan
    for lg in t.league.unique():
        sel = (t.league == lg).to_numpy() & has_c
        if not sel.any():
            continue
        pc = tb.probs(cc["pressure_h"].to_numpy()[sel], cc["pressure_a"].to_numpy()[sel], alpha.get(lg, 0.1))
        for c in CORNER_CODES:
            P.loc[sel, c] = pc[c].to_numpy()
        hc, ac = cc["hc"].to_numpy()[sel], cc["ac"].to_numpy()[sel]
        Y.loc[sel, "corners_total_over_9.5"] = (hc + ac > 9.5).astype(float)
        Y.loc[sel, "corners_home_over_4.5"] = (hc > 4.5).astype(float)
        Y.loc[sel, "corners_away_over_4.5"] = (ac > 4.5).astype(float)
    Pc = live_calibrate(P)

    out = t[["league", "fixture_id", "date", "hg", "ag", "lam", "mu", "rho"]].copy()
    for c in GOAL_CODES + CORNER_CODES:
        out[f"p_{c}"] = Pc[c].round(5)
        out[f"y_{c}"] = Y[c]
    out.to_csv(f"validation/final_v_{TAG}_matches.csv", index=False)

    # 2. коефициенти на калибрация
    cal = []
    for g in ORDER:
        codes = [c for c in GOAL_CODES + CORNER_CODES if GROUP[c] == g]
        m_ok = ~P[codes].isna().any(axis=1).to_numpy()
        e, l_ = early & m_ok, ~early & m_ok
        cal.append({"group": g, "n_early": int(e.sum()), "n_late": int(l_.sum()),
                    "in_code": policy.CALIBRATION_A.get(g, 1.0),
                    "raw_early": calib_a(P, Y, e, e, codes), "raw_late": calib_a(P, Y, e, l_, codes),
                    "shown_late": calib_a(Pc, Y, e, l_, codes), "shown_all": calib_a(Pc, Y, e, m_ok, codes)})
    cal = pd.DataFrame(cal)
    cal.round(4).to_csv(f"validation/final_v_{TAG}_calib.csv", index=False)

    # 3. колко бърка + Brier по лига (показваното), срещу старото мерило
    old = pd.read_csv("validation/backtest_full_20260923.csv")
    old_m = pd.read_csv("validation/backtest_full_20260923_matches.csv")
    lg_rows = []
    for lg in bf.LEAGUES + ["ALL"]:
        sel = np.ones(len(t), bool) if lg == "ALL" else (t.league == lg).to_numpy()
        rec = {"league": lg, "n": int(sel.sum())}
        for g in ["1x2", "ou25", "btts", "team_total"]:
            codes = [c for c in bf.CODES if bf.GROUPS[c] == g]
            rec[f"brier_{g}"] = float(((Pc.loc[sel, codes].to_numpy() - Y.loc[sel, codes].to_numpy()) ** 2).mean())
            rec[f"old_{g}"] = float(old[(old.league == lg) & (old.group == g)]["brier"].iloc[0])
        rec["brier_all"] = float(((Pc.loc[sel, bf.CODES].to_numpy() - Y.loc[sel, bf.CODES].to_numpy()) ** 2).mean())
        rec["old_all"] = float(old[(old.league == lg) & (old.group == "ALL")]["brier"].iloc[0])
        for gi, insts in (("1x2", ["1x2"]), ("ou25", ["ou25"]), ("btts", ["btts"]), ("team_total", ["tt_home", "tt_away"]),
                          ("corners", ["c_tot", "c_home", "c_away"])):
            m2 = sel & ~early
            if gi == "corners":
                m2 = m2 & ~P["corners_total_over_9.5"].isna().to_numpy()
            if m2.sum() >= 30:
                pr, hi, se = fav_gap(Pc, Y, m2, insts)
                rec[f"gap_{gi}"] = pr - hi
                rec[f"z_{gi}"] = (pr - hi) / se
        lg_rows.append(rec)
    lgs = pd.DataFrame(lg_rows)
    lgs.round(5).to_csv(f"validation/final_v_{TAG}_leagues.csv", index=False)
    # старото мерило - същите мачове ли са
    same = set(zip(old_m.league, old_m.fixture_id)) == set(key)
    gaps = {}
    for g, insts in (("1x2", ["1x2"]), ("ou25", ["ou25"]), ("btts", ["btts"]), ("team_total", ["tt_home", "tt_away"]),
                     ("double_chance", ["dc"]), ("clean_sheet", ["cs_home", "cs_away"]), ("corners", ["c_tot", "c_home", "c_away"])):
        m2 = ~early & (~P[INSTANCES[insts[0]][0]].isna().to_numpy())
        gaps[g] = fav_gap(Pc, Y, m2, insts)

    # 4. срещу пазара
    import model_vs_market as mvm
    detail, _ = mvm.build_rows()
    mrows = [d for d in detail if not d["raw_implied"]]
    idx = {k: i for i, k in enumerate(key)}
    items = []
    miss = defaultdict(int)
    for d in mrows:
        i = idx.get((d["league"], d["fixture_id"]))
        if i is None or d["code"] not in Pc.columns:
            miss[d["league"]] += 1
            continue
        items.append({"fixture_id": d["fixture_id"], "league": d["league"], "group": d["group"], "code": d["code"],
                      "y": d["y"], "market": d["market"], "logged": d["ours"], "now": float(Pc[d["code"]].iloc[i]),
                      "late": not early[i]})
    mk = pd.DataFrame(items)
    # проверка: изходът от лога = изходът от CSV-то
    chk = np.array([Y[r.code].iloc[idx[(r.league, r.fixture_id)]] for r in mk.itertuples()])
    mism = int((chk != mk.y.to_numpy()).sum())
    mres = []
    for lvl, gcol in (("overall", None), ("group", "group"), ("league", "league")):
        parts = [("всички", mk)] if gcol is None else list(mk.groupby(gcol))
        for nm, s in parts:
            bn = (s.now - s.y) ** 2
            bm = (s.market - s.y) ** 2
            bl = (s.logged - s.y) ** 2
            ci = boot_ci((bn - bm).to_numpy(), s.fixture_id.to_numpy())
            ci_l = boot_ci((bl - bm).to_numpy(), s.fixture_id.to_numpy())
            mres.append({"level": lvl, "name": nm, "n": len(s), "matches": s.fixture_id.nunique(),
                         "brier_market": bm.mean(), "brier_now": bn.mean(), "brier_logged": bl.mean(),
                         "diff_now": ci[0], "lo_now": ci[1], "hi_now": ci[2], "diff_logged": ci_l[0], "lo_logged": ci_l[1],
                         "hi_logged": ci_l[2]})
    mres = pd.DataFrame(mres)
    mres.round(5).to_csv(f"validation/final_v_{TAG}_market.csv", index=False)

    # 5. model_vs_market.py както е
    subprocess.run([sys.executable, "validation/model_vs_market.py", "--tag", "final"], check=True,
                   stdout=subprocess.DEVNULL)
    mvm_final = pd.read_csv(f"validation/model_vs_market_final_{TAG}.csv")

    res = {"cal": cal, "lgs": lgs, "gaps": gaps, "mres": mres, "same": same, "miss": dict(miss), "mism": mism,
           "n_mrows": len(mrows), "mvm_final": mvm_final, "n": len(t), "n_c": int(has_c.sum())}
    pd.to_pickle(res, f"/tmp/final_v_{TAG}.pkl")
    write_md(res)


def pct_rel(x, base):
    return x / base * 100


def write_md(res):
    cal, lgs, gaps, mres = res["cal"], res["lgs"], res["gaps"], res["mres"]
    allr = lgs[lgs.league == "ALL"].iloc[0]
    L = [f"# ФИНАЛ, ЧАСТ В - пълното сравнение - {TAG}", "",
         "ZADACHA_FINAL.md, ЧАСТ В. Скрипт: `validation/final_v_20260924.py` (методът е в docstring-а). Числа: "
         "`final_v_20260924_calib.csv` (калибрация), `_leagues.csv` (по лига), `_market.csv` (срещу пазара), "
         "`_matches.csv` (вероятностите по мач - новата отправна точка), `model_vs_market_final_20260924.md` "
         "(записаните проценти).", "",
         f"Мерило: {res['n']} мача, последните две години на всяка лига, моделът се учи всяка седмица само от минали",
         f"мачове (корнери - {res['n_c']} мача в 14-те лиги с корнери). Моделът е днешният: всичко от 23-24.09 плюс ЧАСТ А.",
         "Процентите са показваните (след калибрацията), освен където е казано „суров“.", "",
         "## 1. Калибрация - честни ли са процентите (рамка 0.9-1.1)", "",
         "Коефициент 1.0 = процентите са точно толкова смели, колкото трябва; под 1 - моделът е прекалено сигурен,",
         "над 1 - прекалено плах.", "",
         "| пазар | суров модел, ранна (в кода) | суров, късна | показвано, късна | в рамката (суров, ранна) | в рамката (показвано, късна) |",
         "|---|---|---|---|---|---|"]
    for r in cal.itertuples():
        L.append(f"| {GN[r.group]} | {r.raw_early:.3f} | {r.raw_late:.2f} | {r.shown_late:.2f} | "
                 f"{'да' if 0.9 <= r.raw_early <= 1.1 else 'НЕ'} | {'да' if 0.9 <= r.shown_late <= 1.1 else 'НЕ'} |")
    out_raw = [GN[r.group] for r in cal.itertuples() if not 0.9 <= r.raw_early <= 1.1]
    out_late = [GN[r.group] for r in cal.itertuples() if not 0.9 <= r.shown_late <= 1.1]
    L += ["", ("**Всички показвани пазари са в рамката** по суровия коефициент (този, по който е критерият)."
               if not out_raw else f"**Извън рамката (суров коефициент): {', '.join(out_raw)}.**"),
          ("На късната половина показваните проценти също са в рамката за всички пазари." if not out_late else
           f"На късната половина (невиждана при настройката) показваното число е извън рамката за: {', '.join(out_late)}."),
          "Двоен шанс и чиста мрежа не минават през калибрацията (на живо се показват сурови) - коефициентът им",
          "се мери тук за първи път. Корнерите: суровият модел е прекалено сигурен (0.85), калибрацията го",
          "оправя (показваното на късната - виж колоната). Полувреме/край не е мерено (друг модел).",
          "„Суров, късна“ и „показвано, късна“ ползват b от ранната половина (както живата калибрация) - ако",
          "нивото на пазара се е сменило (над 2.5, ЧАСТ Б), това сваля коефициента.", "",
          "## 2. Кое бърка и с колко (късна половина)", "",
          "На всеки пазар в мача се взима по-вероятната страна; колко процента обещаваме средно и колко реално се",
          "случват:", "",
          "| пазар | обещано % | познато % | разлика (пункта) |", "|---|---|---|---|"]
    for g in ORDER:
        pr, hi, se = gaps[g]
        L.append(f"| {GN[g]} | {pr:.1f} | {hi:.1f} | {pr - hi:+.1f}{' *' if abs(pr - hi) > 2 * se else ''} |")
    L += ["", "Плюс = обещаваме повече, отколкото се случва (самоувереност); минус - по-малко. „*“ = по-голямо от",
          "случайното (над две стандартни отклонения, ако обещаното е вярно).", "",
          "По лига - разликата обещано − познато в пункта (късна половина; празно - под 30 мача; „*“ - както по-горе):", "",
          "| лига | 1X2 | над/под 2.5 | двата отбора | отборни голове | корнери |", "|---|---|---|---|---|---|"]

    def f(r, g):
        v, z = getattr(r, f"gap_{g}", np.nan), getattr(r, f"z_{g}", np.nan)
        return "" if pd.isna(v) else f"{v:+.1f}{' *' if abs(z) > 2 else ''}"
    sig_cells, n_cells = [], 0
    for r in lgs.itertuples():
        L.append(f"| {r.league} | {f(r, '1x2')} | {f(r, 'ou25')} | {f(r, 'btts')} | {f(r, 'team_total')} | {f(r, 'corners')} |")
        if r.league != "ALL":
            for g in ("1x2", "ou25", "btts", "team_total", "corners"):
                v, z = getattr(r, f"gap_{g}", np.nan), getattr(r, f"z_{g}", np.nan)
                if not pd.isna(v):
                    n_cells += 1
                    if abs(z) > 2:
                        sig_cells.append(f"{r.league} {GN[g]} {v:+.1f}")
    L += ["", f"Извън случайното по лига: {len(sig_cells)} от {n_cells} клетки"
          + (f" ({'; '.join(sig_cells)})" if sig_cells else "")
          + f". При {n_cells} клетки и праг две стандартни отклонения ~{n_cells * 0.046:.0f} биха излезли и случайно;",
          "за отборните голове и корнерите (няколко пазара на мач) прагът е по-снизходителен от реалния.", "",
          "## 3. Спрямо изходната точка от 23.09 (мерилото, същите мачове)", "",
          f"Същите мачове като `backtest_full_20260923`: {'да' if res['same'] else 'НЕ'}. Грешка (Brier) - колко по-малка",
          "е днес спрямо модела от 23.09 сутринта (преди калибрацията, xG, темпото, евро модела и ЧАСТ А):", "",
          "| лига | 1X2 | над/под 2.5 | двата отбора | отборни голове | общо |", "|---|---|---|---|---|---|"]
    for r in lgs.itertuples():
        cells = []
        for g in ("1x2", "ou25", "btts", "team_total", "all"):
            new, old = getattr(r, f"brier_{g}"), getattr(r, f"old_{g}")
            cells.append(f"{(old - new) / old * 100:+.1f}%")
        L.append(f"| {r.league} | " + " | ".join(cells) + " |")
    n_better = int(sum(1 for r in lgs.itertuples() if r.league != "ALL" and r.brier_all < r.old_all))
    L += ["", f"(Плюс = по-малка грешка днес.) Общо: {(allr.old_all - allr.brier_all) / allr.old_all * 100:+.1f}%; "
          f"по-добре в {n_better} от 17 лиги.", "",
          "## 4. Срещу пазара", ""]
    ov = mres[(mres.level == "overall")].iloc[0]
    L += [f"Редове: {int(ov.n)} логнати пазара в {int(ov.matches)} уредени мача с обезвиговано пазарно число (от "
          f"{res['n_mrows']} в model_vs_market; "
          + (f"без прогноза в мерилото: {sum(res['miss'].values())} - {', '.join(f'{k} {v}' for k, v in res['miss'].items())}"
             if res["miss"] else "всички са в мерилото") + f"; изходът съвпада с CSV-то: {'да' if res['mism'] == 0 else 'НЕ, ' + str(res['mism'])}).",
          "Разлика = грешката ни минус грешката на пазара, като % от грешката на пазара (плюс = пазарът е по-точен).", "",
          "| | грешката ни спрямо пазара | значимо? |", "|---|---|---|"]

    def sig(lo, hi):
        return "пазарът по-добър" if lo > 0 else ("моделът по-добър" if hi < 0 else "не се различават")
    L.append(f"| записаните проценти (стари версии на модела), тези редове | "
             f"{pct_rel(ov.diff_logged, ov.brier_market):+.1f}% | {sig(ov.lo_logged, ov.hi_logged)} |")
    L.append(f"| **днешният модел, същите редове** | **{pct_rel(ov.diff_now, ov.brier_market):+.1f}%** | "
             f"{sig(ov.lo_now, ov.hi_now)} |")
    L += ["", f"**Изходна точка 23.09: +0.0098** (записаните числа, 840 мача) → на тези {int(ov.matches)} мача записаните дават "
          f"{ov.diff_logged:+.4f}, днешният модел - **{ov.diff_now:+.4f}** (95% [{ov.lo_now:+.4f}, {ov.hi_now:+.4f}]). "
          f"Пазарът е с грешка {ov.brier_market:.3f}; нашата днес е {ov.brier_now:.3f}.", "",
          "По пазар:", "", "| пазар | мачове | записаните | днешният модел | значимо? |", "|---|---|---|---|---|"]
    for r in mres[mres.level == "group"].itertuples():
        L.append(f"| {GN.get(r.name, r.name)} | {r.matches} | {pct_rel(r.diff_logged, r.brier_market):+.1f}% | "
                 f"{pct_rel(r.diff_now, r.brier_market):+.1f}% | {sig(r.lo_now, r.hi_now)} |")
    L += ["", "По лига:", "", "| лига | мачове | записаните | днешният модел | значимо? |", "|---|---|---|---|---|"]
    for r in mres[mres.level == "league"].itertuples():
        L.append(f"| {r.name} | {r.matches} | {pct_rel(r.diff_logged, r.brier_market):+.1f}% | "
                 f"{pct_rel(r.diff_now, r.brier_market):+.1f}% | {sig(r.lo_now, r.hi_now)} |")
    lg_m = mres[mres.level == "league"]
    worse = lg_m[lg_m.lo_now > 0].name.tolist()
    better = lg_m[lg_m.hi_now < 0].name.tolist()
    L += ["", f"Значимо по-зле от пазара: {', '.join(worse) if worse else 'никъде'}; значимо по-добре: "
          f"{', '.join(better) if better else 'никъде'}; останалите - в рамките на шума (40-90 мача на лига).", "",
          "`model_vs_market.py`, пуснат както е (`model_vs_market_final_20260924.md`), мери записаните проценти -",
          "повечето са от версии на модела отпреди 23.09, затова не показва днешния модел; даден е за пълнота."]
    mf = res["mvm_final"]
    o = mf[(mf.level == "overall")].iloc[0]
    L += [f"Там: {int(o.n)} реда, {int(o.matches)} мача, разлика {o['diff']:+.4f} ({o.verdict})."]
    with open(f"validation/final_v_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--md":
        write_md(pd.read_pickle(f"/tmp/final_v_{TAG}.pkl"))
    else:
        main()
