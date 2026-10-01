"""features/layer_eval.py - КЪСНАТА половина, веднъж (ZADACHA_TABLICA, стъпка 3, 01.10.2026).

Отказва да тръгне, ако features/layer_config.json не е комитнат и непроменен (настройките се записват в git ПРЕДИ късната половина).
Мерки (регистрирани в validation/sloy_nastroyki_20261001.md): Brier и log-loss за 1X2, над/под 2.5, двата вкарват; коефициент на калибрация
(рамка 0.9-1.1); 95% интервали (bootstrap по мач, 2000, seed 42); ядро сам срещу ядро+слой, по лиги; тежест на признаците. Пазарът - само справка.
Изход: validation/sloy_20261001.md (+ _leagues.csv, _importance.csv, _matches.csv).
Употреба: nice -n 19 venv/bin/python3 features/layer_eval.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from features import layer_lib as L  # noqa: E402

CFG_PATH = "features/layer_config.json"
N_BOOT = 2000


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def require_committed_config():
    if not git("ls-files", CFG_PATH):
        sys.exit(f"{CFG_PATH} не е в git - първо го комитни (настройките се записват ПРЕДИ късната половина)")
    if git("status", "--porcelain", CFG_PATH):
        sys.exit(f"{CFG_PATH} има некомитнати промени")
    return git("log", "-1", "--format=%H %cI", "--", CFG_PATH)


def ci_diff(d):
    m, lo, hi = L.boot_ci(d, N_BOOT)
    return m, lo, hi


def market_reference(T, P_core, P_layer):
    """Справка: обезвиговани пазарни вероятности за 1X2 / над-под 2.5 / двата вкарват от predictions_log (първото налично коефициент
    на пазар), само за мачовете от късната половина, които са логнати. Brier по същите групи като за модела."""
    con = sqlite3.connect("file:" + os.path.join(ROOT, "predictions.db") + "?mode=ro", uri=True)
    d = pd.read_sql_query("select fixture_id, market_code, market_odds from predictions_log where market_odds is not null", con)
    con.close()
    od = d.groupby(["fixture_id", "market_code"])["market_odds"].first().unstack()
    rows = []
    idx = {f: i for i, f in enumerate(T["fixture_id"])}
    for fx, r in od.iterrows():
        if fx not in idx or idx[fx] not in P_core.index:
            continue
        i = idx[fx]
        rec = {"fixture_id": fx}
        for grp, codes in (("1x2", ["home_win", "draw", "away_win"]), ("ou25", ["over25", "under25"]), ("btts", ["btts_yes", "btts_no"])):
            if all(c in r.index and pd.notna(r[c]) for c in codes):
                inv = np.array([1.0 / r[c] for c in codes])
                for c, v in zip(codes, inv / inv.sum()):
                    rec[f"m_{c}"] = v
        rows.append((i, rec))
    return rows


def main():
    cfgc = require_committed_config()
    cfg = json.load(open(os.path.join(ROOT, CFG_PATH)))
    T = L.load_table()
    LONG = L.to_long(T)
    n_list = [cfg["n_est"]]
    run_cfg = {"depth": cfg["depth"], "min_child": cfg["min_child"], "l2": cfg["l2"], "n_list": n_list, "fset": cfg["fset"]}
    early = (T["is_eval"] & (T["d"] >= L.EVAL_START) & (T["d"] < L.EARLY_END)).to_numpy()
    late = (T["is_eval"] & (T["d"] >= L.EARLY_END)).to_numpy()
    res_e, _ = L.walk_forward(LONG, T, run_cfg, L.EVAL_START, L.EARLY_END)
    res_l, imp = L.walk_forward(LONG, T, run_cfg, L.EARLY_END, None, want_importance=True)
    rh = np.where(early, res_e[cfg["n_est"]][0], res_l[cfg["n_est"]][0])
    ra = np.where(early, res_e[cfg["n_est"]][1], res_l[cfg["n_est"]][1])
    lam1, mu1 = L.corrected(T, rh, ra, cfg["shrink"])
    sel = early | late
    assert not np.isnan(lam1[sel]).any()
    P0 = L.probs(T["lam"][sel], T["mu"][sel], T["rho"][sel])
    P1 = L.probs(lam1[sel], mu1[sel], T["rho"][sel])
    P0.index = P1.index = np.where(sel)[0]
    Y = pd.DataFrame(L.y_matrix(T["hg"][sel], T["ag"][sel]), index=P0.index, columns=L.CODES)
    e_idx, l_idx = P0.index[early[sel]], P0.index[late[sel]]
    Ye, Yl = Y.loc[e_idx].to_numpy(), Y.loc[l_idx].to_numpy()
    base = L.calib_base(Ye)

    # ---- Brier и log-loss (късна половина, некалибрирано)
    b0, b1 = L.brier_match(P0.loc[l_idx], Yl), L.brier_match(P1.loc[l_idx], Yl)
    g0, g1 = L.brier_group(P0.loc[l_idx], Yl), L.brier_group(P1.loc[l_idx], Yl)
    l0, l1 = L.logloss_match(P0.loc[l_idx], Yl), L.logloss_match(P1.loc[l_idx], Yl)
    ll0, ll1 = np.mean([l0[k] for k in l0], axis=0), np.mean([l1[k] for k in l1], axis=0)
    d_all = ci_diff(b1 - b0)
    d_ll = ci_diff(ll1 - ll0)
    # ---- калибрация на късната (b от ранната)
    a0, a1 = L.calib_coef(P0.loc[l_idx], Yl, base), L.calib_coef(P1.loc[l_idx], Yl, base)
    rng = np.random.default_rng(42)
    boots = {"core": [], "layer": []}
    n = len(l_idx)
    for _ in range(500):
        ii = rng.integers(0, n, n)
        boots["core"].append(L.calib_coef(P0.loc[l_idx].iloc[ii], Yl[ii], base))
        boots["layer"].append(L.calib_coef(P1.loc[l_idx].iloc[ii], Yl[ii], base))
    def ca(which, g):
        v = [b[g] for b in boots[which]]
        return np.percentile(v, 2.5), np.percentile(v, 97.5)
    # ---- с живата калибрация (a, b от ранната половина, поотделно за всеки вариант)
    ae0, ae1 = L.calib_coef(P0.loc[e_idx], Ye, base), L.calib_coef(P1.loc[e_idx], Ye, base)
    C0 = L.apply_cal(P0.loc[l_idx], ae0, base)
    C1 = L.apply_cal(P1.loc[l_idx], ae1, base)
    cb0, cb1 = L.brier_match(C0, Yl), L.brier_match(C1, Yl)
    d_cal = ci_diff(cb1 - cb0)
    # ---- по лиги
    lg = T["league"].to_numpy()[sel][late[sel]]
    rows = []
    for league in sorted(set(lg)):
        m = lg == league
        dm, lo, hi = ci_diff((b1 - b0)[m])
        dl, llo, lhi = ci_diff((ll1 - ll0)[m])
        rows.append({"league": league, "matches": int(m.sum()), "brier_core": b0[m].mean(), "brier_layer": b1[m].mean(),
                     "diff": dm, "lo": lo, "hi": hi, "ll_diff": dl, "ll_lo": llo, "ll_hi": lhi})
    bylg = pd.DataFrame(rows)
    worse = int((bylg["lo"] > 0).sum())
    better = int((bylg["hi"] < 0).sum())
    bylg.round(6).to_csv(os.path.join(ROOT, "validation", "sloy_20261001_leagues.csv"), index=False)
    # ---- по групи (diff + CI)
    grp = {}
    for g in L.GROUPS:
        grp[g] = (g0[g].mean(), g1[g].mean(), ci_diff(g1[g] - g0[g]))
    llg = {k: (l0[k].mean(), l1[k].mean(), ci_diff(l1[k] - l0[k])) for k in l0}
    # ---- тежест на признаците
    imp = imp.sort_values(ascending=False)
    imp.round(6).to_csv(os.path.join(ROOT, "validation", "sloy_20261001_importance.csv"), header=["gain_share"])
    blocks = {}
    for c, v in imp.items():
        base_name = c.replace("own_", "").replace("opp_", "")
        blk = ("ядро/лига" if c in ("own_lam", "opp_lam", "lam_total", "rho", "is_home", "is_cup", "league_code", "n_teams")
               else "календар" if base_name in L.F_CAL + ["rest_diff_own"] else "класиране" if base_name in L.F_STAND
               else "форма (резултати/събития)" if base_name in L.F_FORM else "удари/xG" if base_name in L.F_SHOTS
               else "състав/отсъстващи/треньор/контузени" if base_name in L.F_SQUAD else "съдия/час")
        blocks[blk] = blocks.get(blk, 0) + v
    # ---- справка: пазар
    mk = market_reference(T, P0, P1)
    mrows = []
    for i, rec in mk:
        if i not in l_idx:
            continue
        pos = list(l_idx).index(i)
        for grp_name, codes in (("1x2", ["home_win", "draw", "away_win"]), ("ou25", ["over25", "under25"]), ("btts", ["btts_yes", "btts_no"])):
            if all(f"m_{c}" in rec for c in codes):
                ys = Yl[pos, [L.CODES.index(c) for c in codes]]
                mrows.append({"fixture_id": rec["fixture_id"], "group": grp_name,
                              "core": np.mean([(P0.loc[i, c] - y) ** 2 for c, y in zip(codes, ys)]),
                              "layer": np.mean([(P1.loc[i, c] - y) ** 2 for c, y in zip(codes, ys)]),
                              "market": np.mean([(rec[f"m_{c}"] - y) ** 2 for c, y in zip(codes, ys)])})
    mk_df = pd.DataFrame(mrows)
    # ---- критерий
    k1 = d_all[2] < 0
    k2 = d_ll[2] < 0
    k3 = worse <= 4
    k4 = all(0.9 <= a1[g] <= 1.1 for g in ("1x2", "ou25", "btts"))
    passed = bool(k1 and k2 and k3 and k4)
    pd.DataFrame({"fixture_id": T["fixture_id"][sel][late[sel]].to_numpy(), "league": lg, "lam": T["lam"][sel][late[sel]].to_numpy(),
                  "mu": T["mu"][sel][late[sel]].to_numpy(), "lam_layer": lam1[sel][late[sel]], "mu_layer": mu1[sel][late[sel]],
                  "hg": T["hg"][sel][late[sel]].to_numpy(), "ag": T["ag"][sel][late[sel]].to_numpy()}).round(5).to_csv(
        os.path.join(ROOT, "validation", "sloy_20261001_matches.csv"), index=False)

    f = lambda x: f"{x:.5f}"
    sg = lambda lo, hi: "значимо по-добре" if hi < 0 else "значимо по-зле" if lo > 0 else "в рамките на шума"
    L_ = ["# Обучен слой върху ядрото — късна половина — 01.10.2026", "",
          "Предварителна регистрация (настройки, мерки, критерий): `sloy_nastroyki_20261001.md`; избор на настройките (само ранна половина): "
          "`sloy_rana_20261001.md`, `sloy_rana2_20261001.md`. Таблица с признаци и проверка за изтичане: `features/README.md`, "
          "`tablica_iztichane_20261001.md`. Скрипт: `features/layer_eval.py`.", "",
          f"Настройките са комитнати преди този пуск: `features/layer_config.json` @ `{cfgc}`.", "",
          f"**Настройка:** дълбочина {cfg['depth']}, мин. {cfg['min_child']} мача/лист, L2 {cfg['l2']}, {cfg['n_est']} дървета, s = {cfg['shrink']}, набор признаци {cfg['fset']}.",
          f"**Късна половина:** {int(late.sum())} мача (дата ≥ {L.EARLY_END}; мерилото + новите изтеглени). Ранна: {int(early.sum())}. Слоят се учи всяка седмица само от минали мачове.", "",
          "## Главният резултат (некалибрирано)", "",
          "| мярка | ядро сам | ядро + слой | разлика (слой − ядро) | 95% интервал | |", "|---|---|---|---|---|---|",
          f"| Brier, 11 изхода | {f(b0.mean())} | {f(b1.mean())} | {d_all[0]:+.5f} | [{d_all[1]:+.5f}; {d_all[2]:+.5f}] | {sg(d_all[1], d_all[2])} |",
          f"| log-loss (1X2, над/под, двата вкарват; средно) | {f(ll0.mean())} | {f(ll1.mean())} | {d_ll[0]:+.5f} | [{d_ll[1]:+.5f}; {d_ll[2]:+.5f}] | {sg(d_ll[1], d_ll[2])} |",
          f"| Brier след живата калибрация (a, b от ранната) | {f(cb0.mean())} | {f(cb1.mean())} | {d_cal[0]:+.5f} | [{d_cal[1]:+.5f}; {d_cal[2]:+.5f}] | {sg(d_cal[1], d_cal[2])} |", "",
          "## По групи", "", "| група | Brier ядро | Brier слой | разлика | 95% интервал | |", "|---|---|---|---|---|---|"]
    for g, (x0, x1, (dm, lo, hi)) in grp.items():
        L_.append(f"| {g} | {f(x0)} | {f(x1)} | {dm:+.5f} | [{lo:+.5f}; {hi:+.5f}] | {sg(lo, hi)} |")
    L_ += ["", "| log-loss | ядро | слой | разлика | 95% интервал | |", "|---|---|---|---|---|---|"]
    for g, (x0, x1, (dm, lo, hi)) in llg.items():
        L_.append(f"| {g} | {f(x0)} | {f(x1)} | {dm:+.5f} | [{lo:+.5f}; {hi:+.5f}] | {sg(lo, hi)} |")
    L_ += ["", "## Коефициент на калибрация на късната половина (рамка 0.9–1.1; b — честотата на ранната)", "",
           "| група | ядро | 95% | ядро + слой | 95% |", "|---|---|---|---|---|"]
    for g in L.GROUPS:
        c0, c1 = ca("core", g), ca("layer", g)
        L_.append(f"| {g} | {a0[g]:.3f} | [{c0[0]:.3f}; {c0[1]:.3f}] | {a1[g]:.3f} | [{c1[0]:.3f}; {c1[1]:.3f}] |")
    L_ += ["", "## Ядро сам срещу ядро + слой, по лиги (Brier, 11 изхода)", "",
           "| лига | мачове | ядро | слой | разлика | 95% интервал | |", "|---|---|---|---|---|---|---|"]
    for r in bylg.itertuples():
        L_.append(f"| {r.league} | {r.matches} | {f(r.brier_core)} | {f(r.brier_layer)} | {r.diff:+.5f} | [{r.lo:+.5f}; {r.hi:+.5f}] | {sg(r.lo, r.hi)} |")
    L_ += ["", f"Лиги значимо по-добре: **{better}**, значимо по-зле: **{worse}**, останалите — в рамките на шума.", "",
           "## Кои признаци носят тежест (среден дял от gain, всички седмични фитове на късната половина)", "",
           "| блок | дял от тежестта |", "|---|---|"]
    for k, v in sorted(blocks.items(), key=lambda kv: -kv[1]):
        L_.append(f"| {k} | {v:.3f} |")
    L_ += ["", "Най-тежките 25 признака (`own_` = собственият отбор, `opp_` = противникът):", "", "| признак | дял |", "|---|---|"]
    for c, v in imp.head(25).items():
        L_.append(f"| {c} | {v:.4f} |")
    if len(mk_df):
        L_ += ["", "## Справка: пазарът (не е в обучението, не е признак)", "",
               "Логнатите мачове от късната половина с коефициенти в `predictions_log` (първият наличен коефициент, обезвигован). Brier по същите групи.", "",
               "| група | мачове | ядро | слой | пазар |", "|---|---|---|---|---|"]
        for g, s in mk_df.groupby("group"):
            L_.append(f"| {g} | {s['fixture_id'].nunique()} | {f(s['core'].mean())} | {f(s['layer'].mean())} | {f(s['market'].mean())} |")
        al = mk_df.groupby("fixture_id")[["core", "layer", "market"]].mean()
        dd = ci_diff((al["layer"] - al["market"]).to_numpy())
        d0 = ci_diff((al["core"] - al["market"]).to_numpy())
        L_ += ["", f"Разлика с пазара (по мач, средно по групите): ядро {d0[0]:+.5f} [{d0[1]:+.5f}; {d0[2]:+.5f}], ядро+слой {dd[0]:+.5f} [{dd[1]:+.5f}; {dd[2]:+.5f}] "
                   f"(n = {len(al)} мача; положително = пазарът е по-точен). Това е само справка.", ""]
    L_ += ["## Критерий (регистриран преди пуска)", "",
           f"1. Brier: разликата е със 95% интервал изцяло под нулата — {'ДА' if k1 else 'НЕ'} ({d_all[0]:+.5f}, горна граница {d_all[2]:+.5f}).",
           f"2. log-loss: изцяло под нулата — {'ДА' if k2 else 'НЕ'} ({d_ll[0]:+.5f}, горна граница {d_ll[2]:+.5f}).",
           f"3. Не повече от 4 лиги значимо по-зле — {'ДА' if k3 else 'НЕ'} ({worse}).",
           f"4. Калибрация на 1x2, над/под, двата вкарват за ядро+слой в 0.9–1.1 — {'ДА' if k4 else 'НЕ'} "
           f"({a1['1x2']:.3f} / {a1['ou25']:.3f} / {a1['btts']:.3f}).", "",
           f"**{'КРИТЕРИЯТ Е ИЗПЪЛНЕН' if passed else 'КРИТЕРИЯТ НЕ Е ИЗПЪЛНЕН'}**" + (" — слоят може да се предлага (стъпка 4)." if passed else " — нищо не се предлага за живия код.")]
    out = "\n".join(L_) + "\n"
    open(os.path.join(ROOT, "validation", "sloy_20261001.md"), "w", encoding="utf-8").write(out)
    json.dump({"passed": passed, "k": [bool(k1), bool(k2), bool(k3), bool(k4)]}, open("/tmp/sloy_verdict.json", "w"))
    print(out)


if __name__ == "__main__":
    main()
