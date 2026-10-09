"""ZADACHA_VSICHKO_OT_API етап 3: история 2022-2026 на новите (извън Европа) национални турнири -> nationals_merged_full.csv (само
добавяне, без дубликати - nationals_collect.append_results). Сезоните - от /leagues (leagues_inventar_nacionalni.json). Сурово:
api_raw/nationals_hist/<id>_<сезон>.jsonl.gz. Еднократен."""
import gzip, json, os, sys
from collections import Counter
from datetime import datetime
ROOT = "/home/inkas/sportbg-predictor"
sys.path.insert(0, ROOT); os.chdir(ROOT)
import backfill_common as bc
import nationals_collect as nc

NEW = [34, 29, 30, 31, 9, 6, 36, 22, 7]
inv = {r["id"]: r for r in json.load(open("archive/vsichko_ot_api_20261009/leagues_inventar_nacionalni.json"))}
f = bc.Fetcher(os.path.join(ROOT, "archive", "vsichko_ot_api_20261009", "nationals_history_log.txt"))
f.floor = bc.live_reserve()[0]
f.check_quota_now()
os.makedirs("api_raw/nationals_hist", exist_ok=True)
added, by = 0, Counter()
for lid in NEW:
    for season in sorted(inv[lid]["seasons"], key=int):
        data = f.get("/fixtures", {"league": lid, "season": int(season)})
        with gzip.open(f"api_raw/nationals_hist/{lid}_{season}.jsonl.gz", "at", encoding="utf-8") as g:
            g.write(json.dumps({"params": {"league": lid, "season": season}, "fetched_at": datetime.utcnow().isoformat(timespec="seconds"), "data": data}) + "\n")
        rows = [nc.fixture_row(x) for x in (data or {}).get("response", [])]
        rows = [r for r in rows if r["date"] >= "2022-01-01" and r["status"] in nc.FINISHED and r["home_goals"] not in (None, "")]
        n = nc.append_results(rows)
        added += n
        by[(nc.NATIONAL_LEAGUES[lid], season)] = (len(rows), n)
        print(lid, season, len(rows), "нови", n, flush=True)
print("общо нови:", added, "заявки:", f.calls)
json.dump({f"{k[0]}|{k[1]}": v for k, v in by.items()}, open("archive/vsichko_ot_api_20261009/nationals_history_extra.json", "w"), ensure_ascii=False, indent=0)
