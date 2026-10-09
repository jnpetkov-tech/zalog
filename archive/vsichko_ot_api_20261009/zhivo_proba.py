"""ZADACHA_VSICHKO_OT_API етап 5: една проба /fixtures?live=all и /odds/live -> api_raw/zhivo_proba/ + структура на отговора (stdout)."""
import gzip, json, os, sys
from datetime import datetime
ROOT = "/home/inkas/sportbg-predictor"
sys.path.insert(0, ROOT); os.chdir(ROOT)
import backfill_common as bc
f = bc.Fetcher(os.path.join(ROOT, "archive", "vsichko_ot_api_20261009", "zhivo_log.txt"))
f.floor = 1000; f.check_quota_now()
os.makedirs("api_raw/zhivo_proba", exist_ok=True)

def shape(x, depth=0, maxd=4):
    if depth > maxd: return "…"
    if isinstance(x, dict): return {k: shape(v, depth + 1) for k, v in list(x.items())[:25]}
    if isinstance(x, list): return [shape(x[0], depth + 1)] if x else []
    return type(x).__name__

for path, params in (("/fixtures", {"live": "all"}), ("/odds/live", {})):
    data = f.get(path, params)
    stamp = datetime.utcnow().isoformat(timespec="seconds")
    with gzip.open(f"api_raw/zhivo_proba/{path.strip('/').replace('/', '_')}_{stamp[:16].replace(':', '')}.json.gz", "wt", encoding="utf-8") as g:
        json.dump({"params": params, "fetched_at": stamp, "data": data}, g)
    resp = (data or {}).get("response", [])
    print(f"== {path} {params}: {len(resp)} записа ({stamp})")
    if resp:
        print(json.dumps(shape(resp[0]), ensure_ascii=False, indent=1)[:4000])
        if path == "/fixtures":
            print("лиги:", sorted({(r['league']['id'], r['league']['name']) for r in resp})[:40])
            print("има събития:", sum(1 for r in resp if r.get("events")), "статистика:", sum(1 for r in resp if r.get("statistics")))
        else:
            print("пазари в първия:", [b.get("name") for b in resp[0].get("odds", [])][:30])
print("заявки", f.calls)
