"""features/layer_train.py - седмично преобучение на слоя за режима "в сянка" (ZADACHA_SYANKA 2.2, 01.10.2026).

1. нов features/core_lam_mu.csv (ядрото walk-forward върху актуалните CSV); 2. нова features/features_table.csv.gz;
3. два модела върху ВСИЧКИ вече изиграни мачове (само минали): AB (преди съставите) и ABC (след съставите) със записаните настройки
   (ABC: features/layer_config.json; AB: най-добрата по ранната половина - sloy_vlizane_20261001.md); 4. запис във layer_model/<версия>/ и
   layer_model/candidate.json. current.json (това, което е на живо) се сменя САМО от features/layer_gate.py след проверка (ZADACHA_PAZACH,
   06.10.2026) - пуска се в същия cron ред веднага след това. Версията = дата + кратък git hash (+ _2, _3..., ако папката вече съществува -
   никога не се презаписва съществуваща версия, напр. текущата при второ обучение в същия ден).
Самостоятелен процес (crontab, flock), без рестарт. Употреба: nice -n 19 venv/bin/python3 features/layer_train.py [--skip-build]
"""
import json
import os
import subprocess
import sys
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import pandas as pd  # noqa: E402

AB_CFG = {"depth": 3, "min_child": 300, "l2": 100, "n_est": 200, "shrink": 1.0, "fset": "AB"}
MODEL_DIR = os.path.join(ROOT, "layer_model")


def git_hash():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def main():
    if "--skip-build" not in sys.argv:
        from features import core_lam_mu, build_features
        sys.argv = [sys.argv[0], "--procs", "6"]
        core_lam_mu.main()
        build_features.main()
    from features import layer_lib as L
    abc = json.load(open(os.path.join(ROOT, "features", "layer_config.json")))
    t = L.load_table()
    long = L.to_long(t)
    base_version = datetime.utcnow().strftime("%Y%m%d") + "_" + git_hash()
    version, k = base_version, 1
    while os.path.exists(os.path.join(MODEL_DIR, version)):
        k += 1
        version = f"{base_version}_{k}"
    out = os.path.join(MODEL_DIR, version)
    os.makedirs(out)
    meta = {"version": version, "trained_at": datetime.utcnow().isoformat(timespec="seconds"), "git": git_hash(),
            "trained_through": str(t["date"].max()), "n_matches": int(len(t)), "league_codes": L.LEAGUE_CODES, "models": {}}
    for name, cfg in (("AB", AB_CFG), ("ABC", {k: abc[k] for k in ("depth", "min_child", "l2", "n_est", "shrink", "fset")})):
        bst = L.fit_final(long, {**cfg, "n_list": [cfg["n_est"]]})
        bst.save_model(os.path.join(out, f"{name}.txt"))
        meta["models"][name] = {k: cfg[k] for k in ("depth", "min_child", "l2", "n_est", "shrink", "fset")}
        print(name, "обучен върху", len(t), "мача")
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    tmp = os.path.join(MODEL_DIR, ".candidate.json.tmp")
    with open(tmp, "w") as f:
        json.dump({"version": version}, f)
    os.replace(tmp, os.path.join(MODEL_DIR, "candidate.json"))
    print("версия", version, "->", out, "(кандидат; current.json сменя само features/layer_gate.py)")


if __name__ == "__main__":
    main()
