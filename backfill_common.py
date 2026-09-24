"""backfill_common.py - общото за фоновите тегления на история
(ZADACHA_GOLQMA.md, етапи 2-3, 24.09.2026): статистика по играчи
(fetch_player_stats.py) и събития в мача (fetch_fixture_events.py).

Правилата, общи за всички тегления:
- Всяка заявка минава през api_football._api_get() - общият лимит на минута
  (в рамките на процеса) + запис в api_calls.log.
- ТАВАН НА КВОТАТА: спираме, щом дневно оставащите заявки (заглавката
  x-ratelimit-requests-remaining, която API-то връща на всеки отговор)
  паднат под QUOTA_FLOOR. Живата система харчи 1700-3300 заявки на ден
  (api_calls.log, 15-24.09.2026); 5000 = пиковият ден (~3300) + 1500 запас,
  които задачата изисква да останат свободни. Квотата се нулира в 00:00 UTC -
  тегленията харчат най-много 7500 - 5000 = 2500 на ден ОБЩО (всички
  тегления гледат едно и също оставащо число).
- Темпо: най-много една заявка в секунда (60/мин от 300 разрешени) и пауза,
  ако заглавката за минутата покаже, че някой друг (живият сайт) натоварва.
- Продължаване: всеки мач се записва в *_progress.txt веднага след като е
  записан в CSV-то - спиране по средата не губи нищо и не тегли два пъти.
- Един пуск трае най-много MAX_RUN_SECONDS - таймерът е на 30 минути, два
  пуска на един и същи скрипт не се застъпват (плюс flock в crontab).
"""
import os
import sys
import time
from datetime import datetime

import pandas as pd

import api_football

REPO = os.path.dirname(os.path.abspath(__file__))
QUOTA_FLOOR = 5000
MINUTE_FLOOR = 60          # под толкова свободни за минутата -> пауза 60 с
MIN_SECONDS_BETWEEN = 1.0
MAX_RUN_SECONDS = 25 * 60

MAIN_LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal",
                "champions_league", "europa_league", "conference_league"]
SECOND_DIVISIONS = ["france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]


class QuotaExhausted(Exception):
    pass


class Fetcher:
    """Тегли през _api_get със спирачките по-горе. .get() връща JSON-а или
    None при грешка (мачът тогава НЕ се отбелязва като готов - опитва се
    пак при следващ пуск)."""

    def __init__(self, log_path):
        self.log_path = log_path
        self.started = time.monotonic()
        self.last_call = 0.0
        self.calls = 0
        self.remaining_day = None

    def log(self, msg):
        line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def time_left(self):
        return MAX_RUN_SECONDS - (time.monotonic() - self.started)

    def check_quota_now(self):
        """/status не се брои в дневната квота (API-Football)."""
        r = api_football._api_get("/status", timeout=15)
        req = r.json()["response"]["requests"]
        self.remaining_day = req["limit_day"] - req["current"]
        return self.remaining_day

    def get(self, path, params):
        if self.remaining_day is not None and self.remaining_day < QUOTA_FLOOR:
            raise QuotaExhausted(self.remaining_day)
        wait = MIN_SECONDS_BETWEEN - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        self.last_call = time.monotonic()
        self.calls += 1
        try:
            r = api_football._api_get(path, params=params, timeout=20)
        except Exception as e:
            self.log(f"  грешка {path} {params}: {e}")
            return None
        rem = r.headers.get("x-ratelimit-requests-remaining")
        if rem is not None and rem.lstrip("-").isdigit():
            self.remaining_day = int(rem)
        rem_min = r.headers.get("x-ratelimit-remaining")
        if rem_min is not None and rem_min.isdigit() and int(rem_min) < MINUTE_FLOOR:
            self.log(f"  минутният лимит е натоварен ({rem_min} свободни) - пауза 60 с")
            time.sleep(60)
        try:
            data = r.json()
        except ValueError:
            self.log(f"  невалиден JSON {path} {params} (HTTP {r.status_code})")
            return None
        if data.get("errors"):
            self.log(f"  API грешка {path} {params}: {data.get('errors')}")
            return None
        return data


def finished_fixtures(league, min_season):
    """(fixture_id, season, date) на изиграните мачове от {league}_merged_full.csv
    (там влизат само приключили мачове - incremental_refresh.py), най-старите първи."""
    path = os.path.join(REPO, f"{league}_merged_full.csv")
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path, usecols=lambda c: c in ("fixture_id", "season", "date"))
    df = df[df["season"] >= min_season].sort_values("date")
    return [(int(f), int(s), str(d)) for f, s, d in zip(df["fixture_id"], df["season"], df["date"])]


def read_done(progress_path):
    if not os.path.exists(progress_path):
        return set()
    with open(progress_path) as f:
        return {int(x) for x in f if x.strip().lstrip("-").isdigit()}


def run_queue(fetcher, jobs, process_one, max_items=None):
    """jobs: [(league, [fixture_id, ...]), ...] по ред на приоритет.
    process_one(league, fixture_id) -> True (записан/готов) или False (грешка).
    Спира при изчерпан таван или изтекло време. Връща брой готови мачове."""
    done_count = 0
    try:
        fetcher.check_quota_now()
        fetcher.log(f"старт: оставащи заявки днес {fetcher.remaining_day}, таван {QUOTA_FLOOR}")
        if fetcher.remaining_day < QUOTA_FLOOR:
            raise QuotaExhausted(fetcher.remaining_day)
        for league, todo in jobs:
            if not todo:
                continue
            fetcher.log(f"{league}: остават {len(todo)} мача")
            errors = 0
            for fixture_id in todo:
                if max_items is not None and done_count >= max_items:
                    fetcher.log(f"достигнат лимит от {max_items} мача за пуска (ръчен тест)")
                    return done_count
                if fetcher.time_left() <= 0:
                    fetcher.log(f"изтече времето на пуска ({MAX_RUN_SECONDS} с) - продължава следващия път")
                    return done_count
                if process_one(league, fixture_id):
                    done_count += 1
                else:
                    errors += 1
                    if errors >= 20:
                        fetcher.log(f"{league}: 20 грешки в този пуск - минавам на следващата лига")
                        break
    except QuotaExhausted as e:
        fetcher.log(f"таван: оставащи {e.args[0]} < {QUOTA_FLOOR} - спирам до утре (00:00 UTC)")
    finally:
        fetcher.log(f"край на пуска: готови мачове {done_count}, заявки {fetcher.calls}, "
                    f"оставащи днес {fetcher.remaining_day}")
    return done_count


def main_guard():
    os.chdir(REPO)
    sys.path.insert(0, REPO)
