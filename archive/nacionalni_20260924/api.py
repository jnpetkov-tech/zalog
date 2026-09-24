import json, os, sys
sys.path.insert(0, "/home/inkas/sportbg-predictor")
os.chdir("/home/inkas/sportbg-predictor")
import api_football as af
CNT = "/tmp/nac/count.txt"
def get(path, params, name):
    fn = f"/tmp/nac/raw_{name}.json"
    if os.path.exists(fn):
        return json.load(open(fn))
    n = int(open(CNT).read()) if os.path.exists(CNT) else 0
    if n >= 50: raise SystemExit("QUOTA 50 REACHED")
    r = af._api_get(path, params=params, timeout=30)
    open(CNT, "w").write(str(n + 1))
    d = r.json()
    json.dump(d, open(fn, "w"))
    print(f"[call {n+1}] {path} {params} results={d.get('results')} errors={d.get('errors')} paging={d.get('paging')}")
    return d
