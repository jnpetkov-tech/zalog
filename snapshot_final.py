"""snapshot_final.py - бързата снимка (ZADACHA_SASTAVI_BARZO, 02.10.2026): окончателната прогноза по съставите на сайта до минути.

Самостоятелен процес, crontab на 5 мин веднага след `layer_shadow.py --final-only` (flock). Пълната снимка (systemd, на 30 мин) остава както е.
1. Евтина проверка (само sqlite, без да се внася приложението): мачове с ВАЛИДЕН final ред (layer_live.final_time - същата проверка като на
   сайта: до 3 ч, преди началото, отношение в рамката), чиито редове в predictions_snapshot още НЕ са по него (model_version без "+ABC" или
   смятани преди final реда). Няма такива -> изход.
2. Иначе: общият ключ на снимката (build_predictions_snapshot.SNAPSHOT_LOCK - пълната и бързата никога не вървят заедно), проверката наново
   (пълната може вече да ги е обновила), и build_predictions_snapshot.build(only_fixtures) - СЪЩИЯТ код като пълната снимка, само за лигите
   на тези мачове, пише само техните редове (predictions_snapshot, extra_markets_snapshot, fixture_meta).
Защита от въртене: един мач + един final ред -> най-много MAX_TRIES опита (snapshot_final_state.json). Всяка грешка -> лог, сайтът не се пипа.
Изключено: LAYER_LIVE=0 или LAYER_FINAL_LIVE=0 -> нищо. Лог: snapshot_final_log.txt.
Употреба: venv/bin/python3 snapshot_final.py [--dry-run]
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import warnings  # noqa: E402
warnings.filterwarnings("ignore", category=DeprecationWarning)
import layer_live  # noqa: E402  (само sqlite + config)

DB_PATH = os.path.join(ROOT, "predictions.db")
LOG_PATH = os.path.join(ROOT, "snapshot_final_log.txt")
STATE_PATH = os.path.join(ROOT, "snapshot_final_state.json")
LOCK_WAIT = 120          # пълната снимка трае ~40-60 с
MAX_TRIES = 3


def log(msg):
    line = f"{datetime.utcnow().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def stale_fixtures():
    """{fixture_id: (league, final computed_at)} - final ред е валиден, а снимката на мача още не е по него."""
    out = {}
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    try:
        now_ts = int(time.time())
        cut = (datetime.utcnow() - timedelta(hours=layer_live.FINAL_MAX_AGE_H)).isoformat(timespec="seconds")
        finals = con.execute("SELECT fixture_id, league, MAX(computed_at) FROM layer_shadow WHERE mode='final' AND computed_at >= ? "
                             "AND kickoff_ts > ? GROUP BY fixture_id", (cut, now_ts)).fetchall()
        for fid, league, fin_at in finals:
            if layer_live.final_time(fid) is None:
                continue                                # невалиден за сайта -> и снимката няма да го ползва
            rows = con.execute("SELECT model_version, computed_at FROM predictions_snapshot WHERE fixture_id=? AND is_candidate=1",
                               (fid,)).fetchall()
            if not rows:
                continue                                # мачът не е в снимката (нов отбор и т.н.) - няма какво да се обновява
            if any("+ABC" not in (mv or "") for mv, _ in rows) or min(str(c)[:19] for _, c in rows) < fin_at:
                out[int(fid)] = (league, fin_at)
    finally:
        con.close()
    return out


def drop_leftovers(fixture_ids, start):
    """Редове на тези мачове в predictions_snapshot, които НЕ са презаписани сега (пазари, които вече не се смятат - напр. стар ред
    полувреме/край от предни дни). Надписът "обновено след съставите" гледа часа на ред на мача - стар ред би го скрил. Трие се само ако
    мачът има нови редове от този пуск."""
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        n = 0
        for fid in fixture_ids:
            if con.execute("SELECT 1 FROM predictions_snapshot WHERE fixture_id=? AND computed_at >= ? LIMIT 1", (fid, start)).fetchone():
                n += con.execute("DELETE FROM predictions_snapshot WHERE fixture_id=? AND computed_at < ?", (fid, start)).rowcount
        con.commit()
        if n:
            log(f"махнати {n} стари реда (пазари, които вече не се смятат)")
    finally:
        con.close()


def load_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {}


def save_state(st):
    tmp = STATE_PATH + ".tmp"
    json.dump(st, open(tmp, "w"))
    os.replace(tmp, STATE_PATH)


def main():
    dry = "--dry-run" in sys.argv
    if not layer_live.final_enabled():
        return
    try:
        todo = stale_fixtures()
    except Exception as e:
        log(f"проверка: грешка {type(e).__name__}: {e}")
        return
    state = load_state()
    todo = {f: v for f, v in todo.items() if state.get(f"{f}|{v[1]}", 0) < MAX_TRIES}
    if not todo:
        return                                          # евтиният изход - почти винаги
    log(f"нови final за снимката: {sorted(todo)}")
    if dry:
        return
    import build_predictions_snapshot as bps
    lk = bps.acquire_lock(LOCK_WAIT)
    if lk is None:
        log(f"ключът на снимката е зает над {LOCK_WAIT} с - пак след 5 мин")
        return
    try:
        todo = {f: v for f, v in stale_fixtures().items() if f in todo}   # пълната може вече да ги е обновила
        if not todo:
            log("вече обновени от пълната снимка")
            return
        for f, v in todo.items():
            k = f"{f}|{v[1]}"
            state[k] = state.get(k, 0) + 1
        save_state(state)
        t0 = time.time()
        start = datetime.utcnow().isoformat()
        bps.build(only_fixtures={f: v[0] for f, v in todo.items()})
        drop_leftovers(list(todo), start)
        left = stale_fixtures()
        log(f"готово за {time.time() - t0:.1f} с: {len(todo)} мача; още не по final: {sorted(set(left) & set(todo))}")
    except Exception as e:
        log(f"грешка {type(e).__name__}: {e} - сайтът остава с предишната снимка")
    finally:
        lk.close()
    # чистене на старите ключове (по-стари от 2 дни)
    cut = (datetime.utcnow() - timedelta(days=2)).isoformat()
    save_state({k: v for k, v in state.items() if k.split("|")[1] >= cut})


if __name__ == "__main__":
    main()
