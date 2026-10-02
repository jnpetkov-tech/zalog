"""
ZADACHA_RAZVITIE т.2 (02.10.2026): история на коефициентите по мач - САМО
вътрешно мерило. Нищо от тук не се показва на сайта и не влиза в логиката
(никой жив модул не чете odds_log). Дизайн: validation/api_inventar_20261001.md,
раздел 5.

Самостоятелен процес от crontab на inkas (на 5 мин, flock). Не импортира
match_predictor_app. Таблица odds_log в predictions.db - само се добавя
(тригери забраняват UPDATE/DELETE). Три вида записи (колона kind):

  first  - първите налични коефициенти за мача: копие на реда в odds_cache
           (там ги вече е теглил refresh-odds - 0 нови заявки).
  daily  - по един на ден: копие на odds_cache, ако кешът е обновен
           >= 24 ч след последния first/daily запис (0 нови заявки).
  close  - собствено теглене на /odds в последните CLOSE_WINDOW_MIN минути
           преди началото, най-много веднъж на CLOSE_MIN_GAP_MIN минути на мач.
           Затварящият коефициент = последният close ред с
           minutes_to_kickoff >= 0. Пази и диапазона по изход (мин./макс./брой
           букмейкъри) и коефициента на референтен букмейкър (Pinnacle), ако го има.

fetched_at = моментът на коефициентите (за first/daily - fetched_at на кеша;
за close - сега), recorded_at = кога е записан редът. Всичко в UTC.
Мачовете идват от predictions_snapshot (match_date е българско време).

Превключвател: ODDS_LOG в .env (1 = работи; 0/липсва = нищо не прави).
Всяка грешка се записва в odds_history_log.txt и скриптът излиза тихо.
"""
import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.join(BASE_DIR, "predictions.db")
LOG_PATH = os.path.join(BASE_DIR, "odds_history_log.txt")
SOFIA_TZ = ZoneInfo("Europe/Sofia")

CLOSE_WINDOW_MIN = 20     # close тегления само за мачове, които почват до 20 мин
CLOSE_MIN_GAP_MIN = 4     # не по-често от веднъж на ~5 мин (cron е на 5 мин)
DAILY_GAP_H = 24
REFERENCE_BOOKMAKERS = ("Pinnacle",)

# Колона в odds_cache -> код на пазара (същите кодове като predictions_log).
_CACHE_COLS = {"home_odds": "home_win", "draw_odds": "draw", "away_odds": "away_win",
               "over25_odds": "over25", "under25_odds": "under25"}

# Изходи в /odds -> код на пазара (същото като api_football.fetch_fixture_odds,
# плюс над/под 1.5 и 3.5 - за бъдещите пазари от т.5).
_BETS = {
    "Match Winner": {"Home": "home_win", "Draw": "draw", "Away": "away_win"},
    "Goals Over/Under": {"Over 1.5": "over15", "Under 1.5": "under15",
                         "Over 2.5": "over25", "Under 2.5": "under25",
                         "Over 3.5": "over35", "Under 3.5": "under35"},
    "Total - Home": {"Over 1.5": "home_over15", "Under 1.5": "home_under15"},
    "Total - Away": {"Over 1.5": "away_over15", "Under 1.5": "away_under15"},
    "Double Chance": {"Home/Draw": "dc_1x", "Draw/Away": "dc_x2", "Home/Away": "dc_12"},
    "Both Teams Score": {"Yes": "btts_yes", "No": "btts_no"},
}
_HTFT_SIDE = {"Home": "1", "Draw": "X", "Away": "2"}


def log(msg):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}\n")


def _enabled():
    try:
        from config import ODDS_LOG
        return ODDS_LOG
    except Exception:
        return False


def init_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS odds_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fixture_id INTEGER NOT NULL, kind TEXT NOT NULL,
            fetched_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
            kickoff_utc TEXT, minutes_to_kickoff REAL, odds_json TEXT
        )""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_odds_log_fix_kind_at "
                 "ON odds_log(fixture_id, kind, fetched_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_odds_log_fix_at ON odds_log(fixture_id, fetched_at)")
    conn.execute("CREATE TRIGGER IF NOT EXISTS odds_log_no_update BEFORE UPDATE ON odds_log "
                 "BEGIN SELECT RAISE(ABORT, 'odds_log е само за добавяне'); END")
    conn.execute("CREATE TRIGGER IF NOT EXISTS odds_log_no_delete BEFORE DELETE ON odds_log "
                 "BEGIN SELECT RAISE(ABORT, 'odds_log е само за добавяне'); END")
    conn.commit()


def upcoming_fixtures(conn, now_utc):
    """{fixture_id: kickoff_utc (datetime)} за мачовете в снимката, които още не са почнали."""
    out = {}
    for fid, md in conn.execute("SELECT fixture_id, MIN(match_date) FROM predictions_snapshot "
                                "GROUP BY fixture_id"):
        try:
            ko = datetime.strptime(md[:16], "%Y-%m-%d %H:%M").replace(tzinfo=SOFIA_TZ).astimezone(timezone.utc)
        except Exception:
            continue
        if ko > now_utc:
            out[int(fid)] = ko
    return out


def cache_odds(conn, fixture_id):
    """(fetched_at, {код: средно}) от odds_cache или None."""
    cur = conn.execute("SELECT * FROM odds_cache WHERE fixture_id=?", (fixture_id,))
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    rec = dict(zip(cols, row))
    odds = {}
    for col, val in rec.items():
        if not col.endswith("_odds") or val is None:
            continue
        if col in _CACHE_COLS:
            code = _CACHE_COLS[col]
        elif col.startswith("htft_"):
            a, b = col[5:-5].split("_")
            code = f"htft:{a.upper()}/{b.upper()}"
        else:
            code = col[:-5]
        odds[code] = {"mean": val}
    if not odds or not rec.get("fetched_at"):
        return None
    return rec["fetched_at"], odds


def parse_odds_response(data):
    """Суровият /odds отговор -> {код: {mean, min, max, n, ref?}}. mean се
    закръгля като avg() в api_football.fetch_fixture_odds (2 знака) - сравнимо с кеша."""
    lists, ref = {}, {}
    resp = data.get("response") or []
    if not resp:
        return {}
    for bm in resp[0].get("bookmakers", []):
        is_ref = bm.get("name") in REFERENCE_BOOKMAKERS
        for bet in bm.get("bets", []):
            name = bet.get("name")
            for v in bet.get("values", []):
                code = None
                if name in _BETS:
                    code = _BETS[name].get(v.get("value"))
                elif name == "HT/FT Double":
                    parts = str(v.get("value", "")).split("/")
                    if len(parts) == 2 and parts[0] in _HTFT_SIDE and parts[1] in _HTFT_SIDE:
                        code = f"htft:{_HTFT_SIDE[parts[0]]}/{_HTFT_SIDE[parts[1]]}"
                if not code:
                    continue
                try:
                    odd = float(v["odd"])
                except Exception:
                    continue
                lists.setdefault(code, []).append(odd)
                if is_ref:
                    ref[code] = odd
    out = {}
    for code, lst in lists.items():
        out[code] = {"mean": round(sum(lst) / len(lst), 2), "min": min(lst), "max": max(lst), "n": len(lst)}
        if code in ref:
            out[code]["ref"] = ref[code]
    return out


def _utc(iso):
    d = datetime.fromisoformat(iso)
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def _insert(conn, fid, kind, fetched_at, now_utc, ko, odds):
    mins = (ko - _utc(fetched_at)).total_seconds() / 60.0
    cur = conn.execute("INSERT OR IGNORE INTO odds_log (fixture_id, kind, fetched_at, recorded_at, kickoff_utc, "
                       "minutes_to_kickoff, odds_json) VALUES (?,?,?,?,?,?,?)",
                       (fid, kind, fetched_at, now_utc.isoformat(), ko.isoformat(), round(mins, 1),
                        json.dumps(odds, ensure_ascii=False, sort_keys=True) if odds is not None else None))
    return cur.rowcount


def record_from_cache(conn, fixtures, now_utc):
    """first/daily от odds_cache (0 заявки). odds_cache.fetched_at е наивно UTC
    (datetime.now() в system_tracker, сървърът е в UTC)."""
    n_first = n_daily = 0
    for fid, ko in fixtures.items():
        c = cache_odds(conn, fid)
        if not c:
            continue
        fetched_at, odds = c
        last = conn.execute("SELECT MAX(fetched_at) FROM odds_log WHERE fixture_id=? AND kind IN ('first','daily')",
                            (fid,)).fetchone()[0]
        if last is None:
            n_first += _insert(conn, fid, "first", fetched_at, now_utc, ko, odds)
        elif _utc(fetched_at) - _utc(last) >= timedelta(hours=DAILY_GAP_H):
            n_daily += _insert(conn, fid, "daily", fetched_at, now_utc, ko, odds)
    conn.commit()
    return n_first, n_daily


def record_closing(conn, fixtures, now_utc):
    """close: собствено теглене за мачовете, които почват до CLOSE_WINDOW_MIN мин."""
    import api_football as af
    n_req = n_ok = 0
    for fid, ko in sorted(fixtures.items(), key=lambda x: x[1]):
        mins = (ko - now_utc).total_seconds() / 60.0
        if not (0 < mins <= CLOSE_WINDOW_MIN):
            continue
        last = conn.execute("SELECT MAX(recorded_at) FROM odds_log WHERE fixture_id=? AND kind='close'",
                            (fid,)).fetchone()[0]
        if last and now_utc - _utc(last) < timedelta(minutes=CLOSE_MIN_GAP_MIN):
            continue
        try:
            n_req += 1
            data = af._api_get("/odds", params={"fixture": fid}, timeout=15).json()
            odds = parse_odds_response(data) if not data.get("errors") else {}
        except Exception as e:
            log(f"close {fid}: грешка {e!r}")
            continue
        # празен отговор също се записва (odds_json NULL) - за броя опити и
        # за CLOSE_MIN_GAP_MIN; затварящ коефициент е само ред с odds_json.
        n_ok += bool(odds)
        _insert(conn, fid, "close", now_utc.replace(tzinfo=None).isoformat(), now_utc, ko, odds or None)
        conn.commit()
    return n_req, n_ok


def main():
    if not _enabled():
        return
    now_utc = datetime.now(timezone.utc)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        init_table(conn)
        fixtures = upcoming_fixtures(conn, now_utc)
        n_first, n_daily = record_from_cache(conn, fixtures, now_utc)
        n_req, n_ok = record_closing(conn, fixtures, now_utc)
        if n_first or n_daily or n_req:
            log(f"мачове {len(fixtures)}; first {n_first}, daily {n_daily}; close заявки {n_req}, с коефициенти {n_ok}")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("ГРЕШКА " + traceback.format_exc().replace("\n", " | "))
