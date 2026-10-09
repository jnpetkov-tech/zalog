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
- Лимитите идват от API-то, не са твърди (01.10.2026, Ultra план): дневният от
  /status (limit_day), минутният от заглавката x-ratelimit-limit (Pro: 300,
  Ultra: 450). DAILY_LIMIT/MINUTE_LIMIT по-долу са само резерва, ако /status не отговори.
- Темпо (от 01.10.2026): до 4 заявки в секунда, но не повече от 60% от лимита
  на минута. Стъпаловидно по заглавката x-ratelimit-remaining (оставащи в
  минутата): над 30% от лимита - бързо; 20-30% - 1 заявка/сек; под 20% -
  пауза 60 с (някой друг - живият сайт - натоварва). 429 или API грешка за
  лимит - СПИРАМЕ пуска (RateLimited), записваме какво е станало.
- Продължаване: всеки мач се записва в *_progress.txt веднага след като е
  записан в CSV-то - спиране по средата не губи нищо и не тегли два пъти.
- Един пуск трае най-много MAX_RUN_SECONDS (25 мин; за ръчно дълго пускане -
  променливата BACKFILL_MAX_RUN_SECONDS) - таймерът е на 30 минути, два
  пуска на един и същи скрипт не се застъпват (плюс flock в crontab).
"""
import math
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd

import api_football

REPO = os.path.dirname(os.path.abspath(__file__))
DAILY_LIMIT = 7500         # само резерва, ако /status не отговори (реалният идва от /status)
MINUTE_LIMIT = 300         # същото - реалният идва от x-ratelimit-limit
# ZADACHA_VSICHKO_OT_API (Дака, 09.10.2026): резерв за сайта = max(RESERVE_FLOOR, RESERVE_FACTOR × най-тежкия ден на живата система за
# последните 7 дни); без горна граница (старото: min(6000, max(2500, пик + 1000))). Всичко над резерва - за тегленията.
RESERVE_FLOOR = 8000
RESERVE_FACTOR = 1.5
RESERVE_MAX = RESERVE_FLOOR  # резервата, когато резервът не може да се сметне (името остава - ползва го и layer_shadow.py)
RESERVE_DAYS = 7
API_CALLS_LOG = os.path.join(REPO, "api_calls.log")
DAILY_USAGE_CSV = os.path.join(REPO, "api_daily_usage.csv")
# имената на извикващия в api_calls.log, които са тегления, а не живата система
BACKFILL_CALLER = "backfill_request"
OLD_BACKFILL_CALLERS = {"get", "check_quota_now"}      # само 24-25.09.2026
OLD_BACKFILL_DAYS = {"2026-09-24", "2026-09-25"}
MAX_RATE_PER_SEC = 4.0     # таван на темпото
MAX_SHARE_OF_MINUTE = 0.6  # и не повече от 60% от лимита на минута (запас за сайта)
SLOW_INTERVAL = 1.0        # темпо при 20-30% свободни за минутата
PAUSE_BELOW = 0.20         # под толкова от лимита свободни в минутата -> пауза
SLOW_BELOW = 0.30          # под толкова -> бавно темпо
PAUSE_SECONDS = 60
USAGE_REFRESH_SECONDS = 300   # дневните суми се допълват в хода на пуска (api_calls.log се срязва при 5MB)
MAX_RUN_SECONDS = int(os.environ.get("BACKFILL_MAX_RUN_SECONDS", 25 * 60))

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
    + днешният (непълен - може само да вдигне максимума). Без данни -> RESERVE_FLOOR.
    Резерв = max(RESERVE_FLOOR, RESERVE_FACTOR × пик), закръглен нагоре до цяло число."""
    if usage is None:
        usage = update_daily_usage()
    today = today or datetime.utcnow().strftime("%Y-%m-%d")
    t = datetime.strptime(today, "%Y-%m-%d")
    window = [(t - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(RESERVE_DAYS + 1)]
    seen = [(usage[d][2], d) for d in window if d in usage]
    if not seen:
        return RESERVE_FLOOR, None, None
    peak, peak_day = max(seen)
    return max(RESERVE_FLOOR, int(math.ceil(RESERVE_FACTOR * peak))), peak, peak_day


class QuotaExhausted(Exception):
    pass


class RateLimited(Exception):
    """429 или API грешка за лимит на минута/ден - пускът спира (не повтаря)."""


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
        self.daily_limit = DAILY_LIMIT     # сменя се от /status (check_quota_now)
        self.minute_limit = MINUTE_LIMIT   # сменя се от x-ratelimit-limit
        self.interval = self.fast_interval()
        self.rate_limited = False      # вдига се при 429/rateLimit - извикващият скрипт спира всичко
        self.last_usage_update = time.monotonic()
        self.floor = RESERVE_MAX       # сменя се в run_queue() от live_reserve()

    def fast_interval(self):
        """Секунди между заявките при свободна минута: до MAX_RATE_PER_SEC/сек,
        но не над MAX_SHARE_OF_MINUTE от лимита на минута."""
        per_sec = min(MAX_RATE_PER_SEC, MAX_SHARE_OF_MINUTE * self.minute_limit / 60.0)
        return 1.0 / per_sec

    def _read_limits(self, headers):
        lim = headers.get("x-ratelimit-limit")
        if lim is not None and lim.isdigit() and int(lim) > 0:
            self.minute_limit = int(lim)
        lim_day = headers.get("x-ratelimit-requests-limit")
        if lim_day is not None and lim_day.isdigit() and int(lim_day) > 0:
            self.daily_limit = int(lim_day)

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
        self.daily_limit = req["limit_day"]
        self.remaining_day = req["limit_day"] - req["current"]
        self._read_limits(r.headers)
        self.interval = self.fast_interval()
        return self.remaining_day

    def get(self, path, params):
        if self.remaining_day is not None and self.remaining_day < self.floor:
            raise QuotaExhausted(self.remaining_day)
        wait = self.interval - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        self.last_call = time.monotonic()
        self.calls += 1
        if self.last_call - self.last_usage_update > USAGE_REFRESH_SECONDS:
            self.last_usage_update = self.last_call
            try:
                update_daily_usage()
            except Exception as e:
                self.log(f"  дневните суми не можаха да се допълнят ({e})")
        try:
            r = backfill_request(path, params=params, timeout=20)
        except Exception as e:
            self.log(f"  грешка {path} {params}: {e}")
            return None
        if r.status_code == 429:
            self.log(f"  HTTP 429 {path} {params} - спирам пуска")
            self.rate_limited = True
            raise RateLimited("HTTP 429")
        self._read_limits(r.headers)
        rem = r.headers.get("x-ratelimit-requests-remaining")
        if rem is not None and rem.lstrip("-").isdigit():
            self.remaining_day = int(rem)
        rem_min = r.headers.get("x-ratelimit-remaining")
        if rem_min is not None and rem_min.isdigit():
            share = int(rem_min) / self.minute_limit
            if share < PAUSE_BELOW:
                self.log(f"  минутният лимит е натоварен ({rem_min} от {self.minute_limit} свободни) - пауза {PAUSE_SECONDS} с")
                time.sleep(PAUSE_SECONDS)
                self.interval = SLOW_INTERVAL
            elif share < SLOW_BELOW:
                self.interval = SLOW_INTERVAL
            else:
                self.interval = self.fast_interval()
        try:
            data = r.json()
        except ValueError:
            self.log(f"  невалиден JSON {path} {params} (HTTP {r.status_code})")
            return None
        errors = data.get("errors")
        if errors:
            self.log(f"  API грешка {path} {params}: {errors}")
            if isinstance(errors, dict):
                if "rateLimit" in errors:
                    self.rate_limited = True
                    raise RateLimited(str(errors))
                if "requests" in errors:
                    raise QuotaExhausted(0)
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
        fetcher.log(f"старт: оставащи заявки днес {fetcher.remaining_day} от {fetcher.daily_limit}, "
                    f"лимит на минута {fetcher.minute_limit}, темпо до {1 / fetcher.interval:.1f}/сек, "
                    f"резерв за сайта {fetcher.floor} "
                    f"(max({RESERVE_FLOOR}, {RESERVE_FACTOR} × най-тежкия ден на сайта {peak} на {peak_day}))")
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
    except RateLimited as e:
        fetcher.log(f"ЛИМИТ НА МИНУТА/429 ({e.args[0]}) - спирам пуска; нужно е ръчно да се прегледа, "
                    f"оставащи днес {fetcher.remaining_day}")
    finally:
        fetcher.log(f"край на пуска: готови мачове {done_count}, заявки {fetcher.calls}, "
                    f"оставащи днес {fetcher.remaining_day}")
    return done_count


def main_guard():
    os.chdir(REPO)
    sys.path.insert(0, REPO)
