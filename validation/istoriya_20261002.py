"""validation/istoriya_20261002.py - слой на по-дълга история срещу сегашния, на СЪЩАТА късна половина (ZADACHA_RAZVITIE т.3).

Настройките са записани преди резултатите: validation/istoriya_nastroyki_20261002.md (скриптът отказва, ако файлът не е в git).
  сегашен = обучение от features/features_table.csv.gz (от 2023-08-01);
  нов     = същата таблица + редовете от features/features_table_hist.csv.gz с дата < 2023-08-01 (2020-08 -> 2023-07).
Тестовите мачове (is_eval, дата >= layer_lib.EARLY_END) са едни и същи редове с едни и същи lam/mu и признаци в двата варианта -
разликата е само в редовете за обучение. Седмично префитване, само от минали мачове (layer_lib.walk_forward).
Изход: validation/istoriya_20261002.md (+ _leagues.csv, _matches.csv).
Употреба: nice -n 19 venv/bin/python3 validation/istoriya_20261002.py
"""
import json
import os
import subprocess
import sys
import warnings
from multiprocessing import Pool

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from features import layer_lib as L  # noqa: E402

SETTINGS = "validation/istoriya_nastroyki_20261002.md"
HIST_TABLE = os.path.join(ROOT, "features", "features_table_hist.csv.gz")
HIST_END = "2023-08-01"
AB = {"depth": 3, "min_child": 300, "l2": 100, "n_est": 200, "shrink": 1.0, "fset": "AB"}     # = features/layer_train.AB_CFG
OUT = os.path.join(ROOT, "validation", "istoriya_20261002")


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def abc_cfg():
    c = json.load(open(os.path.join(ROOT, "features", "layer_config.json")))
    return {k: c[k] for k in ("depth", "min_child", "l2", "n_est", "shrink", "fset")}


def tables():
    t0 = L.load_table()
    h = pd.read_csv(HIST_TABLE, float_precision="round_trip")
    h = h[h["date"] < HIST_END]
    h = h[~h["fixture_id"].isin(set(t0["fixture_id"]))]
    h["d"] = pd.to_datetime(h["date"])
    h["week"] = h["d"] - pd.to_timedelta(h["d"].dt.weekday, unit="D")
    h["league_code"] = h["league"].map(L.LEAGUE_CODES).astype(float)
    h["is_eval"] = False
    t1 = pd.concat([h[t0.columns.intersection(h.columns)], t0], ignore_index=True, sort=False)
    t1 = t1.sort_values(["d", "fixture_id"]).reset_index(drop=True)
    return t0, t1, h


def run(args):
    variant, cname = args
    t0, t1, _ = tables()
    t = t0 if variant == "current" else t1
    cfg = AB if cname == "AB" else abc_cfg()
    long = L.to_long(t)
    res, _ = L.walk_forward(long, t, {**cfg, "n_list": [cfg["n_est"]]}, L.EARLY_END, None)
    rh, ra = res[cfg["n_est"]]
    late = (t["is_eval"] & (t["d"] >= L.EARLY_END)).to_numpy()
    lam, mu = L.corrected(t, rh, ra, cfg["shrink"])
    return variant, cname, pd.DataFrame({"fixture_id": t["fixture_id"].to_numpy()[late], "lam1": lam[late], "mu1": mu[late]})


def main():
    if not git("ls-files", SETTINGS) or git("status", "--porcelain", SETTINGS):
        sys.exit(f"{SETTINGS} трябва да е комитнат и непроменен преди сравнението")
    t0, t1, h = tables()
    late = t0[t0["is_eval"] & (t0["d"] >= L.EARLY_END)].reset_index(drop=True)
    early = t0[t0["is_eval"] & (t0["d"] >= L.EVAL_START) & (t0["d"] < L.EARLY_END)]
    base = L.calib_base(L.y_matrix(early["hg"], early["ag"]))
    Y = L.y_matrix(late["hg"], late["ag"])
    jobs = [(v, c) for c in ("AB", "ABC") for v in ("current", "new")]
    with Pool(4) as pool:
        outs = pool.map(run, jobs)
    preds = {}
    for v, c, df in outs:
        df = late[["fixture_id"]].merge(df, on="fixture_id", how="left")
        assert df["lam1"].notna().all(), f"{v}/{c}: липсват прогнози"
        preds[(v, c)] = L.probs(df["lam1"].to_numpy(), df["mu1"].to_numpy(), late["rho"].to_numpy())
    P_core = L.probs(late["lam"].to_numpy(), late["mu"].to_numpy(), late["rho"].to_numpy())

    def f(x):
        return f"{x:.5f}"

    lines = ["# Слой на по-дълга история (2020-08 →) срещу сегашния (2023-08 →) — 02.10.2026", "",
             f"Настройки (записани преди резултатите): `{SETTINGS}` (commit {git('log', '-1', '--format=%h %cI', '--', SETTINGS)}).",
             f"Скрипт: `validation/istoriya_20261002.py`. Късна половина: **{len(late)} мача** (дата ≥ {L.EARLY_END}), едни и същи в двата варианта.",
             f"Допълнителни редове за обучение в новия: **{len(h)} мача** ({h['date'].min()} → {h['date'].max()}).", ""]
    summary = {}
    for c in ("AB", "ABC"):
        P0, P1 = preds[("current", c)], preds[("new", c)]
        b0, b1 = L.brier_match(P0, Y), L.brier_match(P1, Y)
        d = L.boot_ci(b1 - b0)
        l0, l1 = L.logloss_match(P0, Y), L.logloss_match(P1, Y)
        a0, a1 = L.calib_coef(P0, Y, base), L.calib_coef(P1, Y, base)
        g0, g1 = L.brier_group(P0, Y), L.brier_group(P1, Y)
        sig_better = d[2] < 0
        in_frame = all(0.9 <= v <= 1.1 for v in a1.values())
        dev0, dev1 = max(abs(v - 1) for v in a0.values()), max(abs(v - 1) for v in a1.values())
        equal_stable = d[1] <= 0 <= d[2] and in_frame and dev1 < dev0
        enter = sig_better or equal_stable
        summary[c] = {"enter": enter, "sig_better": sig_better, "equal_stable": equal_stable, "d": d}
        bc = L.brier_match(P_core, Y).mean()
        lines += [f"## Набор {c}{' (живият)' if c == 'AB' else ' (за сведение, т.4)'}", "",
                  "| мярка | ядро сам | сегашен слой | нов слой | нов − сегашен | 95% интервал |", "|---|---|---|---|---|---|",
                  f"| Brier, 11 изхода | {f(bc)} | {f(b0.mean())} | {f(b1.mean())} | {d[0]:+.5f} | [{d[1]:+.5f}; {d[2]:+.5f}] |"]
        for g in L.GROUPS:
            dg = L.boot_ci(g1[g] - g0[g])
            lines.append(f"| Brier {g} | | {f(g0[g].mean())} | {f(g1[g].mean())} | {dg[0]:+.5f} | [{dg[1]:+.5f}; {dg[2]:+.5f}] |")
        for g in ("1x2", "ou25", "btts"):
            dl = L.boot_ci(l1[g] - l0[g])
            lines.append(f"| log-loss {g} | | {f(l0[g].mean())} | {f(l1[g].mean())} | {dl[0]:+.5f} | [{dl[1]:+.5f}; {dl[2]:+.5f}] |")
        lines += ["", "Коефициент на калибрация на късната половина (рамка 0.9–1.1):", "",
                  "| група | сегашен | нов |", "|---|---|---|"]
        lines += [f"| {g} | {a0[g]:.3f} | {a1[g]:.3f} |" for g in L.GROUPS]
        lines += [f"| max\\|a−1\\| | {dev0:.3f} | {dev1:.3f} |", "",
                  f"Правило: значимо по-добър — {'ДА' if sig_better else 'НЕ'}; равен при по-стабилна калибрация — "
                  f"{'ДА' if equal_stable else 'НЕ'} → **{'НОВИЯТ ВЛИЗА' if enter else 'ОСТАВА СЕГАШНИЯТ'}**.", ""]
        if c == "AB":
            lg = late["league"].to_numpy()
            rows = []
            for name in sorted(set(lg)):
                m = lg == name
                dd = L.boot_ci((b1 - b0)[m])
                rows.append({"league": name, "n": int(m.sum()), "brier_current": b0[m].mean(), "brier_new": b1[m].mean(),
                             "diff": dd[0], "lo": dd[1], "hi": dd[2]})
            lgdf = pd.DataFrame(rows)
            lgdf.round(5).to_csv(OUT + "_leagues.csv", index=False)
            lines += ["По лиги (AB, Brier): по-добре значимо в " + str(int((lgdf.hi < 0).sum())) + ", по-зле значимо в "
                      + str(int((lgdf.lo > 0).sum())) + " от " + str(len(lgdf)) + " (`istoriya_20261002_leagues.csv`).", ""]
            pd.DataFrame({"fixture_id": late["fixture_id"], "league": late["league"], "brier_core": L.brier_match(P_core, Y),
                          "brier_current": b0, "brier_new": b1}).round(6).to_csv(OUT + "_matches.csv", index=False)
    lines += ["## Решение", "",
              (f"AB: **новата версия влиза** ({'значимо по-добра' if summary['AB']['sig_better'] else 'равна при по-стабилна калибрация'})."
               if summary["AB"]["enter"] else "AB: **остава сегашната версия** (правилото не е изпълнено)."), ""]
    open(OUT + ".md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
