"""features/layer_shadow_budget.py - реален разход на заявки по ден (ZADACHA_SYANKA 2.3): заявките на режима "в сянка" (layer_shadow_log.txt, "заявки в този пуск"),
останалите тегления (backfill в api_daily_usage.csv минус сянката) и живият сайт. Бюджет след 01.11 (7 500/ден): сянка + сайт < ~6 000/ден.
Употреба: venv/bin/python3 features/layer_shadow_budget.py"""
import os, re, sys
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT)
shadow = defaultdict(int)
for line in open("layer_shadow_log.txt", encoding="utf-8"):
    m = re.match(r"(\d{4}-\d\d-\d\d)T\S+ заявки в този пуск: (\d+)", line)
    if m:
        shadow[m.group(1)] += int(m.group(2))
rows = {}
for line in list(open("api_daily_usage.csv"))[1:]:
    d, total, back, live = line.strip().split(",")
    rows[d] = (int(total), int(back), int(live))
print("ден        общо  тегления(вкл. сянка)  от тях сянка  сайт")
for d in sorted(rows)[-10:]:
    t, b, l = rows[d]
    print(f"{d} {t:6d} {b:10d} {shadow.get(d, 0):12d} {l:8d}")
