"""validation/trener_20261007.py - слой ABC с треньор по номер (старо) срещу по номер или име (ново), на СЪЩАТА късна половина.

Настройки преди резултатите: validation/trener_nastroyki_20261007.md (скриптът отказва, ако файлът не е комитнат и непроменен).
Двете таблици се строят тук от едни и същи CSV и ядро (features/core_lam_mu.csv) с build_features.COACH_BY_NAME = False / True.
Изход: validation/trener_20261007.md (+ _matches.csv). Употреба: nice -n 19 venv/bin/python3 validation/trener_20261007.py
"""
import json
import os
import subprocess
import sys
import tempfile
import warnings
from multiprocessing import Pool

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from features import build_features as bf  # noqa: E402
from features import layer_lib as L  # noqa: E402

SETTINGS = "validation/trener_nastroyki_20261007.md"
OUT = os.path.join(ROOT, "validation", "trener_20261007")
TMP = tempfile.mkdtemp(prefix="trener_")


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def abc_cfg():
    c = json.load(open(os.path.join(ROOT, "features", "layer_config.json")))
    return {k: c[k] for k in ("depth", "min_child", "l2", "n_est", "shrink", "fset", "lr")}


def build_tables():
    core = pd.read_csv(os.path.join(ROOT, "features", "core_lam_mu.csv"))
    raw = bf.index_raw(bf.load_raw())
    for flag, name in ((False, "old"), (True, "new")):
        bf.COACH_BY_NAME = flag
        bf.build(core, raw).to_csv(os.path.join(TMP, f"{name}.csv.gz"), index=False)


def load(name):
    L.TABLE = os.path.join(TMP, f"{name}.csv.gz")
    return L.load_table()


def run(name):
    t = load(name)
    cfg = abc_cfg()
    res, _ = L.walk_forward(L.to_long(t), t, {**cfg, "n_list": [cfg["n_est"]]}, L.EARLY_END, None)
    rh, ra = res[cfg["n_est"]]
    late = (t["is_eval"] & (t["d"] >= L.EARLY_END)).to_numpy()
    lam, mu = L.corrected(t, rh, ra, cfg["shrink"])
    return name, pd.DataFrame({"fixture_id": t["fixture_id"].to_numpy()[late], "lam1": lam[late], "mu1": mu[late]})


def main():
    if not git("ls-files", SETTINGS) or git("status", "--porcelain", SETTINGS):
        sys.exit(f"{SETTINGS} трябва да е комитнат и непроменен преди сравнението")
    build_tables()
    t_old, t_new = load("old"), load("new")
    chg = {c: int(((t_old[c] != t_new[c]) & ~(t_old[c].isna() & t_new[c].isna())).sum())
           for c in ("h_coach_new", "a_coach_new", "h_coach_tenure_days", "a_coach_tenure_days")}
    other = [c for c in t_old.columns if c not in chg and c not in ("d", "week") and not t_old[c].equals(t_new[c])]
    assert not other, f"променени други колони: {other}"
    t = t_old
    late = t[t["is_eval"] & (t["d"] >= L.EARLY_END)].reset_index(drop=True)
    early = t[t["is_eval"] & (t["d"] >= L.EVAL_START) & (t["d"] < L.EARLY_END)]
    base = L.calib_base(L.y_matrix(early["hg"], early["ag"]))
    Y = L.y_matrix(late["hg"], late["ag"])
    with Pool(2) as pool:
        outs = dict(pool.map(run, ["old", "new"]))
    P = {}
    for k, df in outs.items():
        df = late[["fixture_id"]].merge(df, on="fixture_id", how="left")
        assert df["lam1"].notna().all(), f"{k}: липсват прогнози"
        P[k] = L.probs(df["lam1"].to_numpy(), df["mu1"].to_numpy(), late["rho"].to_numpy())
    P_core = L.probs(late["lam"].to_numpy(), late["mu"].to_numpy(), late["rho"].to_numpy())
    b0, b1 = L.brier_match(P["old"], Y), L.brier_match(P["new"], Y)
    d = L.boot_ci(b1 - b0)
    l0, l1 = L.logloss_match(P["old"], Y), L.logloss_match(P["new"], Y)
    dl = L.boot_ci(l1["1x2"] - l0["1x2"])
    a0, a1 = L.calib_coef(P["old"], Y, base), L.calib_coef(P["new"], Y, base)
    g0, g1 = L.brier_group(P["old"], Y), L.brier_group(P["new"], Y)
    late_chg = late["fixture_id"].isin(set(t_new.loc[(t_old["h_coach_new"] != t_new["h_coach_new"]) |
                                                     (t_old["a_coach_new"] != t_new["a_coach_new"]) |
                                                     (t_old["h_coach_tenure_days"] != t_new["h_coach_tenure_days"]) |
                                                     (t_old["a_coach_tenure_days"] != t_new["a_coach_tenure_days"]), "fixture_id"]))
    ok1 = d[1] <= 0
    ok2 = dl[1] <= 0
    dev0, dev1 = max(abs(v - 1) for v in a0.values()), max(abs(v - 1) for v in a1.values())
    ok3 = all(0.9 <= v <= 1.1 for v in a1.values()) or dev1 <= dev0
    enter = ok1 and ok2 and ok3

    def f(x):
        return f"{x:.5f}"

    lines = ["# Слой ABC: треньор по номер (старо) срещу по номер или име (ново) — 07.10.2026", "",
             f"Настройки (записани преди резултатите): `{SETTINGS}` (commit {git('log', '-1', '--format=%h %cI', '--', SETTINGS)}).",
             f"Скрипт: `validation/trener_20261007.py`. Таблица: {len(t)} мача; променени стойности: "
             + ", ".join(f"`{k}` {v}" for k, v in chg.items()) + "; други колони — 0 промени.",
             f"Късна половина: **{len(late)} мача** (дата ≥ {L.EARLY_END}), от тях с променен признак за треньора: {int(late_chg.sum())}.", "",
             "| мярка | ядро сам | старо | ново | ново − старо | 95% интервал |", "|---|---|---|---|---|---|",
             f"| Brier, 11 изхода | {f(L.brier_match(P_core, Y).mean())} | {f(b0.mean())} | {f(b1.mean())} | {d[0]:+.5f} | [{d[1]:+.5f}; {d[2]:+.5f}] |"]
    for g in L.GROUPS:
        dg = L.boot_ci(g1[g] - g0[g])
        lines.append(f"| Brier {g} | | {f(g0[g].mean())} | {f(g1[g].mean())} | {dg[0]:+.5f} | [{dg[1]:+.5f}; {dg[2]:+.5f}] |")
    for g in ("1x2", "ou25", "btts"):
        dg = L.boot_ci(l1[g] - l0[g])
        lines.append(f"| log-loss {g} | | {f(l0[g].mean())} | {f(l1[g].mean())} | {dg[0]:+.5f} | [{dg[1]:+.5f}; {dg[2]:+.5f}] |")
    m = late_chg.to_numpy()
    if m.any():
        dm = L.boot_ci((b1 - b0)[m])
        lines += ["", f"Само мачовете с променен признак ({int(m.sum())}): Brier ново − старо {dm[0]:+.5f} [{dm[1]:+.5f}; {dm[2]:+.5f}]."]
    lines += ["", "Калибрация на късната половина (рамка 0.9–1.1):", "", "| група | старо | ново |", "|---|---|---|"]
    lines += [f"| {g} | {a0[g]:.3f} | {a1[g]:.3f} |" for g in L.GROUPS]
    lines += ["", "## Решение", "",
              f"1. Brier не значимо по-лош — {'ДА' if ok1 else 'НЕ'}; 2. log-loss 1X2 не значимо по-лош — {'ДА' if ok2 else 'НЕ'}; "
              f"3. калибрация — {'ДА' if ok3 else 'НЕ'} → **{'ПОПРАВКАТА ВЛИЗА' if enter else 'ПОПРАВКАТА НЕ ВЛИЗА'}**.", ""]
    pd.DataFrame({"fixture_id": late["fixture_id"], "league": late["league"], "coach_changed": m,
                  "brier_core": L.brier_match(P_core, Y), "brier_old": b0, "brier_new": b1}).round(6).to_csv(OUT + "_matches.csv", index=False)
    open(OUT + ".md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
