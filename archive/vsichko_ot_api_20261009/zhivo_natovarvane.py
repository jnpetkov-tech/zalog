"""ZADACHA_VSICHKO_OT_API етап 5: колко мача са в ход едновременно (днешното разписание, /fixtures?date, 1 заявка -> api_raw/zhivo_proba/)."""
import gzip, json, os, sys
from datetime import datetime
ROOT = "/home/inkas/sportbg-predictor"
sys.path.insert(0, ROOT); os.chdir(ROOT)
import backfill_common as bc
import fetch_api_sets as fas
OUR = set(fas.LEAGUE_IDS.values())
f = bc.Fetcher(os.path.join(ROOT, "archive", "vsichko_ot_api_20261009", "zhivo_log.txt")); f.floor = 1000; f.check_quota_now()
day = sys.argv[1] if len(sys.argv) > 1 else datetime.utcnow().strftime("%Y-%m-%d")
d = f.get("/fixtures", {"date": day, "timezone": "UTC"})
with gzip.open(f"api_raw/zhivo_proba/fixtures_date_{day}.json.gz", "wt", encoding="utf-8") as g:
    json.dump({"params": {"date": day}, "fetched_at": datetime.utcnow().isoformat(timespec="seconds"), "data": d}, g)
ks = [(x["fixture"]["timestamp"], x["league"]["id"] in OUR) for x in d["response"] if x["fixture"]["status"]["short"] not in ("PST", "CANC", "ABD")]
t0 = min(k for k, _ in ks) // 60 * 60
res = {"all": 0, "our": 0, "min_all": 0, "min_our": 0}
peak_all = peak_our = 0
for m in range(0, 26 * 60):
    t = t0 + m * 60
    a = sum(1 for k, _ in ks if k <= t < k + 115 * 60)
    o = sum(1 for k, our in ks if our and k <= t < k + 115 * 60)
    peak_all, peak_our = max(peak_all, a), max(peak_our, o)
    res["min_all"] += a > 0
    res["min_our"] += o > 0
print(json.dumps({"day": day, "matches": len(ks), "ours": sum(1 for _, o in ks if o), "peak_all": peak_all, "peak_our": peak_our,
                  "minutes_with_live_all": res["min_all"], "minutes_with_live_our": res["min_our"]}, ensure_ascii=False))
