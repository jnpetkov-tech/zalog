"""layer_live.py - обученият слой в ЖИВАТА прогноза (ZADACHA_ZHIVO, 01.10.2026, решение на Дака).

Основа: validation/sloy_vlizane_20261001.md. Слоят (LightGBM, features/layer_lib.py) коригира очакваните голове на ядрото:
lam' = lam * exp(s * изход), mu' = mu * exp(s * изход); rho остава на ядрото. Версия 1 = набор признаци AB (известни дни преди мача);
ABC остава в сянка (layer_shadow.py) за окончателната прогноза.

Две половини (нарочно разделени - Flask не внася тежките библиотеки):
  refresh()  - САМО от самостоятелния build_predictions_snapshot.py (преди цикъла по лиги): за предстоящите мачове смята признаците (същия код като
               таблицата), пуска слоя и записва в таблица layer_live (predictions.db) lam/mu на ядрото и след слоя, версия, час.
  apply()    - от живия код (Flask и снимката), на ЕДНО място след get_ft_lambdas(): намира реда на мача и прилага ОТНОШЕНИЕТО слой/ядро върху
               lam/mu, получени в момента (така контузиите/xG от ядрото си остават; отношението е ≤ ±28% по измерването). Само sqlite + config.
Връщане към старото (две стъпки): LAYER_LIVE=0 в .env (snapshot - при следващия цикъл; Flask - след рестарт); при 0 apply() връща входа БАЙТ ПО БАЙТ.
Всеки мач, за който няма ред/признаци/слоят хвърли грешка -> пада на ядрото и се записва в layer_live_log.txt; сайтът не гърми.
Калибрация за слоя (LAYER_CALIBRATION_A) живее ТУК (prediction_policy.py не се пипа) и се прилага само за мачове, минали през слоя.
"""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import config

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "predictions.db")
LOG_PATH = os.path.join(ROOT, "layer_live_log.txt")
MODEL_DIR = os.path.join(ROOT, "layer_model")
FEATURE_SET = "AB"
HORIZON_H = 8 * 24             # снимката гледа DAYS_AHEAD=7 дни напред; малък запас
MAX_AGE_H = 36                 # ред по-стар от това (снимката е спряла) -> ядро
RATIO_RANGE = (0.5, 2.0)       # защита: измереното максимум е ±28%; извън това -> ядро

# Калибрация за ядро+слой: a от ранната половина (validation/sloy_kalibraciq_20261001.csv, колона a_layer_early); b (базовите честоти) - същите
# като CALIBRATION_BASE в prediction_policy.py. Корнерите не минават през слоя - остават с a от prediction_policy.
LAYER_CALIBRATION_A = {"1x2": 0.9963, "ou25": 1.02, "btts": 1.0665, "team_total": 0.9406}

DDL = """
CREATE TABLE IF NOT EXISTS layer_live (
    fixture_id INTEGER PRIMARY KEY,
    league TEXT, match_date TEXT, computed_at TEXT NOT NULL, feature_set TEXT, layer_version TEXT,
    lam_core REAL, mu_core REAL, lam_layer REAL, mu_layer REAL)"""

_lock = threading.Lock()
_cache = {"at": 0.0, "rows": {}}
_logged = set()
CACHE_TTL = 60


def enabled():
    return bool(getattr(config, "LAYER_LIVE", False))


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.utcnow().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass


def _connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _load_rows():
    now = time.time()
    with _lock:
        if now - _cache["at"] < CACHE_TTL:
            return _cache["rows"]
        rows = {}
        try:
            con = _connect()
            try:
                for r in con.execute("SELECT fixture_id, computed_at, layer_version, lam_core, mu_core, lam_layer, mu_layer FROM layer_live"):
                    rows[int(r[0])] = r[1:]
            finally:
                con.close()
        except Exception as e:                      # няма таблица/заключена база -> всичко пада на ядрото
            log(f"четене на layer_live: {e}")
        _cache.update(at=now, rows=rows)
        return rows


def apply(fixture_id, lam, mu):
    """-> (lam, mu, layer_version|None). None = мачът НЕ е минал през слоя (изключен, няма ред, стар ред, грешка) - входът е върнат непроменен."""
    if not enabled() or fixture_id is None or lam is None or mu is None:
        return lam, mu, None
    try:
        row = _load_rows().get(int(fixture_id))
        if row is None:
            _note(fixture_id, "няма ред в layer_live (признаци/фикстура липсват)")
            return lam, mu, None
        computed_at, version, lam_c, mu_c, lam_l, mu_l = row
        age_h = (datetime.utcnow() - datetime.fromisoformat(computed_at)).total_seconds() / 3600
        if age_h > MAX_AGE_H:
            _note(fixture_id, f"редът е стар ({age_h:.0f} ч)")
            return lam, mu, None
        rh, ra = lam_l / lam_c, mu_l / mu_c
        if not (RATIO_RANGE[0] <= rh <= RATIO_RANGE[1] and RATIO_RANGE[0] <= ra <= RATIO_RANGE[1]):
            _note(fixture_id, f"отношение извън рамката {rh:.2f}/{ra:.2f}")
            return lam, mu, None
        return lam * rh, mu * ra, version
    except Exception as e:
        _note(fixture_id, f"грешка: {e}")
        return lam, mu, None


def _note(fixture_id, why):
    key = (int(fixture_id), why.split(" (")[0])
    if key not in _logged:                          # веднъж на процес на мач+причина (без наводняване на лога)
        _logged.add(key)
        log(f"падане на ядро: мач {fixture_id}: {why}")


def calibrate(prob_pct, market_code):
    """Като prediction_policy.calibrate(), но с коефициентите за ядро+слой. Вика се само за мачове, минали през слоя."""
    import prediction_policy as policy
    if not policy.CALIBRATION_ENABLED or prob_pct is None:
        return prob_pct
    b = policy.CALIBRATION_BASE.get(market_code)
    group = policy.market_group(market_code)
    a = LAYER_CALIBRATION_A.get(group, policy.CALIBRATION_A.get(group, 1.0))
    if b is None or a == 1.0:
        return prob_pct
    p = b + a * (prob_pct / 100.0 - b)
    return 100.0 * min(1.0, max(0.0, p))


# ----------------------------------------------------------------------------------------------- само за снимката (самостоятелен процес)
def refresh(now=None, horizon_h=HORIZON_H):
    """Пуска слоя (набор AB) за предстоящите мачове и пише layer_live. Никога не хвърля - при грешка слоят просто не се обновява (старите редове
    остават до MAX_AGE_H, после -> ядро). -> (брой записани, брой мачове в графика, секунди)."""
    t0 = time.time()
    n_rows = n_sched = 0
    try:
        import warnings
        warnings.filterwarnings("ignore")
        import layer_shadow as ls
        from features import build_features as bf
        from features import layer_lib as L
        now = now or datetime.utcnow()
        fx = ls.load_fixtures()
        sched = ls.upcoming(fx, now, 0, horizon_h)
        n_sched = len(sched)
        if not n_sched:
            return 0, 0, time.time() - t0
        core = ls.core_lambdas(sched)
        have = set(core["fixture_id"]) if len(core) else set()
        for r in sched.itertuples():
            if int(r.fixture_id) not in have:
                _note(r.fixture_id, "няма ядро (отбор извън модела) ")
        if not len(core):
            return 0, n_sched, time.time() - t0
        version, meta, boosters = ls.load_models()
        raw = bf.index_raw(bf.load_raw())
        tab = bf.build(core, raw)
        missing = have - set(tab["fixture_id"]) if len(tab) else have
        for fid in missing:
            _note(fid, "няма признаци (фикстурата липсва в данните) ")
        if not len(tab):
            return 0, n_sched, time.time() - t0
        import numpy as np
        import pandas as pd
        tab["d"] = pd.to_datetime(tab["date"])
        tab["week"] = tab["d"] - pd.to_timedelta(tab["d"].dt.weekday, unit="D")
        tab["league_code"] = tab["league"].map(L.LEAGUE_CODES).astype(float)
        tab["hg"] = np.nan
        tab["ag"] = np.nan
        lam1, mu1 = L.predict_corrected(boosters[FEATURE_SET], FEATURE_SET, tab, meta["models"][FEATURE_SET]["shrink"])
        fxm = fx.set_index("fixture_id")
        stamp = datetime.utcnow().isoformat(timespec="seconds")
        out = []
        for i, r in enumerate(tab.itertuples()):
            if not (np.isfinite(lam1[i]) and np.isfinite(mu1[i])):
                _note(r.fixture_id, "слоят върна нечислова стойност")
                continue
            ts = int(fxm.loc[r.fixture_id, "ts"])
            out.append((int(r.fixture_id), r.league, datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M"), stamp, FEATURE_SET, version,
                        float(r.lam), float(r.mu), float(lam1[i]), float(mu1[i])))
        con = _connect()
        try:
            con.execute(DDL)
            con.executemany("INSERT OR REPLACE INTO layer_live (fixture_id, league, match_date, computed_at, feature_set, layer_version, "
                            "lam_core, mu_core, lam_layer, mu_layer) VALUES (?,?,?,?,?,?,?,?,?,?)", out)
            con.execute("DELETE FROM layer_live WHERE match_date < ?", ((now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),))
            con.commit()
        finally:
            con.close()
        n_rows = len(out)
    except Exception as e:
        log(f"refresh: грешка, слоят не е обновен: {type(e).__name__}: {e}")
    secs = time.time() - t0
    log(f"refresh: {n_sched} мача в графика, {n_rows} записани, {secs:.1f} с")
    return n_rows, n_sched, secs
