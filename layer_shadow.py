"""layer_shadow.py - режим "в сянка" на обучения слой (ZADACHA_SYANKA, част 2, 01.10.2026). НИЩО публично.

За предстоящите мачове на 17-те лиги смята очакваните голове на ядрото (живите модели) и след слоя (features/layer_model/*), с вероятностите по
пазари, и ги ЗАПИСВА в append-only таблицата layer_shadow (predictions.db). Не променя нищо показвано: не пише в predictions_log/predictions_snapshot,
не вика /prognozi. Самостоятелен процес (crontab на всеки 15 мин, flock), без рестарт. Рядка работа - при празен график излиза веднага.

Режими:
  pre   - веднъж на ден (след 07:00 UTC, когато нощното опресняване е минало), за мачове в следващите PRE_HORIZON_H часа; набор признаци AB
          (всичко известно дни преди мача);
  final - за мачове, започващи след FINAL_MIN..FINAL_MAX минути, веднага щом излязат съставите (нужна е 1 заявка /fixtures/lineups, повторена
          на всеки 15 мин до FINAL_MIN минути преди началото) + контузени по мача (/injuries?fixture=); набор ABC.
Признаците - със СЪЩИЯ код като таблицата (features/build_features.build върху актуалните CSV); ядрото - match_predictor_app.get_models/get_ft_lambdas
(същата функция като на сайта; внася се лениво, само когато има работа - по образец на build_predictions_snapshot.py).
Данни: дневно опресняване на {лига}_fixtures.csv за текущия сезон (17 заявки) - резултати/статуси/съдия; нови изиграни мачове (състави, статистика, събития)
идват от fetch_api_sets.py/fetch_fixture_events.py (ids= батчове) по cron.
Заявките минават през backfill_common.Fetcher (резерв за сайта, спиране при 429), броят се в layer_shadow_log.txt.

Употреба: venv/bin/python3 layer_shadow.py [--dry-run] [--now 2026-10-02T09:00] [--force-pre]
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import backfill_common as bc  # noqa: E402

LOG_PATH = os.path.join(ROOT, "layer_shadow_log.txt")
STATE_PATH = os.path.join(ROOT, "layer_shadow_state.json")
DB_PATH = os.path.join(ROOT, "predictions.db")
MODEL_DIR = os.path.join(ROOT, "layer_model")
PRE_HOUR_UTC = 7
PRE_HORIZON_H = 72
FINAL_MIN, FINAL_MAX = 15, 100          # минути до началото
SEASON = 2026
LEAGUE_IDS = {"bulgaria": 172, "england": 39, "germany": 78, "spain": 140, "france": 61, "champions_league": 2, "europa_league": 3,
              "conference_league": 848, "italy": 135, "portugal": 94, "france2": 62, "spain2": 141, "italy2": 136, "portugal2": 95,
              "bulgaria2": 173, "england2": 40, "germany2": 79}

DDL = """
CREATE TABLE IF NOT EXISTS layer_shadow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id INTEGER NOT NULL,
    league TEXT NOT NULL,
    match_date TEXT,            -- начало на мача, UTC 'YYYY-MM-DD HH:MM'
    kickoff_ts INTEGER,
    computed_at TEXT NOT NULL,  -- UTC ISO
    mode TEXT NOT NULL,         -- 'pre' | 'final'
    feature_set TEXT,           -- 'AB' | 'ABC'
    lam_core REAL, mu_core REAL, rho REAL,
    lam_layer REAL, mu_layer REAL,
    probs_core TEXT,            -- JSON {код: вероятност 0-1}, суров модел (без калибрация), 11 изхода на мерилото
    probs_layer TEXT,
    layer_version TEXT,
    core_version TEXT           -- git hash на кода в момента на смятане
)"""
IDX = ["CREATE INDEX IF NOT EXISTS idx_layer_shadow_fx ON layer_shadow(fixture_id, mode)",
       "CREATE INDEX IF NOT EXISTS idx_layer_shadow_date ON layer_shadow(match_date)"]


def now_utc(args):
    return datetime.fromisoformat(args["now"]) if args.get("now") else datetime.utcnow()


def log(msg):
    line = f"{datetime.utcnow().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(DDL)
    for q in IDX:
        con.execute(q)
    con.commit()
    return con


def load_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {}


def save_state(st):
    tmp = STATE_PATH + ".tmp"
    json.dump(st, open(tmp, "w"))
    os.replace(tmp, STATE_PATH)


def git_hash():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def load_fixtures():
    parts = []
    for lg in LEAGUE_IDS:
        p = os.path.join(ROOT, f"{lg}_fixtures.csv")
        if os.path.exists(p) and os.path.getsize(p):
            parts.append(pd.read_csv(p, low_memory=False))
    fx = pd.concat(parts, ignore_index=True).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["timestamp"].notna()].copy()
    fx["ts"] = fx["timestamp"].astype("int64")
    return fx


def upcoming(fx, now, hours_min, hours_max):
    t0 = int((now - datetime(1970, 1, 1)).total_seconds())
    m = (fx["ts"] >= t0 + int(hours_min * 3600)) & (fx["ts"] <= t0 + int(hours_max * 3600)) & (~fx["status"].isin(["FT", "AET", "PEN", "PST", "CANC", "ABD", "AWD", "WO"]))
    return fx[m].sort_values("ts")


def make_fetcher():
    f = bc.Fetcher(LOG_PATH)
    try:
        f.floor, _, _ = bc.live_reserve()
    except Exception:
        f.floor = bc.RESERVE_MAX
    f.check_quota_now()
    return f


def refresh_fixtures(fetcher, fas):
    """17 заявки: /fixtures?league&season=SEASON -> {лига}_fixtures.csv (нов снимков ред на мач; load_raw взема последния)."""
    n = 0
    for lg, lid in LEAGUE_IDS.items():
        params = {"league": lid, "season": SEASON}
        data = fetcher.get("/fixtures", params)
        if data is None:
            continue
        ts = datetime.utcnow().isoformat(timespec="seconds")
        fas.raw_append("fixtures", f"{lg}_{SEASON}", params, data)
        fas.write_rows(fas.csv_path("fixtures", lg), fas.rows_fixtures({"league": lg}, data), ts)
        n += 1
    return n


def fetch_lineups_and_injuries(fetcher, fas, fx_rows):
    """За мачове в прозореца: състави (1 заявка) и контузени по мача (1 заявка). Връща множеството мачове със състави."""
    have = set()
    for r in fx_rows.itertuples():
        lg = r.league
        path = fas.csv_path("lineups", lg)
        if str(r.fixture_id) in fas.fixtures_in(path):
            have.add(int(r.fixture_id))
            continue
        params = {"fixture": int(r.fixture_id)}
        data = fetcher.get("/fixtures/lineups", params)
        if data is None or not data.get("response"):
            continue                                   # още няма състави - пак след 15 мин
        ts = datetime.utcnow().isoformat(timespec="seconds")
        fas.raw_append("lineups_live", f"{lg}_{SEASON}", params, data)
        rows = fas.rows_lineups({"fixture": int(r.fixture_id)}, data)
        if sum(1 for x in rows if x["starter"] == "1" or x["starter"] == 1) < 18:
            continue                                   # непълен състав
        fas.write_rows(path, rows, ts, dedupe_by_fixture=True)
        inj = fetcher.get("/injuries", {"fixture": int(r.fixture_id)})
        if inj is not None:
            fas.raw_append("injuries_live", f"{lg}_{SEASON}", {"fixture": int(r.fixture_id)}, inj)
            fas.write_rows(fas.csv_path("injuries", lg), fas.rows_injuries({"league": lg}, inj), ts, dedupe_by_fixture=True)
        have.add(int(r.fixture_id))
    return have


def core_lambdas(fx_rows):
    """lam, mu, rho на живия модел за всеки мач (match_predictor_app.get_models/get_ft_lambdas - СЪЩАТА функция като на сайта).
    Контузиите - само от кеша на сайта (st.get_cached_injuries); липсва -> 0, както би дал сайтът без данни."""
    import match_predictor_app as mpa
    import system_tracker as st
    out = []
    for r in fx_rows.itertuples():
        try:
            (teams, team_idx, ft_model, *_rest) = mpa.get_models(r.league)
            if r.home not in team_idx or r.away not in team_idx:
                continue
            hi = ai = 0
            if _rest[-1]:                                  # has_injuries
                c = st.get_cached_injuries(int(r.fixture_id))
                if c is not None:
                    hi, ai, _ok = c
            lam, mu = mpa.get_ft_lambdas(ft_model, team_idx, r.home, r.away, hi, ai)
            if lam is None:
                continue
            out.append({"fixture_id": int(r.fixture_id), "league": r.league, "date": str(r.date_utc)[:10], "hg": np.nan, "ag": np.nan,
                        "lam": float(lam), "mu": float(mu), "rho": float(ft_model.get("rho", 0.0))})
        except Exception as e:
            log(f"  ядро {r.league} {r.fixture_id}: {e}")
    return pd.DataFrame(out)


def load_models():
    import lightgbm as lgb
    cur = json.load(open(os.path.join(MODEL_DIR, "current.json")))["version"]
    meta = json.load(open(os.path.join(MODEL_DIR, cur, "meta.json")))
    boosters = {k: lgb.Booster(model_file=os.path.join(MODEL_DIR, cur, f"{k}.txt")) for k in meta["models"]}
    return cur, meta, boosters


def predict_rows(core, fset, version, meta, boosters, raw, mode, dry):
    """core: DataFrame ядро; -> редове за layer_shadow."""
    from features import build_features as bf
    from features import layer_lib as L
    tab = bf.build(core, raw)
    if not len(tab):
        return []
    tab["d"] = pd.to_datetime(tab["date"])
    tab["week"] = tab["d"] - pd.to_timedelta(tab["d"].dt.weekday, unit="D")
    tab["league_code"] = tab["league"].map(L.LEAGUE_CODES).astype(float)
    tab["hg"] = np.nan
    tab["ag"] = np.nan
    cfg = meta["models"][fset]
    lam1, mu1 = L.predict_corrected(boosters[fset], fset, tab, cfg["shrink"])
    P0 = L.probs(tab["lam"], tab["mu"], tab["rho"])
    P1 = L.probs(lam1, mu1, tab["rho"])
    fxm = raw["fx"].set_index("fixture_id")
    now = datetime.utcnow().isoformat(timespec="seconds")
    rows = []
    for i, r in enumerate(tab.itertuples()):
        ts = int(fxm.loc[r.fixture_id, "ts"])
        rows.append((int(r.fixture_id), r.league, datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M"), ts, now, mode, fset,
                     float(r.lam), float(r.mu), float(r.rho), float(lam1[i]), float(mu1[i]),
                     json.dumps({c: round(float(P0.iloc[i][c]), 6) for c in L.CODES}), json.dumps({c: round(float(P1.iloc[i][c]), 6) for c in L.CODES}),
                     version, git_hash()))
    return rows


def insert(con, rows):
    con.executemany("INSERT INTO layer_shadow (fixture_id, league, match_date, kickoff_ts, computed_at, mode, feature_set, lam_core, mu_core, rho, "
                    "lam_layer, mu_layer, probs_core, probs_layer, layer_version, core_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()


def main():
    args = {"dry": "--dry-run" in sys.argv, "force_pre": "--force-pre" in sys.argv}
    if "--now" in sys.argv:
        args["now"] = sys.argv[sys.argv.index("--now") + 1]
    now = now_utc(args)
    if not os.path.exists(os.path.join(MODEL_DIR, "current.json")):
        log("няма обучен слой (layer_model/current.json) - първо features/layer_train.py")
        return
    con = connect()
    state = load_state()
    today = now.strftime("%Y-%m-%d")
    fx = load_fixtures()
    do_pre = (args["force_pre"] or (now.hour >= PRE_HOUR_UTC and state.get("pre_done") != today))
    fin = upcoming(fx, now, FINAL_MIN / 60, FINAL_MAX / 60)
    done_final = {r[0] for r in con.execute("SELECT fixture_id FROM layer_shadow WHERE mode='final'")}
    fin = fin[~fin["fixture_id"].astype(int).isin(done_final)]
    if not do_pre and fin.empty:
        return                                            # нищо за правене - евтин изход на всеки 15 мин
    import importlib
    fas = importlib.import_module("fetch_api_sets")
    from features import build_features as bf
    fetcher = make_fetcher()
    version, meta, boosters = load_models()
    all_rows = []
    try:
        if do_pre:
            n = refresh_fixtures(fetcher, fas)
            log(f"pre: опреснени фикстури за {n} лиги")
            fx = load_fixtures()
            raw = bf.index_raw(bf.load_raw())
            pre = upcoming(fx, now, 0, PRE_HORIZON_H)
            core = core_lambdas(pre)
            rows = predict_rows(core, "AB", version, meta, boosters, raw, "pre", args["dry"]) if len(core) else []
            log(f"pre: {len(pre)} мача в графика, {len(rows)} прогнози")
            all_rows += rows
            if not args["dry"]:
                state["pre_done"] = today
        if not fin.empty:
            have = fetch_lineups_and_injuries(fetcher, fas, fin)
            ready = fin[fin["fixture_id"].astype(int).isin(have)]
            log(f"final: {len(fin)} мача в прозореца, със състави {len(ready)}")
            if len(ready):
                fas._present.clear()
                raw = bf.index_raw(bf.load_raw())
                core = core_lambdas(ready)
                all_rows += predict_rows(core, "ABC", version, meta, boosters, raw, "final", args["dry"]) if len(core) else []
    except bc.QuotaExhausted as e:
        log(f"таван на квотата ({e}) - пропускам")
    except bc.RateLimited as e:
        log(f"429/лимит ({e}) - спирам")
    finally:
        log(f"заявки в този пуск: {fetcher.calls}; оставащи днес {fetcher.remaining_day}")
    if args["dry"]:
        for r in all_rows[:5]:
            print(r[:15])
        log(f"dry-run: {len(all_rows)} реда (не са записани)")
        return
    if all_rows:
        insert(con, all_rows)
        log(f"записани {len(all_rows)} реда в layer_shadow")
    save_state(state)


if __name__ == "__main__":
    main()
