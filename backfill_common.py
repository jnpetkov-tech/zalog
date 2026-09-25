"""backfill_common.py - общото за фоновите тегления на история
(ZADACHA_GOLQMA.md, етапи 2-3, 24.09.2026): статистика по играчи
(fetch_player_stats.py) и събития в мача (fetch_fixture_events.py).

Правилата, общи за всички тегления:
- Всяка заявка минава през api_football._api_get() - общият лимит на минута
  (в рамките на процеса) + запис в api_calls.log.
- ТАВАН НА КВОТАТА (самонастройващ се, ZADACHA_TEGLENE.md т.1, 25.09.2026):
  спираме, щом дневно оставащите заявки (заглавката
  x-ratelimit-requests-remaining) паднат под РЕЗЕРВА ЗА САЙТА:
  най-тежкият ден на живата система (без тегленията) за последните 7 дни
  + 1000 запас, не по-малко от 2500 и не повече от 6000 (live_reserve()).
  Живата система се мери от api_calls.log: всички заявки без тези на
  тегленията и без /status (не се брои в квотата). Тегленията се различават
  по извикващия в лога - "backfill_request" (от 25.09.2026; преди това
  "get"/"check_quota_now" на 24-25.09). api_calls.log се срязва сам при 5MB
  (остават ~3-4 дни), затова дневните суми се пазят отделно в
  api_daily_usage.csv (извън git) и се допълват при всеки пуск.
  Квотата се нулира в 00:00 UTC; всички тегления гледат едно и също
  оставащо число, т.е. общо харчат най-много 7500 - резерва на ден.
  (До 25.09.2026 резервът беше твърд - 5000.)
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
from datetime import datetime, timedelta

import pandas as pd

import api_football

REPO = os.path.dirname(os.path.abspath(__file__))
DAILY_LIMIT = 7500
RESERVE_MARGIN = 1000      # запас над най-тежкия ден
RESERVE_MIN = 2500
RESERVE_MAX = 6000
RESERVE_DAYS = 7
API_CALLS_LOG = os.path.join(REPO, "api_calls.log")
DAILY_USAGE_CSV = os.path.join(REPO, "api_daily_usage.csv")
# имената на извикващия в api_calls.log, които са тегления, а не живата система
BACKFILL_CALLER = "backfill_request"
OLD_BACKFILL_CALLERS = {"get", "check_quota_now"}      # само 24-25.09.2026
OLD_BACKFILL_DAYS = {"2026-09-24", "2026-09-25"}
MINUTE_FLOOR = 60          # под толкова свободни за минутата -> пауза 60 с
MIN_SECONDS_BETWEEN = 1.0
MAX_RUN_SECONDS = 25 * 60

MAIN_LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal",
                "champions_league", "europa_league", "conference_league"]
SECOND_DIVISIONS = ["france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]


def backfill_request(path, params=None, timeout=20):
    """Всяка заявка на тегленията минава оттук - името на функцията е
    етикетът им в api_calls.log (виж BACKFILL_CALLER)."""
    return api_football._api_get(path, params=params, timeout=timeout)


def _is_backfill(day, caller):
    return caller == BACKFILL_CALLER or (caller in OLD_BACKFILL_CALLERS and day in OLD_BACKFILL_DAYS)


def count_log_by_day(log_path=API_CALLS_LOG):
    """{ден (UTC): [всички, тегления, живата система]} от api_calls.log, без /status."""
    days = {}
    if not os.path.exists(log_path):
        return days
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3 or parts[1] == "/status":
                continue
            day = parts[0][:10]
            c = days.setdefault(day, [0, 0, 0])
            c[0] += 1
            if _is_backfill(day, parts[2]):
                c[1] += 1
            else:
                c[2] += 1
    return days


def update_daily_usage(log_path=API_CALLS_LOG, csv_path=DAILY_USAGE_CSV):
    """Допълва api_daily_usage.csv с дните от лога. Ден, вече записан, се
    сменя само ако новото преброяване е по-голямо (след срязване на лога
    първият ден в него е непълен - не бива да намали записаното)."""
    stored = {}
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                d, total, back, live = line.strip().split(",")
                stored[d] = [int(total), int(back), int(live)]
    for d, c in count_log_by_day(log_path).items():
        if d not in stored or c[0] >= stored[d][0]:
            stored[d] = c
    tmp = csv_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("date,total,backfill,live\n")
        for d in sorted(stored):
            f.write(f"{d},{stored[d][0]},{stored[d][1]},{stored[d][2]}\n")
    os.replace(tmp, csv_path)
    return stored


def live_reserve(today=None, usage=None):
    """(резерв, най-тежкият ден, датата му). Прозорец: последните 7 пълни дни
    + днешният (непълен - може само да вдигне максимума). Без данни -> RESERVE_MAX."""
    if usage is None:
        usage = update_daily_usage()
    today = today or datetime.utcnow().strftime("%Y-%m-%d")
    t = datetime.strptime(today, "%Y-%m-%d")
    window = [(t - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(RESERVE_DAYS + 1)]
    seen = [(usage[d][2], d) for d in window if d in usage]
    if not seen:
        return RESERVE_MAX, None, None
    peak, peak_day = max(seen)
    return min(RESERVE_MAX, max(RESERVE_MIN, peak + RESERVE_MARGIN)), peak, peak_day


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
        self.floor = RESERVE_MAX       # сменя се в run_queue() от live_reserve()

    def log(self, msg):
        line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def time_left(self):
        return MAX_RUN_SECONDS - (time.monotonic() - self.started)

    def check_quota_now(self):
        """/status не се брои в дневната квота (API-Football)."""
        r = backfill_request("/status", timeout=15)
        req = r.json()["response"]["requests"]
        self.remaining_day = req["limit_day"] - req["current"]
        return self.remaining_day

    def get(self, path, params):
        if self.remaining_day is not None and self.remaining_day < self.floor:
            raise QuotaExhausted(self.remaining_day)
        wait = MIN_SECONDS_BETWEEN - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        self.last_call = time.monotonic()
        self.calls += 1
        try:
            r = backfill_request(path, params=params, timeout=20)
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
        try:
            fetcher.floor, peak, peak_day = live_reserve()
        except Exception as e:
            fetcher.floor, peak, peak_day = RESERVE_MAX, None, None
            fetcher.log(f"  резервът не можа да се сметне ({e}) - ползвам {RESERVE_MAX}")
        fetcher.check_quota_now()
        fetcher.log(f"старт: оставащи заявки днес {fetcher.remaining_day}, резерв за сайта {fetcher.floor} "
                    f"(най-тежък ден на сайта {peak} на {peak_day} + {RESERVE_MARGIN})")
        if fetcher.remaining_day < fetcher.floor:
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
        fetcher.log(f"таван: оставащи {e.args[0]} < {fetcher.floor} - спирам до утре (00:00 UTC)")
    finally:
        fetcher.log(f"край на пуска: готови мачове {done_count}, заявки {fetcher.calls}, "
                    f"оставащи днес {fetcher.remaining_day}")
    return done_count


def main_guard():
    os.chdir(REPO)
    sys.path.insert(0, REPO)
