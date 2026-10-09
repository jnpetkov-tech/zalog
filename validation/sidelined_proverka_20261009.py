"""validation/sidelined_proverka_20261009.py - годни ли са api_sidelined.csv като признак (ZADACHA_VSICHKO_OT_API, етап 1).
1) покритие по месеци срещу контузените по мач ({лига}_injuries.csv); 2) съвпадение на ниво мач: контузените „пропуска мача“ - покрити ли са
от запис извън игра към датата (с края / само start); 3) противоречие: титуляри в мача, отбелязани „извън игра“ към датата.
Изход: validation/sidelined_proverka_20261009.md"""
import glob
import os
import pandas as pd
import numpy as np

ROOT = "/home/inkas/sportbg-predictor"
os.chdir(ROOT)
s = pd.read_csv("api_sidelined.csv").drop_duplicates(["player_id", "type", "start", "end"])
s["s"] = pd.to_datetime(s["start"], errors="coerce")
s["e"] = pd.to_datetime(s["end"], errors="coerce")
inj = pd.concat([pd.read_csv(f) for f in glob.glob("*_injuries.csv") if os.path.getsize(f)])
inj = inj[inj["type"] == "Missing Fixture"].drop_duplicates(["fixture_id", "player_id"])
inj["D"] = pd.to_datetime(inj["fixture_date"].str[:10])
lu = pd.concat([pd.read_csv(f, usecols=["fixture_id", "player_id", "starter"]) for f in glob.glob("*_lineups.csv") if os.path.getsize(f)])
fx = pd.concat([pd.read_csv(f, usecols=["fixture_id", "date_utc"]) for f in glob.glob("*_fixtures.csv") if os.path.getsize(f)]).drop_duplicates("fixture_id")
lu = lu[lu["starter"] == 1].merge(fx, on="fixture_id")
lu["D"] = pd.to_datetime(lu["date_utc"].str[:10])
by_p = {p: g[["s", "e"]].to_numpy() for p, g in s.groupby("player_id")}
known = set(by_p)


def cover(p, D, mode):
    iv = by_p.get(p)
    if iv is None:
        return False
    for st, en in iv:
        if pd.isna(st):
            continue
        if mode == "end" and st <= D and (pd.isna(en) or en >= D):
            return True
        if mode == "start" and D - pd.Timedelta(days=21) <= st <= D:
            return True
    return False


L = ["# Записите „извън игра“ (api_sidelined.csv) — годни ли са като признак — 09.10.2026", "",
     "Скрипт: `validation/sidelined_proverka_20261009.py`.", "", "## 1. Покритие по месеци", "",
     "| месец | записи (по start) | играчи с „пропуска мача“ в контузените по мач |", "|---|---|---|"]
a = s.groupby(s["s"].dt.strftime("%Y-%m")).size()
inj["M"] = inj["D"].dt.strftime("%Y-%m")
b = inj.drop_duplicates(["player_id", "M"]).groupby("M").size()
for m in sorted(set(a.index) | set(b.index)):
    if "2024-08" <= m <= "2026-10":
        L.append(f"| {m} | {int(a.get(m, 0))} | {int(b.get(m, 0))} |")
L += ["", "## 2–3. Съвпадение на ниво мач (сезон 2024/25: 01.08.2024–31.05.2025, само играчи, за които изобщо има записи)", ""]
win = lambda d: d[(d["D"] >= "2024-08-01") & (d["D"] <= "2025-05-31")]
ii = win(inj)
ii = ii[ii["player_id"].isin(known)]
ll = win(lu)
ll = ll[ll["player_id"].isin(known)].sample(n=min(20000, len(ll)), random_state=42) if len(ll) else ll
rows = []
for mode, name in (("end", "start ≤ D и (end ≥ D или празно)"), ("start", "start в [D−21, D]")):
    c1 = np.mean([cover(p, D, mode) for p, D in zip(ii["player_id"], ii["D"])]) if len(ii) else float("nan")
    c2 = np.mean([cover(p, D, mode) for p, D in zip(ll["player_id"], ll["D"])]) if len(ll) else float("nan")
    rows.append((name, c1, c2))
L += [f"- контузени „пропуска мача“ (по мач): {len(ii)}; титуляри (извадка): {len(ll)}", "",
      "| вариант | контузените — покрити | титулярите — отбелязани „извън игра“ (противоречие) |", "|---|---|---|"]
for name, c1, c2 in rows:
    L.append(f"| {name} | {c1:.1%} | {c2:.1%} |")
L += ["", f"Записи без край: {s['e'].isna().mean():.1%}; най-късен start {s['s'].max().date()}, най-късен край {s['e'].max().date()} "
      "(теглено на 01.10.2026)."]
out = "\n".join(L) + "\n"
open("validation/sidelined_proverka_20261009.md", "w", encoding="utf-8").write(out)
print(out)
