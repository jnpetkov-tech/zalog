"""ZADACHA_VSICHKO_OT_API етап 4: САМО инвентар - брой мачове по сезон (/fixtures?league&season) за женски и младежки турнири.
Покритието - от /leagues (leagues_inventar_zheni.json / _klubni.json). Без теглене на история (суровите списъци - api_raw/inventar_zheni/)."""
import gzip, json, math, os, sys
from datetime import datetime
ROOT = "/home/inkas/sportbg-predictor"
sys.path.insert(0, ROOT); os.chdir(ROOT)
import backfill_common as bc
IDS = {525: "Шампионска лига жени", 44: "Англия жени (WSL)", 142: "Испания жени (Primera Femenina)", 82: "Германия жени (Frauen-BL)",
       64: "Франция жени (D1)", 139: "Италия жени (Serie A)", 38: "Евро U21", 850: "Евро U21 - квалификации", 493: "Евро U19",
       893: "Евро U19 - квалификации", 921: "Евро U17", 886: "Евро U17 - квалификации"}
inv = {}
for fn in ("leagues_inventar_zheni.json", "leagues_inventar_klubni.json"):
    for r in json.load(open(f"archive/vsichko_ot_api_20261009/{fn}")):
        inv.setdefault(r["id"], r)
f = bc.Fetcher(os.path.join(ROOT, "archive", "vsichko_ot_api_20261009", "zheni_log.txt"))
f.floor = bc.live_reserve()[0]; f.check_quota_now()
os.makedirs("api_raw/inventar_zheni", exist_ok=True)
out = []
for lid, name in IDS.items():
    for season, cov in sorted(inv[lid]["seasons"].items()):
        if not ("2022" <= season <= "2026"):
            continue
        data = f.get("/fixtures", {"league": lid, "season": int(season)})
        with gzip.open(f"api_raw/inventar_zheni/{lid}_{season}.jsonl.gz", "at", encoding="utf-8") as g:
            g.write(json.dumps({"params": {"league": lid, "season": season}, "fetched_at": datetime.utcnow().isoformat(timespec="seconds"), "data": data}) + "\n")
        resp = (data or {}).get("response", [])
        fin = sum(1 for x in resp if x["fixture"]["status"]["short"] in ("FT", "AET", "PEN"))
        out.append({"id": lid, "name": name, "season": season, "matches": len(resp), "finished": fin, **{k: cov.get(k) for k in ("st", "lu", "inj", "odds")}})
        print(out[-1], flush=True)
json.dump(out, open("archive/vsichko_ot_api_20261009/zheni_mladezhi.json", "w"), ensure_ascii=False, indent=0)
print("заявки", f.calls)
