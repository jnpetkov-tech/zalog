"""injuries_upcoming.py — контузените/наказаните ПО ИГРАЧ за мачовете в следващите 48 часа (ZADACHA_TEKST_2, Дака 06.10.2026).

Защо: живият кеш injuries_cache пази само БРОЙ контузени на отбор; за текста на мача ("Левски ще е без титулярния вратар ...")
трябват имената. /injuries?ids=a-b-... (до 20 мача на заявка) -> таблица injuries_players (predictions.db).
Чете се само от match_text.py (снимката) - не влиза в модела, слоя или признаците.

Самостоятелен процес (crontab на inkas, на час, flock) - не внася match_predictor_app; заявките минават през api_football._api_get
(общият брояч/лимит). ~60 мача в 48 ч -> 3 заявки на пуск, ~72 на ден.
Употреба: venv/bin/python3 injuries_upcoming.py [--dry-run]
"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "predictions.db")
LOG_PATH = os.path.join(ROOT, "injuries_upcoming_log.txt")
WINDOW_H = 48
BATCH = 20

DDL = """
CREATE TABLE IF NOT EXISTS injuries_players (
    fixture_id INTEGER NOT NULL, team_id INTEGER, player_id INTEGER, player TEXT,
    type TEXT,                 -- "Missing Fixture" (няма да играе) / "Questionable" (под въпрос)
    reason TEXT, fetched_at TEXT NOT NULL
)"""


def log(msg):
    line = f"{datetime.utcnow().isoformat(timespec='seconds')} {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def upcoming(con, hours=None):
    """Мачовете от снимката с начало от преди 3 ч до след `hours` ч (по подразбиране WINDOW_H; match_date е местно време, като в снимката)."""
    hours = hours or WINDOW_H
    now = datetime.now()
    lo, hi = (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"), (now + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    return [r[0] for r in con.execute("SELECT DISTINCT fixture_id FROM predictions_snapshot WHERE match_date >= ? AND match_date <= ? "
                                      "ORDER BY match_date", (lo, hi))]


def main(dry_run=False, db_path=DB_PATH, get=None):
    con = sqlite3.connect(db_path, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        con.execute(DDL)
        con.execute("CREATE INDEX IF NOT EXISTS idx_injuries_players_fx ON injuries_players(fixture_id)")
        con.commit()
        fids = upcoming(con)
        if dry_run or not fids:
            log(f"мачове в {WINDOW_H} ч: {len(fids)}" + (" (dry-run)" if dry_run else ""))
            return 0
        if get is None:
            import api_football as af
            get = lambda ids: af._api_get("/injuries", params={"ids": ids}, timeout=20).json()
        n_req = n_rows = 0
        stamp = datetime.utcnow().isoformat(timespec="seconds")
        for i in range(0, len(fids), BATCH):
            part = fids[i:i + BATCH]
            try:
                data = get("-".join(str(f) for f in part))
                n_req += 1
            except Exception as e:
                log(f"заявка {part[0]}..: {type(e).__name__}: {e} - старите редове остават")
                continue
            if not isinstance(data, dict) or data.get("errors"):
                log(f"заявка {part[0]}..: грешка от API-то {data.get('errors') if isinstance(data, dict) else data!r} - старите редове остават")
                continue
            rows = []
            for x in data.get("response") or []:
                fx, tm, pl = x.get("fixture") or {}, x.get("team") or {}, x.get("player") or {}
                if fx.get("id") in part:
                    rows.append((fx["id"], tm.get("id"), pl.get("id"), pl.get("name"), pl.get("type"), pl.get("reason"), stamp))
            # заявката е минала: за тези мачове важи само новият списък (вкл. празен - никой не липсва)
            con.execute(f"DELETE FROM injuries_players WHERE fixture_id IN ({','.join('?' * len(part))})", part)
            con.executemany("INSERT INTO injuries_players VALUES (?,?,?,?,?,?,?)", rows)
            con.commit()
            n_rows += len(rows)
        con.execute("DELETE FROM injuries_players WHERE fetched_at < ?", ((datetime.utcnow() - timedelta(days=10)).isoformat(),))
        con.commit()
        log(f"мачове {len(fids)}, заявки {n_req}, редове {n_rows}")
        return n_rows
    finally:
        con.close()


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
