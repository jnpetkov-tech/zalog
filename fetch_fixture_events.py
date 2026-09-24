"""fetch_fixture_events.py - събитията в мача (/fixtures/events: минута на
гол, картон, смяна, изгонване, VAR), ZADACHA_GOLQMA.md етап 3.2 (24.09.2026).

Никога не са теглени досега. По образец на fetch_player_stats.py - същият
таван на квотата, същото продължаване (backfill_common.py), crontab на inkas
на всеки 30 минути.

Мачове: изиграните от сезон 2024 нататък (двата сезона на мерилото + текущия)
за всичките 17 лиги - първо основните 10, после вторите дивизии. Тръгва едва след като
fetch_player_stats.py е догонил основните 10 лиги (приоритет, обща дневна квота).

Файлове на лига (извън git):
- {лига}_events.csv - по един ред на събитие:
    fixture_id      мачът
    event_index     поредност в отговора на API-то (0, 1, 2...) - хронологично
    elapsed         минута (45, 90 - краят на полувремето/мача)
    extra           добавено време (45+2 -> elapsed=45, extra=2), празно ако няма
    team_id, team   отборът на събитието
    player_id, player    играчът (при смяна - ВЛИЗАЩИЯТ... виж бележката)
    assist_id, assist    при гол - асистенцията; при смяна - другият играч
    type            Goal / Card / subst / Var
    detail          Normal Goal / Own Goal / Penalty / Missed Penalty /
                    Yellow Card / Red Card / Second Yellow card /
                    Substitution 1..N / Goal cancelled / Penalty confirmed ...
    comments        свободен текст от API-то (напр. "Foul", "Tripping")
  Бележка за смените: API-Football не е последователен кой от двамата е в
  player и кой в assist - в повечето лиги player = излизащият, assist =
  влизащият; при анализ проверявай срещу минутите в *_player_stats.csv.
- {лига}_events_progress.txt - fixture_id-тата, които са готови.

Пускане на ръка: venv/bin/python3 fetch_fixture_events.py [--dry-run] [--limit=N]
"""
import csv
import os
import sys
from datetime import datetime, timedelta

import backfill_common as bc

bc.main_guard()

MIN_SEASON = 2024
RECENT_DAYS = 3
LOG_PATH = os.path.join(bc.REPO, "fetch_fixture_events_log.txt")
FIELDS = ["fixture_id", "event_index", "elapsed", "extra", "team_id", "team",
          "player_id", "player", "assist_id", "assist", "type", "detail", "comments"]


def parse(fixture_id, data):
    rows = []
    for i, e in enumerate(data.get("response") or []):
        t = e.get("time") or {}
        team = e.get("team") or {}
        player = e.get("player") or {}
        assist = e.get("assist") or {}
        rows.append({"fixture_id": fixture_id, "event_index": i,
                     "elapsed": t.get("elapsed"), "extra": t.get("extra"),
                     "team_id": team.get("id"), "team": team.get("name"),
                     "player_id": player.get("id"), "player": player.get("name"),
                     "assist_id": assist.get("id"), "assist": assist.get("name"),
                     "type": e.get("type"), "detail": e.get("detail"), "comments": e.get("comments")})
    return rows


def paths(league):
    base = os.path.join(bc.REPO, league)
    return f"{base}_events.csv", f"{base}_events_progress.txt"


def build_jobs():
    jobs, dates = [], {}
    for league in bc.MAIN_LEAGUES + bc.SECOND_DIVISIONS:
        _, prog = paths(league)
        done = bc.read_done(prog)
        fx = bc.finished_fixtures(league, MIN_SEASON)
        for f, _, d in fx:
            dates[f] = d
        jobs.append((league, [f for f, _, _ in fx if f not in done]))
    return jobs, dates


def player_catchup_pending():
    """Приоритет (24.09.2026): догонването на статистиката по играчи за 10-те основни
    лиги е по-важно - събитията чакат, докато то приключи (иначе изяждат общата
    дневна квота преди него)."""
    import fetch_player_stats as fps
    jobs, _ = fps.build_jobs()
    return sum(len(todo) for league, todo, mode in jobs if mode == "both" and league in bc.MAIN_LEAGUES)


def main(dry_run=False, max_items=None):
    fetcher = bc.Fetcher(LOG_PATH)
    pending = player_catchup_pending()
    if pending and not dry_run and max_items is None:
        fetcher.log(f"чакам: догонването по играчи (10 основни лиги) има още {pending} мача - пропускам пуска")
        return
    jobs, dates = build_jobs()
    fetcher.log(f"опашка: {dict((l, len(t)) for l, t in jobs)}")
    if dry_run:
        return
    recent_cut = (datetime.now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")

    def process_one(league, fixture_id):
        data = fetcher.get("/fixtures/events", {"fixture": fixture_id})
        if data is None:
            return False
        rows = parse(fixture_id, data)
        if not rows and str(dates.get(fixture_id, ""))[:10] >= recent_cut:
            fetcher.log(f"  {league} {fixture_id}: още няма събития (скорошен мач) - пак по-късно")
            return False
        if not rows:
            fetcher.log(f"  {league} {fixture_id}: API-то няма събития - отбелязан като готов")
        out, prog = paths(league)
        new = not os.path.exists(out) or os.path.getsize(out) == 0
        with open(out, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerows(rows)
        with open(prog, "a") as f:
            f.write(f"{fixture_id}\n")
        return True

    bc.run_queue(fetcher, jobs, process_one, max_items=max_items)


if __name__ == "__main__":
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
    main(dry_run="--dry-run" in sys.argv, max_items=limit)
