"""Етап 2/3/4 (ZADACHA_VSICHKO_OT_API): /leagues по държава/търсене -> суровото в api_raw/leagues/, кратка таблица в stdout (json).
Еднократен. Заявките - през backfill_common.Fetcher."""
import json, os, sys, gzip
from datetime import datetime
ROOT = "/home/inkas/sportbg-predictor"
sys.path.insert(0, ROOT); os.chdir(ROOT)
import backfill_common as bc

f = bc.Fetcher(os.path.join(ROOT, "archive", "vsichko_ot_api_20261009", "leagues_log.txt"))
f.floor = 1000
f.check_quota_now()
queries = [("country", c) for c in sys.argv[1].split(",")] if len(sys.argv) > 1 else []
queries += [("search", s) for s in (sys.argv[2].split(",") if len(sys.argv) > 2 else [])]
out = []
for kind, q in queries:
    data = f.get("/leagues", {kind: q})
    with gzip.open(os.path.join(ROOT, "api_raw", "leagues", f"inventar_20261009.jsonl.gz"), "at", encoding="utf-8") as g:
        g.write(json.dumps({"params": {kind: q}, "fetched_at": datetime.utcnow().isoformat(timespec="seconds"), "data": data}, ensure_ascii=False) + "\n")
    for r in (data or {}).get("response", []):
        cov = {s["year"]: s.get("coverage", {}) for s in r.get("seasons", [])}
        out.append({"q": q, "id": r["league"]["id"], "name": r["league"]["name"], "type": r["league"]["type"],
                    "country": r["country"]["name"],
                    "seasons": {y: {"st": c.get("fixtures", {}).get("statistics_fixtures"), "lu": c.get("fixtures", {}).get("lineups"),
                                    "pl": c.get("fixtures", {}).get("statistics_players"), "inj": c.get("injuries"), "odds": c.get("odds"),
                                    "pred": c.get("predictions")} for y, c in cov.items() if y >= 2021}})
json.dump(out, open(os.path.join(ROOT, "archive", "vsichko_ot_api_20261009", "leagues_inventar.json"), "w"), ensure_ascii=False, indent=0)
print(f"{len(out)} лиги/турнира, заявки {f.calls}")
