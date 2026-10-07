"""features/layer_train.py - седмично преобучение на слоя за режима "в сянка" (ZADACHA_SYANKA 2.2, 01.10.2026).

1. нов features/core_lam_mu.csv (ядрото walk-forward върху актуалните CSV); 2. нова features/features_table.csv.gz;
3. два модела върху ВСИЧКИ вече изиграни мачове (само минали): AB (преди съставите) и ABC (след съставите) със записаните настройки
   (ABC: features/layer_config.json; AB: най-добрата по ранната половина - sloy_vlizane_20261001.md); 4. запис във layer_model/<версия>/ и
   layer_model/candidate.json. current.json (това, което е на живо) се сменя САМО от features/layer_gate.py след проверка (ZADACHA_PAZACH,
   06.10.2026) - пуска се в същия cron ред веднага след това. Версията = дата + кратък git hash (+ _2, _3..., ако папката вече съществува -
   никога не се презаписва съществуваща версия, напр. текущата при второ обучение в същия ден).

ЧЕСТНА ПРОВЕРКА (ZADACHA_MODELI, ЧАСТ 1, 07.10.2026). Окончателните модели са видели всичко, затова в същото пускане се обучават и
ПРОВЕРОЧНИ модели без мачовете от последните HOLDOUT_WEEKS седмици (дата >= holdout_from = последният изигран − 4 седмици + 1 ден):
 - AB_holdout.txt / ABC_holdout.txt     - рецептата на кандидата (същите настройки), само мачове с дата < holdout_from;
 - AB_holdout_cur.txt / ABC_holdout_cur.txt - рецептата на ТЕКУЩАТА версия (настройките от нейния meta.json), същите данни.
Пазачът сравнява двете проверочни двойки върху 4-те седмици - нито една не ги е виждала. В meta.json: holdout_from, holdout{...}.
Ако рецептите съвпадат, двете проверочни двойки са еднакви (същите данни, детерминистично обучение) - проверката (б)/(в) тогава
показва 0 разлика и пазачът го пише; честното сравнение срещу ядрото без слой (само за сведение) остава.
Без текуща версия (първо обучение) - само AB_holdout/ABC_holdout.

Самостоятелен процес (crontab, flock), без рестарт.
Употреба: nice -n 19 venv/bin/python3 features/layer_train.py [--skip-build] [--model-dir DIR]   (--model-dir - само за тестове върху копие)
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
HOLDOUT_WEEKS = 4
CFG_KEYS = ("depth", "min_child", "l2", "n_est", "shrink", "fset")


def git_hash():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def holdout_from(t):
    """Първата дата на проверочния прозорец: последният изигран мач − HOLDOUT_WEEKS седмици + 1 ден (прозорецът = последните 28 дни)."""
    played = t[t["hg"].notna() & t["ag"].notna()]
    return (played["d"].max() - pd.Timedelta(weeks=HOLDOUT_WEEKS) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def recipes():
    abc = json.load(open(os.path.join(ROOT, "features", "layer_config.json")))
    return {"AB": dict(AB_CFG), "ABC": {k: abc[k] for k in CFG_KEYS}}


def current_recipe(model_dir):
    """Настройките на текущата версия (current.json -> meta.json) или None."""
    from features import layer_gate as G
    try:
        cur = G.current_version(model_dir)
        meta = json.load(open(os.path.join(model_dir, cur, "meta.json")))
        return cur, {m: {k: meta["models"][m][k] for k in CFG_KEYS} for m in ("AB", "ABC")}
    except Exception:
        return None, None


def train(t, long, model_dir=MODEL_DIR, cand_long=None):
    """Обучава окончателните + проверочните модели и пише папката на версията + candidate.json. cand_long (само за тестове) - данни за
    моделите на КАНДИДАТА (окончателни и проверочни); проверочните на текущата рецепта винаги са от long. Връща версията."""
    from features import layer_lib as L
    cand_long = long if cand_long is None else cand_long
    base_version = datetime.utcnow().strftime("%Y%m%d") + "_" + git_hash()
    version, k = base_version, 1
    while os.path.exists(os.path.join(model_dir, version)):
        k += 1
        version = f"{base_version}_{k}"
    out = os.path.join(model_dir, version)
    hf = holdout_from(t)
    cur_v, cur_rec = current_recipe(model_dir)
    rec = recipes()
    os.makedirs(out)
    tr_mask = (long["d"] < pd.Timestamp(hf)).to_numpy()
    meta = {"version": version, "trained_at": datetime.utcnow().isoformat(timespec="seconds"), "git": git_hash(),
            "trained_through": str(t["date"].max()), "n_matches": int(len(t)), "league_codes": L.LEAGUE_CODES, "models": {},
            "holdout_from": hf,
            "holdout": {"weeks": HOLDOUT_WEEKS, "n_train_matches": int((t["d"] < pd.Timestamp(hf)).sum()),
                        "n_holdout_matches": int((t["d"] >= pd.Timestamp(hf)).sum()),
                        "current_version": cur_v, "current_recipe": cur_rec,
                        "same_recipe": bool(cur_rec is not None and all(cur_rec[m] == rec[m] for m in rec))}}
    for name, cfg in rec.items():
        bst = L.fit_final(cand_long, {**cfg, "n_list": [cfg["n_est"]]})
        bst.save_model(os.path.join(out, f"{name}.txt"))
        meta["models"][name] = {k: cfg[k] for k in CFG_KEYS}
        print(name, "обучен върху", len(t), "мача")
        bst = L.fit_final(cand_long[tr_mask], {**cfg, "n_list": [cfg["n_est"]]})
        bst.save_model(os.path.join(out, f"{name}_holdout.txt"))
        print(name, f"проверочен (кандидат) - без мачовете от {hf} нататък")
        if cur_rec is not None:
            c = cur_rec[name]
            bst = L.fit_final(long[tr_mask], {**c, "n_list": [c["n_est"]]})
            bst.save_model(os.path.join(out, f"{name}_holdout_cur.txt"))
            print(name, f"проверочен (рецептата на текущата {cur_v}) - без мачовете от {hf} нататък")
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    tmp = os.path.join(model_dir, ".candidate.json.tmp")
    with open(tmp, "w") as f:
        json.dump({"version": version}, f)
    os.replace(tmp, os.path.join(model_dir, "candidate.json"))
    print("версия", version, "->", out, "(кандидат; current.json сменя само features/layer_gate.py)")
    return version


def main():
    model_dir = sys.argv[sys.argv.index("--model-dir") + 1] if "--model-dir" in sys.argv else MODEL_DIR
    if "--skip-build" not in sys.argv:
        from features import core_lam_mu, build_features
        sys.argv = [sys.argv[0], "--procs", "6"]
        core_lam_mu.main()
        build_features.main()
    from features import layer_lib as L
    t = L.load_table()
    long = L.to_long(t)
    train(t, long, model_dir)


if __name__ == "__main__":
    main()
