"""Основание за вътрешния предпазител (ZADACHA_TABLICA ст.5а): за уверените прогнози (p >= 0.65) на мерилото (11 823 мача,
validation/final_v_20260924_matches.csv - калибрираните вероятности) - обещано срещу реално по групи: малко история (К<10) / екстремно ядро (X)
срещу останалите. Ако предпазителят е оправдан, флагнатите групи трябва да са по-лошо калибрирани (обещаното надхвърля реалното).
Изход: validation/pazar_vun_osnovanie_20261001.md/.csv."""
import os, sys, bisect
from collections import defaultdict
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "validation"))
import pazar_vun_20261001 as pv
n_prior = pv.load_fixture_info()
m = pd.read_csv("validation/final_v_20260924_matches.csv")
m["nmin"] = m["fixture_id"].map(n_prior)
m["extreme"] = ~m["lam"].between(0.35, 3.2) | ~m["mu"].between(0.35, 3.2)
codes = ["home_win", "draw", "away_win", "over25", "under25", "btts_yes", "btts_no", "home_over15", "home_under15", "away_over15", "away_under15"]
rows = []
for c in codes:
    d = m[[f"p_{c}", f"y_{c}", "nmin", "extreme", "fixture_id", "league"]].rename(columns={f"p_{c}": "p", f"y_{c}": "y"}); d["code"] = c
    rows.append(d)
L = pd.concat(rows)
L = L[L["p"] >= 0.65]
def summ(mask, name):
    s = L[mask]
    se = np.sqrt((s["p"] * (1 - s["p"])).sum()) / len(s) if len(s) else np.nan
    return {"група": name, "прогнози (>=65%)": len(s), "мача": s["fixture_id"].nunique(), "обещано": s["p"].mean(), "реално": s["y"].mean(),
            "разлика (реално-обещано)": s["y"].mean() - s["p"].mean(), "шум (1 sd)": se}
out = [summ(L["nmin"].notna(), "всички (с известна история)"), summ(L["nmin"] >= 10, "К >= 10"), summ(L["nmin"] < 10, "К < 10"), summ(L["nmin"] < 6, "К < 6"),
       summ(L["nmin"] >= 15, "К >= 15"), summ(L["nmin"] < 15, "К < 15"), summ(L["extreme"], "екстремно ядро (X)"), summ(~L["extreme"], "без екстремно ядро")]
df = pd.DataFrame(out); df.round(4).to_csv("validation/pazar_vun_osnovanie_20261001.csv", index=False)
T = ["# Основание за вътрешния предпазител — 01.10.2026", "", "Мерило `final_v_20260924_matches.csv` (11 823 мача; показваните, калибрирани вероятности). Само уверени прогнози (p ≥ 0.65). "
     "Ако предпазителят е оправдан, флагнатите групи имат реално под обещаното (по-лошо калибрирани). Шумът е 1 стандартно отклонение на сбора на Бернули.", "",
     "| група | прогнози | мача | обещано | реално | реално − обещано | шум (1 sd) |", "|---|---|---|---|---|---|---|"]
for r in df.itertuples():
    T.append(f"| {r.група} | {r._2} | {r.мача} | {r.обещано:.3f} | {r.реално:.3f} | {r._6:+.3f} | {r._7:.3f} |")
open("validation/pazar_vun_osnovanie_20261001.md", "w", encoding="utf-8").write("\n".join(T) + "\n")
print("\n".join(T))
