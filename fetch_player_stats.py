"""fetch_player_stats.py - статистика по играчи за всеки изигран мач
(/fixtures/players), ZADACHA_GOLQMA.md етапи 2 и 3.1 (24.09.2026).

Изваден от archive/ (там стоеше ръчен скрипт, спрял на 07.08.2026 -
никой не го пускаше). Сега тече от crontab на inkas на всеки 30 минути,
с таван на квотата и продължаване оттам, докъдето е стигнал (виж
backfill_common.py за правилата).

Файлове на лига (извън git, както и преди):
- {лига}_player_stats.csv - СЪЩИЯТ формат като преди (player_props.py го
  чете): fixture_id,team,player_name,player_id,minutes,position,goals,
  assists,yellow_cards,red_cards
- {лига}_player_stats_progress.txt - fixture_id-тата, които са готови
- {лига}_player_stats_extra.csv - НОВО, същите мачове с още полета от
  същия отговор (удари, удари в целта, резерва ли е, id на отбора...) -
  отделен файл, за да не се чупи горният формат
- {лига}_player_stats_extra_progress.txt

Ред на работа (приоритет):
1. десетте основни лиги, сезон 2024+ - догонване след 07.08 (Етап 2);
2. седемте втори дивизии, сезон 2024+ (Етап 3.1);
3. допълнителните полета (удари) за мачовете от т.1, теглени преди,
   когато удари не са се пазели.

Пускане на ръка: venv/bin/python3 fetch_player_stats.py [--dry-run] [--limit=N]
"""
import csv
import os
import sys
from datetime import datetime, timedelta

import backfill_common as bc

bc.main_guard()

MIN_SEASON = 2024
RECENT_DAYS = 3   # празен отговор за мач от последните дни = още не е попълнен, опитай пак
LOG_PATH = os.path.join(bc.REPO, "fetch_player_stats_log.txt")

MAIN_FIELDS = ["fixture_id", "team", "player_name", "player_id", "minutes",
               "position", "goals", "assists", "yellow_cards", "red_cards"]
EXTRA_FIELDS = ["fixture_id", "team_id", "team", "player_id", "player_name", "minutes", "substitute",
                "position", "shots_total", "shots_on", "goals", "assists", "passes_key",
                "dribbles_success", "tackles_total", "fouls_committed",
                "penalty_scored", "penalty_missed", "yellow_cards", "red_cards"]


def parse(fixture_id, data):
    main_rows, extra_rows = [], []
    for team_block in data.get("response") or []:
        team = team_block.get("team") or {}
        for p in team_block.get("players") or []:
            stats = p["statistics"][0] if p.get("statistics") else {}
            games = stats.get("games") or {}
            goals = stats.get("goals") or {}
            cards = stats.get("cards") or {}
            shots = stats.get("shots") or {}
            passes = stats.get("passes") or {}
            dribbles = stats.get("dribbles") or {}
            tackles = stats.get("tackles") or {}
            fouls = stats.get("fouls") or {}
            pen = stats.get("penalty") or {}
            player = p.get("player") or {}
            main_rows.append({
                "fixture_id": fixture_id, "team": team.get("name"),
                "player_name": player.get("name"), "player_id": player.get("id"),
                "minutes": games.get("minutes"), "position": games.get("position"),
                "goals": goals.get("total"), "assists": goals.get("assists"),
                "yellow_cards": cards.get("yellow"), "red_cards": cards.get("red"),
            })
            extra_rows.append({
                "fixture_id": fixture_id, "team_id": team.get("id"), "team": team.get("name"),
                "player_id": player.get("id"), "player_name": player.get("name"),
                "minutes": games.get("minutes"), "substitute": games.get("substitute"),
                "position": games.get("position"),
                "shots_total": shots.get("total"), "shots_on": shots.get("on"),
                "goals": goals.get("total"), "assists": goals.get("assists"),
                "passes_key": passes.get("key"), "dribbles_success": dribbles.get("success"),
                "tackles_total": tackles.get("total"), "fouls_committed": fouls.get("committed"),
                "penalty_scored": pen.get("scored"), "penalty_missed": pen.get("missed"),
                "yellow_cards": cards.get("yellow"), "red_cards": cards.get("red"),
            })
    return main_rows, extra_rows


def _append(path, fields, rows):
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def _mark(path, fixture_id):
    with open(path, "a") as f:
        f.write(f"{fixture_id}\n")


def paths(league):
    base = os.path.join(bc.REPO, league)
    return {"main": f"{base}_player_stats.csv", "main_progress": f"{base}_player_stats_progress.txt",
            "extra": f"{base}_player_stats_extra.csv",
            "extra_progress": f"{base}_player_stats_extra_progress.txt"}


def build_jobs():
    """[(league, [fixture_id...], mode)] по приоритет; mode 'both' пише двата
    CSV-та, 'extra' - само допълнителния (главният вече има мача)."""
    jobs = []
    dates = {}
    for group in (bc.MAIN_LEAGUES, bc.SECOND_DIVISIONS):
        for league in group:
            p = paths(league)
            done = bc.read_done(p["main_progress"])
            fx = bc.finished_fixtures(league, MIN_SEASON)
            for f, _, d in fx:
                dates[f] = d
            jobs.append((league, [f for f, _, _ in fx if f not in done], "both"))
    for league in bc.MAIN_LEAGUES:
        p = paths(league)
        done_main = bc.read_done(p["main_progress"])
        done_extra = bc.read_done(p["extra_progress"])
        fx = bc.finished_fixtures(league, MIN_SEASON)
        jobs.append((league, [f for f, _, _ in fx if f in done_main and f not in done_extra], "extra"))
    return jobs, dates


def main(dry_run=False, max_items=None):
    fetcher = bc.Fetcher(LOG_PATH)
    jobs, dates = build_jobs()
    summary = {}
    for league, todo, mode in jobs:
        summary.setdefault(mode, {})[league] = len(todo)
    fetcher.log(f"опашка: {summary}")
    if dry_run:
        return
    recent_cut = (datetime.now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    mode_of = {}

    def process_one(league_mode, fixture_id):
        league, mode = league_mode
        data = fetcher.get("/fixtures/players", {"fixture": fixture_id})
        if data is None:
            return False
        p = paths(league)
        main_rows, extra_rows = parse(fixture_id, data)
        if not main_rows and str(dates.get(fixture_id, ""))[:10] >= recent_cut:
            fetcher.log(f"  {league} {fixture_id}: още няма данни (скорошен мач) - пак по-късно")
            return False
        if not main_rows:
            fetcher.log(f"  {league} {fixture_id}: API-то няма статистика по играчи - отбелязан като готов")
        if mode == "both":
            _append(p["main"], MAIN_FIELDS, main_rows)
            _mark(p["main_progress"], fixture_id)
        _append(p["extra"], EXTRA_FIELDS, extra_rows)
        _mark(p["extra_progress"], fixture_id)
        return True

    bc.run_queue(fetcher, [((league, mode), todo) for league, todo, mode in jobs], process_one,
                 max_items=max_items)


if __name__ == "__main__":
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
    main(dry_run="--dry-run" in sys.argv, max_items=limit)
