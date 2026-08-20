"""
diag_full_review.py - ПЪЛЕН read-only преглед на реалната точност (Opus review, 2026-08-11).

НИЩО не се записва в базата. Само SELECT заявки.

Целта: да отговори на въпроса "къде моделът реално е добър" с числа, РАЗДЕЛЕНИ
по пазар и по лига - защото смесеният win rate (44.4%) няма смисъл: смесва
2-изходни пазари (baseline 50%) с 9-изходни HT/FT (baseline 11%).
"""
import sqlite3
import os
from collections import defaultdict

DB = "predictions.db"

MARKET_GROUPS = [
    ("1X2",        lambda c: c in ("home_win", "draw", "away_win")),
    ("Над/Под 2.5", lambda c: c in ("over25", "under25")),
    ("Тотал дом 1.5", lambda c: c in ("home_over15", "home_under15")),
    ("Тотал гост 1.5", lambda c: c in ("away_over15", "away_under15")),
    ("HT/FT",      lambda c: c.startswith("htft")),
    ("Двоен шанс", lambda c: c.startswith("dc")),
    ("BTTS",       lambda c: c.startswith("btts")),
    ("Ъглови",     lambda c: c.startswith("corners")),
    ("Картони",    lambda c: c.startswith("cards")),
    ("Засади",     lambda c: c.startswith("offsides")),
]

PROVEN_GROUPS = {"1X2", "Над/Под 2.5", "Тотал дом 1.5", "HT/FT"}


def group_of(code):
    if not code:
        return "?"
    for name, test in MARKET_GROUPS:
        if test(code):
            return name
    return "друго"


def hdr(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def pct(n, d):
    return (100.0 * n / d) if d else 0.0


if not os.path.exists(DB):
    raise SystemExit(f"НЯМА {DB} в текущата директория")

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT league, market_code, pick_pct, status, market_odds, our_fair_odds, match_date
    FROM predictions_log
""").fetchall()

WON = {"won", "win", "hit"}
LOST = {"lost", "loss", "miss"}

hdr("Q1. ОБЩО СЪСТОЯНИЕ")
by_status = defaultdict(int)
for r in rows:
    by_status[r["status"]] += 1
print(f"Общо записи: {len(rows)}")
for s, n in sorted(by_status.items(), key=lambda x: -x[1]):
    print(f"  {str(s):12} {n:6}")
dates = [r["match_date"] for r in rows if r["match_date"]]
if dates:
    print(f"Диапазон match_date: {min(dates)}  ->  {max(dates)}")

hdr("Q2. WIN RATE ПО ГРУПА ПАЗАРИ (само приключили) - КЛЮЧОВАТА ТАБЛИЦА")
agg = defaultdict(lambda: {"n": 0, "won": 0, "promised": 0.0})
for r in rows:
    if r["status"] not in WON and r["status"] not in LOST:
        continue
    g = group_of(r["market_code"])
    a = agg[g]
    a["n"] += 1
    a["promised"] += (r["pick_pct"] or 0)
    if r["status"] in WON:
        a["won"] += 1
print(f"{'Група':18} {'n':>6} {'обещано':>9} {'реално':>9} {'разлика':>9}  статус")
for g, a in sorted(agg.items(), key=lambda x: -x[1]["n"]):
    if not a["n"]:
        continue
    prom = a["promised"] / a["n"]
    real = pct(a["won"], a["n"])
    tag = "ДОКАЗАН" if g in PROVEN_GROUPS else ""
    print(f"{g:18} {a['n']:6} {prom:8.1f}% {real:8.1f}% {real-prom:+8.1f}pp  {tag}")

hdr("Q3. САМО 1X2, ПО ЛИГА (сърцевината на продукта)")
agg3 = defaultdict(lambda: {"n": 0, "won": 0, "promised": 0.0})
for r in rows:
    if group_of(r["market_code"]) != "1X2":
        continue
    if r["status"] not in WON and r["status"] not in LOST:
        continue
    a = agg3[r["league"]]
    a["n"] += 1
    a["promised"] += (r["pick_pct"] or 0)
    if r["status"] in WON:
        a["won"] += 1
print(f"{'Лига':22} {'n':>6} {'обещано':>9} {'реално':>9} {'разлика':>9}")
for lg, a in sorted(agg3.items(), key=lambda x: -x[1]["n"]):
    if not a["n"]:
        continue
    prom = a["promised"] / a["n"]
    real = pct(a["won"], a["n"])
    print(f"{str(lg):22} {a['n']:6} {prom:8.1f}% {real:8.1f}% {real-prom:+8.1f}pp")

hdr("Q4. КАЛИБРАЦИЯ - САМО ДОКАЗАНИТЕ ПАЗАРИ")
bands = [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]


def calib(filter_fn, label):
    print(f"--- {label} ---")
    print(f"{'банд':>10} {'n':>6} {'обещано':>9} {'реално':>9} {'разлика':>9}")
    for lo, hi in bands:
        n = w = 0
        prom = 0.0
        for r in rows:
            if r["status"] not in WON and r["status"] not in LOST:
                continue
            if not filter_fn(r):
                continue
            p = r["pick_pct"] or 0
            if not (lo <= p < hi):
                continue
            n += 1
            prom += p
            if r["status"] in WON:
                w += 1
        if n:
            print(f"{lo:4}-{hi:<4} {n:6} {prom/n:8.1f}% {pct(w,n):8.1f}% {pct(w,n)-prom/n:+8.1f}pp")
    print()


calib(lambda r: group_of(r["market_code"]) in PROVEN_GROUPS, "ДОКАЗАНИ пазари")
calib(lambda r: group_of(r["market_code"]) not in PROVEN_GROUPS, "НЕдоказани пазари (за контраст)")

hdr("Q5. РАВЕНСТВАТА - известно слабо място на всички Poisson модели")
n_draw_pred = sum(1 for r in rows if r["market_code"] == "draw"
                  and (r["status"] in WON or r["status"] in LOST))
w_draw = sum(1 for r in rows if r["market_code"] == "draw" and r["status"] in WON)
prom_draw = sum(r["pick_pct"] or 0 for r in rows if r["market_code"] == "draw"
                and (r["status"] in WON or r["status"] in LOST))
print(f"Прогнози 'Равен' (приключили): {n_draw_pred}")
if n_draw_pred:
    print(f"  обещано средно: {prom_draw/n_draw_pred:.1f}%   реално: {pct(w_draw,n_draw_pred):.1f}%")
print("\nБрой записи по 1X2 изход:")
for code in ("home_win", "draw", "away_win"):
    n = sum(1 for r in rows if r["market_code"] == code)
    print(f"  {code:10} {n:6}")

hdr("Q6. ROI ТАМ, КЪДЕТО ИМА РЕАЛЕН КОЕФИЦИЕНТ (по група пазари)")
roi = defaultdict(lambda: {"n": 0, "stake": 0.0, "ret": 0.0, "won": 0})
for r in rows:
    if r["market_odds"] is None:
        continue
    if r["status"] not in WON and r["status"] not in LOST:
        continue
    g = group_of(r["market_code"])
    a = roi[g]
    a["n"] += 1
    a["stake"] += 1.0
    if r["status"] in WON:
        a["ret"] += r["market_odds"]
        a["won"] += 1
print(f"{'Група':18} {'n':>6} {'win%':>8} {'ROI':>9}")
tot_s = tot_r = 0.0
for g, a in sorted(roi.items(), key=lambda x: -x[1]["n"]):
    prof = a["ret"] - a["stake"]
    tot_s += a["stake"]
    tot_r += a["ret"]
    print(f"{g:18} {a['n']:6} {pct(a['won'],a['n']):7.1f}% {pct(prof,a['stake']):+8.1f}%")
if tot_s:
    print(f"{'ОБЩО':18} {int(tot_s):6} {'':8} {pct(tot_r-tot_s,tot_s):+8.1f}%")

hdr("Q7. ПОКРИТИЕ С РЕАЛНИ КОЕФИЦИЕНТИ (след Фаза F0)")
tot = len(rows)
with_odds = sum(1 for r in rows if r["market_odds"] is not None)
print(f"Записи с market_odds: {with_odds} / {tot} = {pct(with_odds,tot):.1f}%")
print("\nПо група пазари:")
cov = defaultdict(lambda: [0, 0])
for r in rows:
    g = group_of(r["market_code"])
    cov[g][0] += 1
    if r["market_odds"] is not None:
        cov[g][1] += 1
for g, (t, w) in sorted(cov.items(), key=lambda x: -x[1][0]):
    print(f"  {g:18} {w:5}/{t:<6} {pct(w,t):5.1f}%")

hdr("Q8. КОИ ПАЗАРИ СТАВАТ 'ТОП ПРОГНОЗА' (най-често най-висок процент)")
best = defaultdict(int)
byfix = defaultdict(list)
for r in rows:
    byfix[(r["league"], r["match_date"])].append(r)
for k, rs in byfix.items():
    top = max(rs, key=lambda r: (r["pick_pct"] or 0))
    best[top["market_code"]] += 1
print("Ако един пазар доминира - моделът е изроден, показва все едно и също:\n")
for code, n in sorted(best.items(), key=lambda x: -x[1])[:15]:
    print(f"  {str(code):32} {n:6}")

hdr("Q9. РАЗПРЕДЕЛЕНИЕ НА pick_pct")
dist = defaultdict(int)
for r in rows:
    p = r["pick_pct"] or 0
    dist[int(p // 10) * 10] += 1
mx = max(dist.values()) if dist else 1
for b in sorted(dist):
    bar = "#" * int(60 * dist[b] / mx)
    print(f"  {b:3}-{b+9:<3} {dist[b]:6}  {bar}")
n100 = sum(1 for r in rows if (r["pick_pct"] or 0) >= 99.5)
print(f"\nПрогнози с >= 99.5% (математически невъзможни): {n100}")

conn.close()
print("\nГОТОВО - нищо не е променяно в базата.")
