"""validation/top4_yadro2_20261007.py - ZADACHA_MODELI_2, ЧАСТ 2 (07.10.2026): топ 4, второ пускане с ранна част от 2023-08-01.

Настройки - validation/top4_yadro2_nastroyki_20261007.md (записани преди пускането). Функциите (варианти, walk-forward, мерки) - от
validation/top4_yadro_20261007.py без промяна; разлика - само прозорецът (START = 2023-08-01, както features/core_lam_mu.py).
Употреба: --early (избор, записва се) ; --late (веднъж, само ако има избран) ; --report (ако няма избран).
"""
import json
import os
import sys

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
from multiprocessing import Pool  # noqa: E402

import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

import backtest_full as bf  # noqa: E402
import football_lib as fl  # noqa: E402
import top4_yadro_20261007 as Y  # noqa: E402

START = pd.Timestamp("2023-08-01")
SEASON2 = "2024-07-01"
V = Y.V
P = lambda s: os.path.join(V, f"top4_yadro2_20261007_{s}")
SEL = P("izbor.json")


def run2(args):
    league = args[0]
    fin = fl.load_league_data(league).dropna(subset=["home_goals", "away_goals"])
    bf.PERIOD_DAYS = int((fin["date"].max() - START).days) + 1        # като core_lam_mu.job()
    return Y.run(args)


def table(d, base, title):
    A = d[d.variant == "А"].sort_values("fixture_id").reset_index(drop=True)
    mA = Y.per_match(A)
    out = [f"### {title} — {len(A)} мача", "", "| вариант | Brier 11 | разлика спрямо А, 95% | Brier 1X2 | log-loss 1X2 | равни модел / реално | ср. rho |",
           "|---|---|---|---|---|---|---|"]
    res = {}
    for v in Y.VARIANTS:
        X = d[d.variant == v].sort_values("fixture_id").reset_index(drop=True)
        mX = Y.per_match(X)
        ds = Y.describe(X, mX, base)
        ci = Y.boot(mX["b11"] - mA["b11"]) if v != "А" else None
        res[v] = ds["b11"]
        out.append(f"| {v} | {ds['b11']:.5f} | {Y.fmt_ci(ci) if ci else '—'} | {ds['b1x2']:.5f} | {ds['ll1x2']:.5f} | "
                   f"{ds['draw_model'] * 100:.1f}% / {ds['draw_real'] * 100:.1f}% | {ds['rho_mean']:+.3f} |")
    return out + [""], res


def early():
    jobs = [(lg, v, "early") for v in Y.VARIANTS for lg in Y.LEAGUES]
    with Pool(16) as pool:
        parts = pool.map(run2, jobs, chunksize=1)
    d = pd.concat(parts, ignore_index=True)
    d = d[d["date"] >= str(START.date())]
    d.to_csv(P("early_matches.csv"), index=False)
    base = Y.base_freq(d[d.variant == "А"])
    md = ["# ЧАСТ 2 (ZADACHA_MODELI_2) — ранна част 2023-08-01 ≤ дата < 2025-09-23 (избор)", ""]
    t, res = table(d, base, "Двата сезона заедно (по това е изборът)")
    md += t
    for lo, hi, nm in (("2023-08-01", SEASON2, "Сезон 2023/24 (само за сведение)"), (SEASON2, Y.EARLY_END, "Сезон 2024/25 (само за сведение)")):
        md += table(d[(d.date >= lo) & (d.date < hi)], base, nm)[0]
    cand = min((v for v in Y.VARIANTS if v != "А"), key=lambda v: res[v])
    chosen = cand if res[cand] < res["А"] else None
    json.dump({"chosen": chosen, "early_b11": res, "rule": "най-нисък Brier 11 на ранната (2023-08-01..2025-09-22) сред Б/В/Г, ако < А"},
              open(SEL, "w"), ensure_ascii=False, indent=1)
    md += [f"**Избор (правило от настройките):** {'вариант ' + chosen if chosen else 'нито един от Б/В/Г не е под А - край, късната не се пуска'}."]
    open(P("early.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))


def late():
    sel = json.load(open(SEL))
    ch = sel["chosen"]
    if not ch:
        print("няма избран - късната не се пуска")
        return
    jobs = [(lg, v, "late") for v in ("А", ch) for lg in Y.LEAGUES]
    with Pool(8) as pool:
        parts = pool.map(run2, jobs, chunksize=1)
    d = pd.concat(parts, ignore_index=True)
    d.to_csv(P("late_matches.csv"), index=False)
    e = pd.read_csv(P("early_matches.csv"))
    base = Y.base_freq(e[e.variant == "А"])
    A = d[d.variant == "А"].sort_values("fixture_id").reset_index(drop=True)
    X = d[d.variant == ch].sort_values("fixture_id").reset_index(drop=True)
    mA, mX = Y.per_match(A), Y.per_match(X)
    dA, dX = Y.describe(A, mA, base), Y.describe(X, mX, base)
    ci = {k: Y.boot(mX[k] - mA[k]) for k in ("b11", "b1x2", "ll1x2") + tuple(f"b_{g}" for g in Y.GROUPS)}
    lg_ci = {lg: Y.boot((mX["b11"] - mA["b11"])[A.league == lg]) for lg in Y.LEAGUES}
    c1 = ci["b11"][2] < 0 or (ci["b1x2"][2] < 0 and all(ci[f"b_{g}"][1] <= 0 for g in Y.GROUPS))
    c2 = all(lg_ci[lg][1] <= 0 for lg in Y.LEAGUES)
    passed = c1 and c2
    json.dump({"chosen": ch, "passed": bool(passed), "c1": bool(c1), "c2": bool(c2), "ci": ci, "league_ci": lg_ci, "A": dA, "X": dX},
              open(P("late.json"), "w"), ensure_ascii=False, indent=1, default=float)
    md = ["# ЧАСТ 2 (ZADACHA_MODELI_2) — топ 4, второ пускане", "",
          f"**Решение: {'КРИТЕРИЯТ Е ИЗПЪЛНЕН — вариант ' + ch if passed else 'КРИТЕРИЯТ НЕ Е ИЗПЪЛНЕН — нищо не влиза, край на тази линия'}.**", "",
          "Настройки: `validation/top4_yadro2_nastroyki_20261007.md`. Ранна: `validation/top4_yadro2_20261007_early.md`.", "",
          open(P("early.md"), encoding="utf-8").read().split("\n", 2)[2].strip(), "",
          f"## Късна половина (пусната веднъж): А срещу {ch}, {len(A)} мача", "", f"| мярка | А | {ch} | разлика, 95% |", "|---|---|---|---|",
          f"| Brier 11 | {dA['b11']:.5f} | {dX['b11']:.5f} | {Y.fmt_ci(ci['b11'])} |", f"| Brier 1X2 | {dA['b1x2']:.5f} | {dX['b1x2']:.5f} | {Y.fmt_ci(ci['b1x2'])} |",
          f"| log-loss 1X2 | {dA['ll1x2']:.5f} | {dX['ll1x2']:.5f} | {Y.fmt_ci(ci['ll1x2'])} |"]
    md += [f"| Brier група {g} | | | {Y.fmt_ci(ci['b_' + g])} |" for g in Y.GROUPS]
    md += [f"| равни модел / реално | {dA['draw_model'] * 100:.1f}% / {dA['draw_real'] * 100:.1f}% | {dX['draw_model'] * 100:.1f}% | |",
           f"| 1-1 модел / реално | {dA['p11_model'] * 100:.1f}% / {dA['p11_real'] * 100:.1f}% | {dX['p11_model'] * 100:.1f}% | |"]
    md += [f"| калибрация a {g} | {dA['a_' + g]:.3f} | {dX['a_' + g]:.3f} | |" for g in Y.GROUPS]
    md += ["", "По лига (Brier 11, " + ch + " − А): " + "; ".join(f"{lg} {Y.fmt_ci(c)}" for lg, c in lg_ci.items()), "",
           f"Критерий: (1) {'изпълнено' if c1 else 'не'}; (2) {'изпълнено' if c2 else 'не'}.", ""]
    open(P("report.md").replace("_report.md", ".md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))


def report():
    sel = json.load(open(SEL))
    if sel["chosen"]:
        print("има избран - ползвай --late")
        return
    md = ["# ЧАСТ 2 (ZADACHA_MODELI_2) — топ 4, второ пускане", "",
          "**Решение: КРИТЕРИЯТ НЕ Е ИЗПЪЛНЕН — нищо не влиза, край на тази линия.** И с ранна част от два сезона нито един от Б/В/Г не е под А; "
          "късната не е пускана.", "", open(P("early.md"), encoding="utf-8").read().split("\n", 2)[2].strip(), ""]
    open(os.path.join(V, "top4_yadro2_20261007.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    {"--early": early, "--late": late, "--report": report}.get(next((a for a in sys.argv if a.startswith("--")), ""), lambda: print(__doc__))()
