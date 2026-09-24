"""ZADACHA_NACIONALNI2 Б: двата липсващи списъка (мачовете от 2022 в сезоните
"2020" на ЛН и световните квалификации Европа). Останалите сурови списъци са
от сутрешния инвентар (archive/nacionalni_20260924/api.py -> /tmp/nac/)."""
import json, os, sys
sys.path.insert(0, "/home/inkas/sportbg-predictor"); os.chdir("/home/inkas/sportbg-predictor")
import api_football as af
for lid in (5, 32):
    fn = f"/tmp/nac/raw_fx_{lid}_2020.json"
    if os.path.exists(fn):
        continue
    d = af._api_get("/fixtures", params={"league": lid, "season": 2020}, timeout=30).json()
    json.dump(d, open(fn, "w"))
    print(lid, d.get("results"), d.get("errors"))
