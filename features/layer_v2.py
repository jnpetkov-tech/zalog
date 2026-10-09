"""features/layer_v2.py - слоят с новите признаци (features_table_v2) - избор по ранната половина, късната веднъж, ablation
(ZADACHA_VSICHKO_OT_API, етап 1, 09.10.2026). НЕ пипа живия слой: features/layer_lib.py се внася и се разширява САМО в този процес
(TABLE и блоковете), layer_model/current.json и candidate.json не се пипат; кандидатът (ако има) отива в layer_model/v2_candidate/.

Правилата (записани в validation/sloy_v2_nastroyki_20261009.md ПРЕДИ късната половина):
  отправна точка = живата настройка (features/layer_config.json: ABC, depth 4, min_child 100, l2 100, 300 дървета, s 1.0) върху СЪЩАТА таблица;
  кандидати = ABC + нови блокове (E рейтинг, G трансфери, H възраст; F извън игра - само в ablation, не е кандидат);
  избор = най-нисък Brier (11 изхода) на ранната половина; късната - веднъж.
Употреба:
  nice -n 19 venv/bin/python3 features/layer_v2.py select [--procs 12]   -> validation/sloy_v2_rana_20261009.csv, features/layer_v2_config.json
  nice -n 19 venv/bin/python3 features/layer_v2.py late                  -> validation/sloy_v2_20261009.md (+ _leagues.csv, _importance.csv)
"""
import itertools
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
from features import build_features_v2 as B2  # noqa: E402

L.TABLE = B2.OUT
for b, cols in B2.BLOCK_COLS.items():
    L.BLOCKS[b] = cols
L.FEATURE_SETS.update({"ABCE": ["A", "B", "C", "E"], "ABCF": ["A", "B", "C", "F"], "ABCG": ["A", "B", "C", "G"],
                       "ABCH": ["A", "B", "C", "H"], "ABCEGH": ["A", "B", "C", "E", "G", "H"]})
CANDIDATE_FSETS = ["ABCE", "ABCG", "ABCH", "ABCEGH"]
DEPTHS, N_LIST = [3, 4, 5], [200, 300, 400]
MIN_CHILD, L2, SHRINK = 100, 100, 1.0
CFG_PATH = os.path.join(ROOT, "features", "layer_v2_config.json")
BASE_CFG = json.load(open(os.path.join(ROOT, "features", "layer_config.json")))
DATE = "20261009"
T = LONG = None


def init():
    global T, LONG
    T = L.load_table()
    LONG = L.to_long(T)


def early_mask():
    return (T["is_eval"] & (T["d"] >= L.EVAL_START) & (T["d"] < L.EARLY_END)).to_numpy()


def late_mask():
    return (T["is_eval"] & (T["d"] >= L.EARLY_END)).to_numpy()


def run_early(args):
    fset, depth = args
    cfg = {"depth": depth, "min_child": MIN_CHILD, "l2": L2, "n_list": N_LIST, "fset": fset}
    res, _ = L.walk_forward(LONG, T, cfg, L.EVAL_START, L.EARLY_END)
    m = early_mask()
    Y = L.y_matrix(T["hg"][m], T["ag"][m])
    out = []
    for n in N_LIST:
        rh, ra = res[n]
        lam, mu = L.corrected(T, rh, ra, SHRINK)
        P = L.probs(lam[m], mu[m], T["rho"][m])
        out.append({"fset": fset, "depth": depth, "n_est": n, "brier_all": float(L.brier_match(P, Y).mean()),
                    "logloss": float(np.mean(list(L.logloss_match(P, Y).values())))})
    print(out, flush=True)
    return out


def base_cfg_run():
    return {"depth": BASE_CFG["depth"], "min_child": BASE_CFG["min_child"], "l2": BASE_CFG["l2"], "n_list": [BASE_CFG["n_est"]],
            "fset": BASE_CFG["fset"], "shrink": BASE_CFG["shrink"]}


def select(procs):
    init()
    jobs = list(itertools.product(CANDIDATE_FSETS, DEPTHS)) + [("ABC", BASE_CFG["depth"])]
    with Pool(procs, initializer=init) as pool:
        res = [r for lst in pool.map(run_early, jobs) for r in lst]
    df = pd.DataFrame(res)
    base = df[(df["fset"] == "ABC") & (df["depth"] == BASE_CFG["depth"]) & (df["n_est"] == BASE_CFG["n_est"])].iloc[0]
    df["d_vs_base"] = df["brier_all"] - base["brier_all"]
    df.sort_values("brier_all").to_csv(os.path.join(ROOT, "validation", f"sloy_v2_rana_{DATE}.csv"), index=False)
    best = df[df["fset"].isin(CANDIDATE_FSETS)].sort_values("brier_all").iloc[0]
    cfg = {"depth": int(best["depth"]), "min_child": MIN_CHILD, "l2": L2, "fset": best["fset"], "n_est": int(best["n_est"]),
           "shrink": SHRINK, "lr": 0.03, "selected_on": f"ранна половина (дата < {L.EARLY_END})",
           "early_brier_candidate": float(best["brier_all"]), "early_brier_base": float(base["brier_all"]),
           "candidate_beats_base_on_early": bool(best["brier_all"] < base["brier_all"])}
    json.dump(cfg, open(CFG_PATH, "w"), ensure_ascii=False, indent=1)
    print(df.sort_values("brier_all").to_string())
    print("избрано:", cfg)


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def late():
    for p in (os.path.relpath(CFG_PATH, ROOT), f"validation/sloy_v2_nastroyki_{DATE}.md"):
        if not git("ls-files", p) or git("status", "--porcelain", p):
            sys.exit(f"{p} трябва да е комитнат и непроменен ПРЕДИ късната половина")
    cfg = json.load(open(CFG_PATH))
    init()
    m = late_mask()
    Tl = T[m].reset_index(drop=True)
    Y = L.y_matrix(Tl["hg"], Tl["ag"])
    em = early_mask()
    base_rates = L.calib_base(L.y_matrix(T["hg"][em], T["ag"][em]))

    def run(c, want_imp=False):
        rc = {"depth": c["depth"], "min_child": c["min_child"], "l2": c["l2"], "n_list": [c["n_est"]], "fset": c["fset"]}
        res, imp = L.walk_forward(LONG, T, rc, L.EARLY_END, None, want_importance=want_imp)
        rh, ra = res[c["n_est"]]
        lam, mu = L.corrected(T, rh, ra, c["shrink"])
        return L.probs(lam[m], mu[m], T["rho"][m]).reset_index(drop=True), imp

    P0 = L.probs(T["lam"][m], T["mu"][m], T["rho"][m]).reset_index(drop=True)          # ядро
    Pb, _ = run(BASE_CFG)                                                              # живата настройка (отправна точка)
    Pc, imp = run(cfg, want_imp=True)                                                  # кандидатът
    abl = {}
    for f in ["ABCE", "ABCF", "ABCG", "ABCH"]:
        if f != cfg["fset"]:
            abl[f], _ = run({**cfg, "fset": f})
    abl[cfg["fset"]] = Pc

    def meas(P):
        b = L.brier_match(P, Y)
        ll = np.mean(list(L.logloss_match(P, Y).values()), axis=0)
        return b, ll
    b0, l0 = meas(P0)
    bb, lb = meas(Pb)
    bc, lc = meas(Pc)
    d_b = L.boot_ci(bc - bb)
    d_l = L.boot_ci(lc - lb)
    a_c = L.calib_coef(Pc, Y, base_rates)
    # по лига и група: 🟢 значимо по-добре, 🔴 значимо по-зле, 🟡 в шума (кандидат − живата настройка)
    gb = L.brier_group(Pb, Y)
    gc = L.brier_group(Pc, Y)
    rows, worse = [], []
    for lg in sorted(Tl["league"].unique()):
        mk = (Tl["league"] == lg).to_numpy()
        rec = {"league": lg, "n": int(mk.sum())}
        for g in ["all"] + L.GROUPS:
            d = (bc - bb)[mk] if g == "all" else (gc[g] - gb[g])[mk]
            mm, lo, hi = L.boot_ci(d)
            rec[g] = (mm, lo, hi)
        if rec["all"][1] > 0:
            worse.append(lg)
        rows.append(rec)
    sig = lambda t: "🟢" if t[2] < 0 else ("🔴" if t[1] > 0 else "🟡")
    passed = d_b[2] < 0 and d_l[2] < 0 and all(0.9 <= a_c[g] <= 1.1 for g in L.GROUPS) and not worse
    # тежест по група признаци
    grp_imp = {}
    for col, v in imp.items():
        base_name = col[4:] if col.startswith(("own_", "opp_")) else col
        g = next((b for b, cols in L.BLOCKS.items() if base_name in cols and b in L.FEATURE_SETS[cfg["fset"]]), "ядро/общи")
        grp_imp[g] = grp_imp.get(g, 0.0) + float(v)
    names = {"A": "A календар+класиране+форма", "B": "B удари/xG", "C": "C състав/отсъстващи", "E": "E рейтинг", "F": "F извън игра",
             "G": "G трансфери", "H": "H възраст", "ядро/общи": "ядро/общи (lam, лига, ...)"}
    out = [f"# Слой v2 (нови признаци) — късна половина, веднъж — {DATE[6:]}.{DATE[4:6]}.{DATE[:4]}", "",
           f"Настройки и правила: `validation/sloy_v2_nastroyki_{DATE}.md` (комитнати преди този пуск). Скрипт: `features/layer_v2.py late`.",
           f"Късна половина: {int(m.sum())} мача (дата ≥ {L.EARLY_END}). Отправна точка = живата настройка ({BASE_CFG['fset']}, depth "
           f"{BASE_CFG['depth']}, {BASE_CFG['n_est']} дървета) върху същата таблица. Кандидат: **{cfg['fset']}**, depth {cfg['depth']}, "
           f"{cfg['n_est']} дървета (избран по ранната половина).", "",
           "## Резултат", "",
           "| | Brier (11 изхода) | log-loss (1X2, над/под, двата) |", "|---|---|---|",
           f"| ядро | {b0.mean():.5f} | {l0.mean():.5f} |", f"| живият слой (ABC) | {bb.mean():.5f} | {lb.mean():.5f} |",
           f"| кандидат {cfg['fset']} | {bc.mean():.5f} | {lc.mean():.5f} |", "",
           f"- Кандидат − живият слой, Brier: **{d_b[0]:+.5f}** [{d_b[1]:+.5f}; {d_b[2]:+.5f}]",
           f"- Кандидат − живият слой, log-loss: **{d_l[0]:+.5f}** [{d_l[1]:+.5f}; {d_l[2]:+.5f}]",
           f"- Калибрация на кандидата (рамка 0.9–1.1): " + ", ".join(f"{g} {a_c[g]:.3f}" for g in L.GROUPS),
           f"- Лиги значимо по-зле (Brier, интервалът изцяло > 0): {', '.join(worse) if worse else 'няма'}",
           f"- leak_check на новите колони: `validation/tablica_v2_iztichane_{DATE}.md`", "",
           f"**Критерият {'Е изпълнен' if passed else 'НЕ е изпълнен'}.**" + ("" if passed else " Кандидатът не се оставя за Дака."), "",
           "## По лига и пазар (кандидат − живият слой, Brier; 🟢 значимо по-добре, 🔴 значимо по-зле, 🟡 в шума)", "",
           "| лига | мачове | общо | 1X2 | над/под 2.5 | двата | отборни голове |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['league']} | {r['n']} | " + " | ".join(f"{sig(r[g])} {r[g][0]:+.4f}" for g in ["all"] + L.GROUPS) + " |")
    out += ["", "## Тежест по група признаци (кандидатът, дял от gain, средно по седмичните обучения)", "",
            "| група | дял |", "|---|---|"]
    for g, v in sorted(grp_imp.items(), key=lambda x: -x[1]):
        out.append(f"| {names.get(g, g)} | {v:.1%} |")
    out += ["", "## Ablation — всяка нова група поотделно (ABC + група, същите настройки на дървото; само за обяснение)", "",
            "| набор | Brier − живият слой | 95% | log-loss − живият слой | 95% |", "|---|---|---|---|---|"]
    for f in ["ABCE", "ABCF", "ABCG", "ABCH"] + ([cfg["fset"]] if cfg["fset"] not in ("ABCE", "ABCF", "ABCG", "ABCH") else []):
        bf_, lf_ = meas(abl[f])
        d1, d2 = L.boot_ci(bf_ - bb), L.boot_ci(lf_ - lb)
        out.append(f"| {f} | {d1[0]:+.5f} | [{d1[1]:+.5f}; {d1[2]:+.5f}] | {d2[0]:+.5f} | [{d2[1]:+.5f}; {d2[2]:+.5f}] |")
    out += ["", "ABCF (извън игра) е само справка: `api_sidelined.csv` няма записи от 10.2025 до 05.2026 → в късната половина блокът е празен "
            "(виж `validation/sidelined_proverka_20261009.md`)."]
    txt = "\n".join(out) + "\n"
    open(os.path.join(ROOT, "validation", f"sloy_v2_{DATE}.md"), "w", encoding="utf-8").write(txt)
    pd.DataFrame([{"league": r["league"], "n": r["n"], **{f"{g}_{k}": r[g][i] for g in ["all"] + L.GROUPS for i, k in enumerate(["d", "lo", "hi"])}}
                  for r in rows]).to_csv(os.path.join(ROOT, "validation", f"sloy_v2_{DATE}_leagues.csv"), index=False)
    imp.sort_values(ascending=False).to_csv(os.path.join(ROOT, "validation", f"sloy_v2_{DATE}_importance.csv"))
    json.dump({"passed": passed, "d_brier": d_b, "d_logloss": d_l, "calib": a_c, "worse": worse},
              open(os.path.join(ROOT, "validation", f"sloy_v2_{DATE}_result.json"), "w"), ensure_ascii=False, indent=1)
    print(txt)
    return passed


if __name__ == "__main__":
    if sys.argv[1] == "select":
        select(int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 12)
    elif sys.argv[1] == "late":
        late()
