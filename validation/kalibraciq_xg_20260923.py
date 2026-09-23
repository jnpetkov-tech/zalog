"""
validation/kalibraciq_xg_20260923.py - ZADACHA_KALIBRACIQ.md, ЧАСТИ Б и В.

Мерило: validation/backtest_full_20260923_matches.csv (walk-forward, седмично
префитване, 730 дни, 11823 мача - виж backtest_full.py). Оттам идват
вероятностите на СЕГАШНИЯ модел (модел А: lam_A, mu_A, rho) - не се
преизчисляват.

=== ЧАСТ Б - xG като отделен модел, смесване на ниво очаквани голове ===
Само лигите с xG >= 70% (data_inventory_20260923.csv).
- Модел А: сегашният (от мерилото, без промяна).
- Модел Б: fl.fit_goals_model(..., obs_cols=("home_xg","away_xg"),
  use_dc=False) - същата машинария (атака/защита/домакинско предимство,
  време-тегла xi на лигата, свиване за малко данни), учена само от
  мачовете с xG. Същото седмично префитване като мерилото: за всяка
  седмица - само мачове с дата < понеделника ѝ.
- Период, в който xG съществува: седмица влиза в модел Б само ако
  историята ѝ има >= MIN_XG_HISTORY мача с xG; иначе за мачовете от нея
  w = 0 (т.е. сегашният модел).
- Смес: lam = w*lam_Б + (1-w)*lam_А, същото за mu; Dixon-Coles rho - от
  модел А (за лигите с контузии rho = 0, както днес).
- Избор на w от {0.0, 0.3, 0.5, 0.7, 1.0} по лига: най-нисък Brier (11-те
  изхода на backtest_full.CODES, без калибрация) на ПО-РАННАТА половина
  (мачове с дата < 2025-09-23 - същото разделяне като calibration_fit).
  По-късната половина НЕ участва в избора.

=== ЧАСТ В - три варианта ===
  сегашен | само калибрация | калибрация + xG
Калибрацията - през ЖИВАТА prediction_policy.calibrate() (временно с
CALIBRATION_ENABLED = True само в този процес), с параметрите от
calibration_fit_20260923.md - т.е. проверява и кода, не само числата.
Сравнение на по-късната половина (извън извадката и за калибрацията, и за
w) и, за справка, на по-ранната. 95% интервал - сдвоен bootstrap по мач,
2000, seed 42.

Проверка на диапазона: очакваните голове (lam/mu) на сместа в мерилото и
на модел, учен от всички данни (всички двойки отбори от последните 365 дни)
- срещу 0.3-3.5 и срещу сегашния модел.

Употреба: XG_LIB=<папка с football_lib.py с obs_cols> venv/bin/python3 validation/kalibraciq_xg_20260923.py
(след влизането на obs_cols в живия football_lib.py XG_LIB не е нужен)
"""
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
if os.environ.get("XG_LIB"):
    sys.path.insert(0, os.environ["XG_LIB"])
os.chdir(ROOT)

import football_lib as fl  # noqa: E402
import prediction_policy as policy  # noqa: E402
import backtest_full as bf  # noqa: E402

TAG = "20260923"
SRC = f"validation/backtest_full_{TAG}_matches.csv"
CUT = pd.Timestamp("2025-09-23")
WEIGHTS = [0.0, 0.3, 0.5, 0.7, 1.0]
MIN_XG_HISTORY = 150
LO, HI = 0.3, 3.5


def xg_leagues():
    inv = pd.read_csv(f"validation/data_inventory_{TAG}.csv")
    return inv[inv.xg_pct >= 70].league.tolist()


def fit_b(league, hist, ref):
    return fl.fit_goals_model(hist, ref, *_idx[league], xi=fl.LEAGUE_XI.get(league, fl.XI),
                              use_dc=False, obs_cols=("home_xg", "away_xg"))


_idx = {}


def model_b_preds(league):
    df = fl.load_league_data(league)
    teams, n, team_idx = fl.get_team_index(df)
    _idx[league] = (team_idx, n)
    m = pd.read_csv(SRC)
    m = m[m.league == league].copy()
    m["fit_week"] = pd.to_datetime(m["fit_week"])
    xg = df.dropna(subset=["home_xg", "away_xg"])
    out = []
    for week, block in m.groupby("fit_week"):
        hist = xg[xg["date"] < week]
        if len(hist) < MIN_XG_HISTORY:
            for r in block.itertuples():
                out.append((r.fixture_id, np.nan, np.nan))
            continue
        model = fit_b(league, hist, week)
        for r in block.itertuples():
            lam, mu = fl.get_lambdas(model, team_idx, r.home_team, r.away_team)
            out.append((r.fixture_id, lam, mu))
    return league, pd.DataFrame(out, columns=["fixture_id", "lam_b", "mu_b"])


def probs_frame(lam, mu, rho):
    rows = [bf.market_probs(l, u, r) for l, u, r in zip(lam, mu, rho)]
    return pd.DataFrame(rows)


def calibrated(pf):
    policy.CALIBRATION_ENABLED = True
    out = pf.copy()
    for c in bf.CODES:
        out[c] = [policy.calibrate(100 * p, None, c) / 100 for p in pf[c]]
    return out


def brier_rows(pf, m):
    """(n_matches,) средна Brier на мач върху 11-те изхода."""
    sq = np.zeros(len(m))
    for c in bf.CODES:
        sq += (pf[c].to_numpy() - m[f"y_{c}"].to_numpy()) ** 2
    return sq / len(bf.CODES)


def ci(a, b):
    d = a - b
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(d), size=(2000, len(d)))
    v = d[idx].mean(1)
    return float(d.mean()), float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def range_all_pairs(args):
    league, w = args
    df = fl.load_league_data(league)
    teams, n, team_idx = fl.get_team_index(df)
    _idx[league] = (team_idx, n)
    ref = df["date"].max()
    a = bf.current_fit(league, df, ref, team_idx, n, df.columns)
    b = fit_b(league, df.dropna(subset=["home_xg", "away_xg"]), ref)
    recent = df[df["date"] >= ref - pd.Timedelta(days=365)]
    act = sorted(set(recent.home_team) | set(recent.away_team))
    cur, mix = [], []
    for h in act:
        for g in act:
            if h == g:
                continue
            la, ma = bf.lambdas(a, team_idx, h, g, 0.0, 0.0)
            lb, mb = fl.get_lambdas(b, team_idx, h, g)
            cur += [la, ma]
            mix += [w * lb + (1 - w) * la, w * mb + (1 - w) * ma]
    return league, (min(cur), max(cur), min(mix), max(mix))


def main():
    m = pd.read_csv(SRC)
    m["d"] = pd.to_datetime(m["date"])
    xl = xg_leagues()
    with Pool(len(xl)) as pool:
        bres = dict(pool.map(model_b_preds, xl))
    bcols = pd.concat([v.assign(league=k) for k, v in bres.items()])
    m = m.merge(bcols, on=["league", "fixture_id"], how="left")
    early = (m["d"] < CUT).to_numpy()

    base = probs_frame(m["lam"], m["mu"], m["rho"])
    br_cur = brier_rows(base, m)
    cal = calibrated(base)
    br_cal = brier_rows(cal, m)

    # ЧАСТ Б - избор на w по лига върху по-ранната половина
    has_b = m["lam_b"].notna().to_numpy()
    sel_rows, chosen = [], {}
    br_w = {}
    for w in WEIGHTS:
        lam = np.where(has_b, w * m["lam_b"].fillna(0) + (1 - w) * m["lam"], m["lam"])
        mu = np.where(has_b, w * m["mu_b"].fillna(0) + (1 - w) * m["mu"], m["mu"])
        pf = probs_frame(lam, mu, m["rho"])
        br_w[w] = (brier_rows(pf, m), brier_rows(calibrated(pf), m), lam, mu)
    for lg in xl:
        sel = (m["league"] == lg).to_numpy()
        e, late = sel & early, sel & ~early
        scores = {w: br_w[w][0][e].mean() for w in WEIGHTS}
        best = min(scores, key=scores.get)
        chosen[lg] = best
        for w in WEIGHTS:
            sel_rows.append({"league": lg, "w": w, "brier_early": round(scores[w], 5),
                             "brier_late": round(br_w[w][0][late].mean(), 5),
                             "n_early_with_xg_model": int((e & has_b).sum()),
                             "n_late_with_xg_model": int((late & has_b).sum()), "chosen": w == best})
    pd.DataFrame(sel_rows).to_csv(f"validation/kalibraciq_xg_{TAG}_selection.csv", index=False)

    # вариант "калибрация + xG" с избраното w (w=0 за лигите без xG)
    br_calxg = br_cal.copy()
    lam_x, mu_x = m["lam"].to_numpy().copy(), m["mu"].to_numpy().copy()
    for lg, w in chosen.items():
        sel = (m["league"] == lg).to_numpy()
        br_calxg[sel] = br_w[w][1][sel]
        lam_x[sel], mu_x[sel] = br_w[w][2][sel], br_w[w][3][sel]

    # ЧАСТ В - по лига и общо
    res = []
    for lg in bf.LEAGUES + ["ALL"]:
        sel = np.ones(len(m), bool) if lg == "ALL" else (m["league"] == lg).to_numpy()
        for part, mask in (("ранна", sel & early), ("късна", sel & ~early)):
            r = {"league": lg, "part": part, "matches": int(mask.sum()),
                 "current": br_cur[mask].mean(), "cal": br_cal[mask].mean(), "cal_xg": br_calxg[mask].mean(),
                 "w": chosen.get(lg, "")}
            r["cal_minus_cur"], r["cal_ci_lo"], r["cal_ci_hi"] = ci(br_cal[mask], br_cur[mask])
            r["xg_minus_cal"], r["xg_ci_lo"], r["xg_ci_hi"] = ci(br_calxg[mask], br_cal[mask])
            if lg == "ALL" or lg in xl:
                r["lam_min_cur"] = float(min(m["lam"][mask].min(), m["mu"][mask].min()))
                r["lam_max_cur"] = float(max(m["lam"][mask].max(), m["mu"][mask].max()))
                r["lam_min_xg"] = float(min(lam_x[mask].min(), mu_x[mask].min()))
                r["lam_max_xg"] = float(max(lam_x[mask].max(), mu_x[mask].max()))
            res.append(r)
    res = pd.DataFrame(res)
    res.round(6).to_csv(f"validation/kalibraciq_xg_{TAG}.csv", index=False)

    with Pool(len(xl)) as pool:
        rng_all = dict(pool.map(range_all_pairs, [(lg, chosen[lg]) for lg in xl]))

    # РЕШЕНИЕ (правилата на задачата, автоматично):
    #  xG остава за лига, ако (1) w > 0, (2) на късната половина калибрация+xG < само калибрация,
    #  (3) сместа е в 0.3-3.5 и в мерилото, и за всички двойки днес.
    late = res[res.part == "късна"].set_index("league")
    early_ = res[res.part == "ранна"].set_index("league")
    decision = {}
    for lg in xl:
        mn = min(late.loc[lg, "lam_min_xg"], early_.loc[lg, "lam_min_xg"], rng_all[lg][2])
        mx = max(late.loc[lg, "lam_max_xg"], early_.loc[lg, "lam_max_xg"], rng_all[lg][3])
        in_range = mn >= LO and mx <= HI
        holds = chosen[lg] > 0 and late.loc[lg, "xg_minus_cal"] < 0
        decision[lg] = {"w": chosen[lg], "holds": holds, "in_range": in_range, "min": mn, "max": mx,
                        "keep": holds and in_range}
    keep = {lg: d["w"] for lg, d in decision.items() if d["keep"]}
    br_final = br_cal.copy()
    for lg, w in keep.items():
        sel = (m["league"] == lg).to_numpy()
        br_final[sel] = br_w[w][1][sel]
    fin = []
    for part, mask in (("ранна", early), ("късна", ~early)):
        d, lo, hi = ci(br_final[mask], br_cur[mask])
        d2, lo2, hi2 = ci(br_final[mask], br_cal[mask])
        fin.append({"part": part, "final": br_final[mask].mean(), "final_minus_cur": d, "ci_lo": lo, "ci_hi": hi,
                    "final_minus_cal": d2, "ci2_lo": lo2, "ci2_hi": hi2})
    pd.DataFrame([dict(league=k, **v) for k, v in decision.items()]).to_csv(
        f"validation/kalibraciq_xg_{TAG}_decision.csv", index=False)
    write_md(res, pd.DataFrame(sel_rows), chosen, xl, rng_all, decision, keep, fin)


def write_md(res, sel, chosen, xl, rng_all, decision, keep, fin):
    late = res[res.part == "късна"].set_index("league")
    early = res[res.part == "ранна"].set_index("league")
    A = late.loc["ALL"]
    L = [f"# Калибрация + xG (отделен модел) - {TAG}", "",
         "ZADACHA_KALIBRACIQ.md, части Б и В. Скрипт: `validation/kalibraciq_xg_20260923.py` (методът е в",
         "docstring-а). Мерило: `backtest_full_20260923_matches.csv` (11823 мача, walk-forward, седмично",
         "префитване). Сурови числа: `kalibraciq_xg_20260923.csv` и `_selection.csv`.", "",
         "Разделяне по време при 2025-09-23: **ранна** половина = избор на w и учене на калибрацията;",
         "**късна** половина = проверка, не участва в нито един избор. Brier - средно на 11-те изхода на мач",
         "(1X2, над/под 2.5, двата отбора, отборни голове над/под 1.5); по-малко = по-добре.", "",
         "## Трите варианта - късна половина (извън извадката)", "",
         "| вариант | Brier | спрямо сегашния (95% инт.) |", "|---|---|---|",
         f"| сегашен | {A['current']:.5f} | — |",
         f"| само калибрация | {A['cal']:.5f} | {A['cal_minus_cur']:+.5f} [{A['cal_ci_lo']:+.5f}, {A['cal_ci_hi']:+.5f}] |",
         f"| калибрация + xG | {A['cal_xg']:.5f} | {A['cal_xg'] - A['current']:+.5f} (xG върху калибрацията: "
         f"{A['xg_minus_cal']:+.5f} [{A['xg_ci_lo']:+.5f}, {A['xg_ci_hi']:+.5f}]) |",
         "", f"Мачове в късната половина: {int(A['matches'])}. Докладът calibration_fit_20260923.md даде",
         "0.22791 → 0.22722 (−0.00069) върху същите мачове с друга единица (ред мач x изход, не средно на",
         "мач) - при еднакъв брой изходи на мач двете са едно и също число, затова трябва да съвпадат.", "",
         "Калибрацията е приложена през **живата** `prediction_policy.calibrate()` (включена само в процеса",
         "на измерването). Непроменени остават (a = 1.0, не са мерени): двоен шанс, полувреме/край,",
         "корнери, чиста мрежа.", "",
         "## ЧАСТ Б - избор на w (ранна половина) и дали се задържа (късна)", "",
         "| лига | Brier ранна по w = 0 / 0.3 / 0.5 / 0.7 / 1.0 | избрано w | късна: xG − калибрация (95% инт.) | задържа ли се |",
         "|---|---|---|---|---|"]
    for lg in xl:
        s = sel[sel.league == lg].set_index("w")
        r = late.loc[lg]
        holds = r["xg_minus_cal"] < 0 and chosen[lg] > 0
        verdict = ("w = 0 - xG не помага още на ранната" if chosen[lg] == 0 else
                   ("да" + (" (значимо)" if r["xg_ci_hi"] < 0 else " (в рамките на шума)")) if holds else "НЕ")
        L.append(f"| {lg} | " + " / ".join(f"{s.loc[w, 'brier_early']:.5f}" for w in WEIGHTS) +
                 f" | {chosen[lg]} | {r['xg_minus_cal']:+.5f} [{r['xg_ci_lo']:+.5f}, {r['xg_ci_hi']:+.5f}] | {verdict} |")
    L += ["", "## По лига - късна половина", "",
          "| лига | мачове | сегашен | калибрация | калибрация + xG | калибрация − сегашен (95% инт.) |",
          "|---|---|---|---|---|---|"]
    for lg in bf.LEAGUES + ["ALL"]:
        r = late.loc[lg]
        L.append(f"| {lg} | {int(r['matches'])} | {r['current']:.5f} | {r['cal']:.5f} | {r['cal_xg']:.5f} | "
                 f"{r['cal_minus_cur']:+.5f} [{r['cal_ci_lo']:+.5f}, {r['cal_ci_hi']:+.5f}] |")
    E = early.loc["ALL"]
    L += ["", f"За справка, ранна половина (тук са учени и w, и калибрацията - не е доказателство): сегашен "
          f"{E['current']:.5f}, калибрация {E['cal']:.5f}, калибрация + xG {E['cal_xg']:.5f}.", "",
          "## Проверка на очакваните голове (0.3 - 3.5)", "",
          "| лига | w | мерило: сегашен мин-макс | мерило: смес мин-макс | всички двойки днес: сегашен | всички двойки днес: смес |",
          "|---|---|---|---|---|---|"]
    for lg in xl:
        rl, re_ = late.loc[lg], early.loc[lg]
        cmin, cmax = min(rl["lam_min_cur"], re_["lam_min_cur"]), max(rl["lam_max_cur"], re_["lam_max_cur"])
        xmin, xmax = min(rl["lam_min_xg"], re_["lam_min_xg"]), max(rl["lam_max_xg"], re_["lam_max_xg"])
        a = rng_all[lg]
        L.append(f"| {lg} | {chosen[lg]} | {cmin:.2f} - {cmax:.2f} | {xmin:.2f} - {xmax:.2f} | "
                 f"{a[0]:.2f} - {a[1]:.2f} | {a[2]:.2f} - {a[3]:.2f} |")
    F = {f["part"]: f for f in fin}["късна"]
    L += ["", "## Решение", "",
          "Правила: калибрацията остава, ако потвърди подобрението (−0.00069 в доклада); xG остава за",
          "лига само ако (1) избраното w > 0, (2) на КЪСНАТА половина калибрация + xG е по-добра от само",
          "калибрация и (3) сместа остава в 0.3 - 3.5 навсякъде (мерилото и всички двойки отбори днес).", "",
          "| лига | w | задържа се на късната | в 0.3-3.5 (мин-макс) | xG влиза |", "|---|---|---|---|---|"]
    for lg, d in decision.items():
        L.append(f"| {lg} | {d['w']} | {'да' if d['holds'] else 'не'} | "
                 f"{'да' if d['in_range'] else 'НЕ'} ({d['min']:.2f} - {d['max']:.2f}) | **{'да' if d['keep'] else 'не'}** |")
    L += ["", f"**Краен вариант** (калибрация навсякъде + xG само за {', '.join(f'{k} (w={v})' for k, v in keep.items()) or 'никоя лига'}),",
          f"късна половина: Brier {F['final']:.5f}; спрямо сегашния {F['final_minus_cur']:+.5f} "
          f"[{F['ci_lo']:+.5f}, {F['ci_hi']:+.5f}]; спрямо само калибрация {F['final_minus_cal']:+.5f} "
          f"[{F['ci2_lo']:+.5f}, {F['ci2_hi']:+.5f}]."]
    with open(f"validation/kalibraciq_xg_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
