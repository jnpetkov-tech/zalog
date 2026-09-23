"""
validation/xg_quality.py - ZADACHA_MERILO.md, ЧАСТ Б (23.09.2026).

Въпрос: xG от API-то предсказва ли головете в СЛЕДВАЩИЯ мач на отбора
по-добре от самите голове? Нула промени в кода, нула API заявки.

Лиги: само тези с xG >= 70% от мачовете (validation/data_inventory_20260923.csv).

=== МЕТОД ===
1. Мачове: завършени, с xG и за двата отбора (без xG мачът не влиза и в
   средните, и в целта - двата предиктора виждат ЕДНАКВИ мачове).
2. За всеки отбор, хронологично: пълзящи средни за последните k мача
   (k = 5 и 10), само от ПРЕДИШНИ мачове (shift 1) - вкарани голове (GF),
   xG за (XGF), допуснати голове (GA), xG срещу (XGA). Мачът влиза, само ако
   И отборът, И противникът имат по k предишни мача.
3. Прогноза за головете на отбора в този мач:
     голове: (GF_k на отбора + GA_k на противника) / 2
     xG:     (XGF_k на отбора + XGA_k на противника) / 2
   (атака на отбора + защита на противника - най-простата честна
   комбинация; същата формула за двата предиктора).
4. Мерки: средна квадратна грешка (MSE) срещу реалните голове - основна;
   плюс корелация (не зависи от мащаба). Разлика MSE(xG) - MSE(голове),
   95% интервал със сдвоен bootstrap по мач (двата реда на мач заедно),
   2000 повторения, seed 42.
5. Присъда за k=10 (по-стабилната): интервалът изцяло < 0 -> "xG е
   по-добър"; изцяло > 0 -> "xG е по-лош"; съдържа 0 -> "еднакво".

Изход: validation/xg_quality_<ДАТА>.md и .csv
"""
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import football_lib as fl  # noqa: E402

INV = "validation/data_inventory_20260923.csv"
WINDOWS = [5, 10]
THRESH = 70.0


def team_table(df):
    d = df.dropna(subset=["home_goals", "away_goals", "home_xg", "away_xg"])
    h = pd.DataFrame({"fixture_id": d.fixture_id, "date": d.date, "team": d.home_team, "opp": d.away_team,
                      "gf": d.home_goals, "ga": d.away_goals, "xgf": d.home_xg, "xga": d.away_xg})
    a = pd.DataFrame({"fixture_id": d.fixture_id, "date": d.date, "team": d.away_team, "opp": d.home_team,
                      "gf": d.away_goals, "ga": d.home_goals, "xgf": d.away_xg, "xga": d.home_xg})
    t = pd.concat([h, a], ignore_index=True).sort_values(["team", "date", "fixture_id"]).reset_index(drop=True)
    for k in WINDOWS:
        g = t.groupby("team")
        for c in ("gf", "ga", "xgf", "xga"):
            t[f"{c}_{k}"] = g[c].transform(lambda s: s.shift(1).rolling(k, min_periods=k).mean())
    return t


def evaluate(t, k):
    opp = t[["fixture_id", "team", f"ga_{k}", f"xga_{k}"]].rename(
        columns={"team": "opp", f"ga_{k}": "opp_ga", f"xga_{k}": "opp_xga"})
    m = t.merge(opp, on=["fixture_id", "opp"], how="inner")
    m = m.dropna(subset=[f"gf_{k}", f"xgf_{k}", "opp_ga", "opp_xga"])
    m["pred_goals"] = (m[f"gf_{k}"] + m["opp_ga"]) / 2
    m["pred_xg"] = (m[f"xgf_{k}"] + m["opp_xga"]) / 2
    m["se_goals"] = (m["pred_goals"] - m["gf"]) ** 2
    m["se_xg"] = (m["pred_xg"] - m["gf"]) ** 2
    per_fx = m.groupby("fixture_id").agg(d=("se_xg", "sum"), g=("se_goals", "sum"), c=("gf", "size"))
    diff_sum = (per_fx["d"] - per_fx["g"]).to_numpy()
    cnt = per_fx["c"].to_numpy()
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(diff_sum), size=(2000, len(diff_sum)))
    boot = diff_sum[idx].sum(1) / cnt[idx].sum(1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"k": k, "n_rows": len(m), "matches": m["fixture_id"].nunique(),
            "first_date": m["date"].min().date(), "mse_goals": m["se_goals"].mean(), "mse_xg": m["se_xg"].mean(),
            "diff": m["se_xg"].mean() - m["se_goals"].mean(), "ci_low": lo, "ci_high": hi,
            "corr_goals": np.corrcoef(m["pred_goals"], m["gf"])[0, 1],
            "corr_xg": np.corrcoef(m["pred_xg"], m["gf"])[0, 1],
            "mean_goals": m["gf"].mean(), "mean_pred_xg": m["pred_xg"].mean()}


def verdict(r):
    if r["ci_high"] < 0:
        return "xG е по-добър"
    if r["ci_low"] > 0:
        return "xG е по-лош"
    return "еднакво"


def main():
    tag = date.today().strftime("%Y%m%d")
    inv = pd.read_csv(INV)
    leagues = inv[inv.xg_pct >= THRESH].league.tolist()
    rows = []
    for lg in leagues:
        t = team_table(fl.load_league_data(lg))
        for k in WINDOWS:
            r = evaluate(t, k)
            r["league"] = lg
            r["verdict"] = verdict(r)
            rows.append(r)
    out = pd.DataFrame(rows)[["league", "k", "matches", "n_rows", "first_date", "mse_goals", "mse_xg", "diff",
                              "ci_low", "ci_high", "corr_goals", "corr_xg", "mean_goals", "mean_pred_xg", "verdict"]]
    out.round(5).to_csv(f"validation/xg_quality_{tag}.csv", index=False)

    L = [f"# Струва ли нещо xG на API-то - {tag}", "",
         "ZADACHA_MERILO.md, ЧАСТ Б. Скрипт: `validation/xg_quality.py` (методът е в docstring-а),",
         f"сурови числа: `xg_quality_{tag}.csv`. Нула промени в кода.", "",
         "Въпрос: кое предсказва по-добре головете на отбора в СЛЕДВАЩИЯ му мач - средното от последните",
         "k мача на головете (вкарани от отбора + допуснати от противника, /2) или същото, сметнато с xG?",
         "MSE = средна квадратна грешка (по-малко = по-добре). Разлика = MSE(xG) − MSE(голове):",
         "отрицателна = xG е по-точен.", "",
         "| лига | k | мачове | от | MSE голове | MSE xG | разлика (95% инт.) | корел. голове | корел. xG | присъда |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['league']} | {r['k']} | {r['matches']} | {r['first_date']} | {r['mse_goals']:.4f} | "
                 f"{r['mse_xg']:.4f} | {r['diff']:+.4f} [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}] | "
                 f"{r['corr_goals']:.3f} | {r['corr_xg']:.3f} | {r['verdict']} |")
    L += ["", "## Присъда по лига (по k = 10 - по-стабилното средно)", ""]
    for r in rows:
        if r["k"] == 10:
            L.append(f"- **{r['league']}:** {r['verdict']} (разлика {r['diff']:+.4f}, "
                     f"интервал [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}], {r['matches']} мача).")
    with open(f"validation/xg_quality_{tag}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
