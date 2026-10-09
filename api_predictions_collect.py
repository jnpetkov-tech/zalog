"""api_predictions_collect.py - вградената прогноза на API-Football за предстоящите мачове, САМО записване (ZADACHA_VSICHKO_OT_API, етап 1).

Защо не е признак: /predictions се смята от API-то в деня на заявката (за минал мач знае вече и резултата) -> изтичане. Затова тук се
пази само "както изглеждаше преди мача": за всеки предстоящ мач от 17-те лиги - 1 заявка /predictions в последните 24 ч преди началото,
запис само-добавяне в таблица api_predictions_log (predictions.db). Сравнение с нашия модел - след ~3 месеца (виж PROGRESS_VSICHKO_OT_API.md).
Нищо не се показва. Не внася match_predictor_app. Заявките - през backfill_common.Fetcher (-> api_football._api_get, спиране при 429,
резерв за сайта по live_reserve()). Суровите отговори - api_raw/predictions_live/<дата>.jsonl.gz.

crontab (inkas): 8,38 * * * *  flock -n /tmp/api_predictions.lock venv/bin/python3 api_predictions_collect.py
Лог: api_predictions_log.txt.  Пробно без заявки: --dry-run
"""
import glob
import gzip
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import backfill_common as bc  # noqa: E402

DB = os.path.join(ROOT, "predictions.db")
LOG = os.path.join(ROOT, "api_predictions_log.txt")
LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal", "champions_league", "europa_league",
           "conference_league", "france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
WINDOW_H = 24
DONE_STATUSES = {"FT", "AET", "PEN", "PST", "CANC", "ABD", "AWD", "WO"}
DDL = """CREATE TABLE IF NOT EXISTS api_predictions_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id INTEGER NOT NULL, league TEXT, kickoff_utc TEXT,
    fetched_at TEXT NOT NULL, minutes_to_kickoff REAL, json TEXT)"""
IDX = "CREATE INDEX IF NOT EXISTS idx_api_pred_fx ON api_predictions_log(fixture_id)"


def upcoming(now_ts):
    parts = []
    for lg in LEAGUES:
        p = f"{lg}_fixtures.csv"
        if os.path.exists(p) and os.path.getsize(p):
            parts.append(pd.read_csv(p, usecols=["fixture_id", "league", "timestamp", "status", "fetched_at"], low_memory=False))
    fx = pd.concat(parts).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["timestamp"].notna()]
    m = (fx["timestamp"] > now_ts) & (fx["timestamp"] <= now_ts + WINDOW_H * 3600) & ~fx["status"].isin(DONE_STATUSES)
    return fx[m].sort_values("timestamp")


def main():
    dry = "--dry-run" in sys.argv
    f = bc.Fetcher(LOG)
    now_ts = time.time()
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        con.execute(DDL)
        con.execute(IDX)
        con.commit()
        have = {r[0] for r in con.execute("SELECT DISTINCT fixture_id FROM api_predictions_log")}
        todo = [r for r in upcoming(now_ts).itertuples() if int(r.fixture_id) not in have]
        if not todo:
            return
        if dry:
            f.log(f"[проба] за теглене: {len(todo)} мача")
            return
        f.floor, peak, _ = bc.live_reserve()
        f.check_quota_now()
        if f.remaining_day < f.floor:
            f.log(f"остават {f.remaining_day} < резерв {f.floor} - не тегля ({len(todo)} мача чакат)")
            return
        n = 0
        for r in todo:
            params = {"fixture": int(r.fixture_id)}
            try:
                data = f.get("/predictions", params)
            except (bc.QuotaExhausted, bc.RateLimited) as e:
                f.log(f"спирам: {type(e).__name__} {e}")
                break
            fetched = datetime.utcnow().isoformat(timespec="seconds")
            d = os.path.join(ROOT, "api_raw", "predictions_live")
            os.makedirs(d, exist_ok=True)
            with gzip.open(os.path.join(d, fetched[:10] + ".jsonl.gz"), "at", encoding="utf-8") as g:
                g.write(json.dumps({"params": params, "fetched_at": fetched, "data": data}, ensure_ascii=False) + "\n")
            if data is None or not data.get("response"):
                continue
            mins = (float(r.timestamp) - time.time()) / 60.0
            con.execute("INSERT INTO api_predictions_log (fixture_id, league, kickoff_utc, fetched_at, minutes_to_kickoff, json) VALUES (?,?,?,?,?,?)",
                        (int(r.fixture_id), r.league, datetime.utcfromtimestamp(float(r.timestamp)).isoformat(timespec="minutes"), fetched,
                         round(mins, 1), json.dumps(data["response"][0], ensure_ascii=False)))
            con.commit()
            n += 1
        f.log(f"записани {n} от {len(todo)} мача (заявки {f.calls}, остават днес {f.remaining_day})")
    finally:
        con.close()


if __name__ == "__main__":
    main()
