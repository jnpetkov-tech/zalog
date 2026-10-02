"""fetch_history.py - история 2019-2021 за 17-те лиги (ZADACHA_RAZVITIE т.3, 02.10.2026, докато планът е Ultra - до 01.11.2026).

Самостоятелен, пуска се на ръка (nohup) и е прекъсваем (прогрес след всеки елемент). НЕ пише в нито един файл, който
чете живият код: всичко отива в hist/ (извън git), суровите отговори - в api_raw/history/. Сезон 2022 вече е
изтеглен от fetch_api_sets.py (fixtures, fixtures_full, събития/играчи в *_pre2024) - тук не се тегли пак.

Стъпки (по ред):
  1. coverage  - /leagues?id=  (1 заявка на лига) -> hist/coverage.csv (кои набори има API-то по сезон)
  2. fixtures  - /fixtures?league=&season=  -> hist/{лига}_fixtures.csv
  3. injuries  - /injuries?league=&season=  (само ако coverage.injuries) -> hist/{лига}_injuries.csv
  4. full      - /fixtures?ids=a-b-.. (до 20 приключили мача) -> hist/{лига}_lineups.csv, _stats_full.csv, _events.csv,
                 _player_stats_extra.csv (същите парсери и колони като живите файлове)
Спирачките (резерв за сайта, 429, минутен лимит) - от backfill_common.Fetcher.

Употреба: venv/bin/python3 fetch_history.py [--steps=coverage,fixtures,injuries,full] [--limit=N]
"""
import csv
import gzip
import json
import os
import sys
from datetime import datetime

import backfill_common as bc

bc.main_guard()
import fetch_api_sets as fa  # noqa: E402
import fetch_fixture_events as fe  # noqa: E402
import fetch_player_stats as fps  # noqa: E402

SEASONS = [2019, 2020, 2021]
HIST = os.path.join(bc.REPO, "hist")
RAW = os.path.join(bc.REPO, "api_raw", "history")
LOG_PATH = os.path.join(bc.REPO, "fetch_history_log.txt")
FINISHED = {"FT", "AET", "PEN"}
COV_KEYS = ["events", "lineups", "statistics_fixtures", "statistics_players", "injuries", "standings", "odds"]


def p(name):
    return os.path.join(HIST, name)


def raw(name, params, data):
    os.makedirs(RAW, exist_ok=True)
    with gzip.open(os.path.join(RAW, name + ".jsonl.gz"), "at", encoding="utf-8") as g:
        g.write(json.dumps({"params": params, "fetched_at": fa.now(), "data": data}, ensure_ascii=False) + "\n")


def step_coverage(f):
    out = p("coverage.csv")
    if os.path.exists(out):
        return 0
    rows = []
    for league, lid in fa.LEAGUE_IDS.items():
        data = f.get("/leagues", {"id": lid})
        if data is None:
            raise RuntimeError(f"coverage {league}: няма отговор")
        raw("leagues", {"id": lid}, data)
        for s in (data.get("response") or [{}])[0].get("seasons", []):
            if s.get("year") in SEASONS + [2022]:
                c = s.get("coverage") or {}
                fx = c.get("fixtures") or {}
                rows.append({"league": league, "league_id": lid, "season": s["year"], "start": s.get("start"), "end": s.get("end"),
                             "events": fx.get("events"), "lineups": fx.get("lineups"),
                             "statistics_fixtures": fx.get("statistics_fixtures"), "statistics_players": fx.get("statistics_players"),
                             "injuries": c.get("injuries"), "standings": c.get("standings"), "odds": c.get("odds")})
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return len(fa.LEAGUE_IDS)


def coverage():
    with open(p("coverage.csv"), encoding="utf-8") as fh:
        return {(r["league"], int(r["season"])): r for r in csv.DictReader(fh)}


def step_ls(f, name, ep, rows_fn, cov_key=None, limit=None):
    cov = coverage()
    n = 0
    for league, lid in fa.LEAGUE_IDS.items():
        prog = p(f"{league}_{name}_progress.txt")
        done = fa.read_progress(prog)
        for season in SEASONS:
            c = cov.get((league, season))
            if c is None or (cov_key and c.get(cov_key) != "True") or str(season) in done:
                continue
            params = {"league": lid, "season": season}
            data = f.get(ep, params)
            if data is None:
                continue
            raw(f"{name}_{league}_{season}", params, data)
            fa.write_rows(p(f"{league}_{name}.csv"), rows_fn({"league": league, "season": season}, data), fa.now())
            fa.mark(prog, season)
            n += 1
            if limit and n >= limit:
                return n
    return n


def finished_hist(league):
    path = p(f"{league}_fixtures.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        seen, out = set(), []
        for r in csv.DictReader(fh):
            if r["status"] in FINISHED and r["fixture_id"] not in seen:
                seen.add(r["fixture_id"])
                out.append((int(r["fixture_id"]), int(r["season"]), r["date_utc"]))
    return sorted(out, key=lambda x: x[2])


def step_full(f, limit=None):
    n = 0
    for league in fa.LEAGUE_IDS:
        prog = p(f"{league}_full_progress.txt")
        done = fa.read_progress(prog)
        todo = [x for x in finished_hist(league) if str(x[0]) not in done]
        for i in range(0, len(todo), fa.BATCH):
            chunk = todo[i:i + fa.BATCH]
            params = {"ids": "-".join(str(x[0]) for x in chunk)}
            data = f.get("/fixtures", params)
            if data is None:
                continue
            raw(f"full_{league}_{chunk[0][1]}", params, data)
            ts = fa.now()
            for x in data.get("response") or []:
                fid = x["fixture"]["id"]
                ctx = {"fixture": fid}
                fa.write_rows(p(f"{league}_lineups.csv"), fa.rows_lineups(ctx, {"response": x.get("lineups")}), ts, dedupe_by_fixture=True)
                fa.write_rows(p(f"{league}_stats_full.csv"), fa.rows_stats_gaps(ctx, {"response": x.get("statistics")}), ts,
                              dedupe_by_fixture=True)
                fa.write_rows(p(f"{league}_events.csv"), fe.parse(fid, {"response": x.get("events")}), None, dedupe_by_fixture=True)
                _, extra = fps.parse(fid, {"response": x.get("players")})
                fa.write_rows(p(f"{league}_player_stats_extra.csv"), extra, None, dedupe_by_fixture=True)
                fa.mark(prog, fid)
            n += 1
            if limit and n >= limit:
                return n
    return n


def main():
    os.makedirs(HIST, exist_ok=True)
    steps = ["coverage", "fixtures", "injuries", "full"]
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--steps="):
            steps = a.split("=", 1)[1].split(",")
        elif a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    f = bc.Fetcher(LOG_PATH)
    f.floor, _, _ = bc.live_reserve()
    f.check_quota_now()
    f.log(f"fetch_history старт {steps}: оставащи днес {f.remaining_day} от {f.daily_limit}, резерв {f.floor}")
    try:
        if "coverage" in steps:
            f.log(f"  coverage: {step_coverage(f)} заявки")
        if "fixtures" in steps:
            f.log(f"  fixtures: {step_ls(f, 'fixtures', '/fixtures', fa.rows_fixtures, None, limit)} заявки")
        if "injuries" in steps:
            f.log(f"  injuries: {step_ls(f, 'injuries', '/injuries', fa.rows_injuries, 'injuries', limit)} заявки")
        if "full" in steps:
            f.log(f"  full: {step_full(f, limit)} заявки")
    except (bc.QuotaExhausted, bc.RateLimited) as e:
        f.log(f"  спрях: {e!r}")
    f.log(f"fetch_history край: {f.calls} заявки, оставащи {f.remaining_day}")


if __name__ == "__main__":
    main()
