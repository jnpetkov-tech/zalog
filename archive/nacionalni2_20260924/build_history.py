"""ZADACHA_NACIONALNI2 Б: история 2022-2026 на националните -> nationals_merged_full.csv
(жив файл, извън git) + копие validation/nacionalni2_istoriya_20260924.csv.

Турнири: 5 (ЛН), 32 (св. квал. Европа), 960 (квал. Евро), 4 (Евро), 1 (Световно)
+ приятелски (10), само сеньорски мачове между два национални отбора:
  - махат се имената с U17-U23 / Olympic;
  - и двата отбора трябва да играят в поне един официален турнир от
    сутрешния инвентар (30 списъка, всички конфедерации) - това маха и
    мачовете срещу клубове.
Само завършени мачове с дата 2022-01-01 .. днес.
"""
import csv, glob, json, re, sys
from collections import Counter
sys.path.insert(0, "/home/inkas/sportbg-predictor")
import nationals_collect as nc

RAW = "/tmp/nac"
OFFICIAL = [f for f in glob.glob(f"{RAW}/raw_fx_*.json") if not f.split("/")[-1].startswith("raw_fx_10_")]
WANTED = {5, 32, 960, 4, 1}
YOUTH = re.compile(r"\bU-?\s?(1[5-9]|2[0-3])\b|Olymp", re.I)

official_ids = set()
for f in OFFICIAL:
    for x in json.load(open(f))["response"]:
        official_ids.add(x["teams"]["home"]["id"]); official_ids.add(x["teams"]["away"]["id"])

rows, dropped = {}, Counter()
for f in sorted(glob.glob(f"{RAW}/raw_fx_*.json")):
    for x in json.load(open(f))["response"]:
        lid = x["league"]["id"]
        if lid not in WANTED and lid != 10:
            continue
        if x["fixture"]["status"]["short"] not in nc.FINISHED:
            continue
        if x["fixture"]["date"] < "2022-01-01":
            continue
        h, a = x["teams"]["home"], x["teams"]["away"]
        if lid == 10:
            if YOUTH.search(h["name"]) or YOUTH.search(a["name"]):
                dropped["приятелски младежки"] += 1; continue
            if h["id"] not in official_ids or a["id"] not in official_ids:
                dropped["приятелски с клуб/неофициален отбор"] += 1; continue
        r = nc.fixture_row(x)
        if r["home_goals"] is None or r["home_goals"] == "":
            dropped["без резултат"] += 1; continue
        rows[r["fixture_id"]] = r

out = sorted(rows.values(), key=lambda r: r["date"])
for path in ("/home/inkas/sportbg-predictor/nationals_merged_full.csv",
             "/home/inkas/sportbg-predictor/validation/nacionalni2_istoriya_20260924.csv"):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=nc.CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in out:
            w.writerow({c: nc._goal(r.get(c)) for c in nc.CSV_COLUMNS})

teams = set()
for r in out: teams.add(r["home_id"]); teams.add(r["away_id"])
by = Counter((r["league_name"], r["date"][:4]) for r in out)
print("мачове:", len(out), "отбори:", len(teams), "махнати:", dict(dropped))
for k in sorted(by): print(k, by[k])
