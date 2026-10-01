"""fetch_api_sets.py - нови набори от API-Football, които досега не се пазеха (ТЕГЛЕНЕ3 Б4, 01.10.2026).
Опис на наборите и решението защо точно тези: validation/api_inventar_20261001.md.

Самостоятелен процес (не импортира match_predictor_app), по образец на fetch_player_stats.py: правилата на
backfill_common.py (резерв за сайта, спиране при 429, прекъсваемост, запис в *_progress.txt след всеки елемент).
Пуска се от crontab на inkas с flock. НЕ влиза в модела.

За всеки набор:
- СУРОВИ отговори: api_raw/<набор>/<лига>_<сезон>.jsonl.gz (или .../<кофа>.jsonl.gz за набори по играч/отбор) - по един
  JSON ред на заявка {"params","fetched_at","data"}; извън git.
- ПЛОСЪК CSV: {лига}_<набор>.csv (набори по лига/сезон/мач) или api_<набор>.csv (набори по играч/отбор); извън git.
  Всеки ред има fetched_at - наборите, които API-то връща "към днес" (standings, team_stats, players_season, tops, squads),
  са СНИМКА към този момент, не към датата на мача (виж колоната "към датата" в api_inventar).
- Прогрес: {лига}_<набор>_progress.txt / api_<набор>_progress.txt, ред "<ключ>\t<време>". Текущият сезон (CURRENT_SEASON) на
  наборите със снимки се тегли пак, ако е по-стар от REFRESH_DAYS; миналите сезони - веднъж.

Пускане на ръка: venv/bin/python3 fetch_api_sets.py [--sets=a,b] [--limit=N] [--dry-run]
"""
import csv
import gzip
import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

import backfill_common as bc
import fetch_fixture_events as fe
import fetch_player_stats as fps

bc.main_guard()

SEASONS = [2022, 2023, 2024, 2025, 2026]
CURRENT_SEASON = 2026
REFRESH_DAYS = 7
MIN_SEASON_FIXTURE_SETS = 2024      # predictions - същото като играчите и събитията
BATCH = 20                          # /fixtures?ids= приема до 20 мача на заявка
OLD_SEASON_BELOW = 2024             # събития/играчи от по-стари сезони отиват в отделни файлове (не в тези, които чете живият код)
RECENT_DAYS = 3
LOG_PATH = os.path.join(bc.REPO, "fetch_api_sets_log.txt")
COVERAGE_CSV = os.path.join(bc.REPO, "validation", "api_pokritie_20261001.csv")
FIELDS_JSON = os.path.join(bc.REPO, "validation", "api_probe_fields_20261001.json")
LEAGUE_IDS = {"bulgaria": 172, "england": 39, "germany": 78, "spain": 140, "france": 61, "champions_league": 2,
              "europa_league": 3, "conference_league": 848, "italy": 135, "portugal": 94, "france2": 62, "spain2": 141,
              "italy2": 136, "portugal2": 95, "bulgaria2": 173, "england2": 40, "germany2": 79}
LEAGUES = bc.MAIN_LEAGUES + bc.SECOND_DIVISIONS
MIN_FREE_GB = 20


def now():
    return datetime.now().isoformat(timespec="seconds")


def gp(d, path, default=""):
    """d["a"]["b"] по път "a.b" (липсващо/None -> default)."""
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return default if d is None else d


# ---------------------------------------------------------------- плоски редове по набор
def rows_fixtures(ctx, data):
    out = []
    for x in data.get("response") or []:
        fx, lg, tm, gl, sc = x["fixture"], x["league"], x["teams"], x["goals"], x["score"]
        out.append({"fixture_id": fx["id"], "league": ctx["league"], "season": lg.get("season"), "round": lg.get("round"),
                    "date_utc": fx.get("date"), "timestamp": fx.get("timestamp"), "referee": fx.get("referee"),
                    "venue_id": gp(fx, "venue.id"), "venue": gp(fx, "venue.name"), "city": gp(fx, "venue.city"),
                    "status": gp(fx, "status.short"), "elapsed": gp(fx, "status.elapsed"),
                    "home_id": gp(tm, "home.id"), "home": gp(tm, "home.name"), "away_id": gp(tm, "away.id"), "away": gp(tm, "away.name"),
                    "home_winner": gp(tm, "home.winner"), "home_goals": gl.get("home"), "away_goals": gl.get("away"),
                    "ht_home": gp(sc, "halftime.home"), "ht_away": gp(sc, "halftime.away"),
                    "ft_home": gp(sc, "fulltime.home"), "ft_away": gp(sc, "fulltime.away"),
                    "et_home": gp(sc, "extratime.home"), "et_away": gp(sc, "extratime.away"),
                    "pen_home": gp(sc, "penalty.home"), "pen_away": gp(sc, "penalty.away")})
    return out


def rows_standings(ctx, data):
    out = []
    for item in data.get("response") or []:
        for group in gp(item, "league.standings", []):
            for r in group:
                row = {"league": ctx["league"], "season": ctx["season"], "group": r.get("group"), "rank": r.get("rank"),
                       "team_id": gp(r, "team.id"), "team": gp(r, "team.name"), "points": r.get("points"),
                       "goals_diff": r.get("goalsDiff"), "form": r.get("form"), "status": r.get("status"),
                       "description": r.get("description"), "update": r.get("update")}
                for part in ("all", "home", "away"):
                    for k in ("played", "win", "draw", "lose"):
                        row[f"{part}_{k}"] = gp(r, f"{part}.{k}")
                    row[f"{part}_gf"] = gp(r, f"{part}.goals.for")
                    row[f"{part}_ga"] = gp(r, f"{part}.goals.against")
                out.append(row)
    return out


def rows_injuries(ctx, data):
    return [{"league": ctx["league"], "season": gp(x, "league.season"), "fixture_id": gp(x, "fixture.id"),
             "fixture_date": gp(x, "fixture.date"), "team_id": gp(x, "team.id"), "team": gp(x, "team.name"),
             "player_id": gp(x, "player.id"), "player": gp(x, "player.name"), "type": gp(x, "player.type"),
             "reason": gp(x, "player.reason")} for x in data.get("response") or []]


def rows_teams(ctx, data):
    return [{"league": ctx["league"], "season": ctx["season"], "team_id": gp(x, "team.id"), "team": gp(x, "team.name"),
             "code": gp(x, "team.code"), "country": gp(x, "team.country"), "founded": gp(x, "team.founded"),
             "national": gp(x, "team.national"), "venue_id": gp(x, "venue.id"), "venue": gp(x, "venue.name"),
             "city": gp(x, "venue.city"), "capacity": gp(x, "venue.capacity"), "surface": gp(x, "venue.surface")}
            for x in data.get("response") or []]


PLAYER_COLS = ["games.appearences", "games.lineups", "games.minutes", "games.number", "games.position", "games.rating",
               "games.captain", "substitutes.in", "substitutes.out", "substitutes.bench", "shots.total", "shots.on",
               "goals.total", "goals.conceded", "goals.assists", "goals.saves", "passes.total", "passes.key", "passes.accuracy",
               "tackles.total", "tackles.blocks", "tackles.interceptions", "duels.total", "duels.won", "dribbles.attempts",
               "dribbles.success", "dribbles.past", "fouls.drawn", "fouls.committed", "cards.yellow", "cards.yellowred",
               "cards.red", "penalty.won", "penalty.commited", "penalty.scored", "penalty.missed", "penalty.saved"]


def player_rows(league, season, data, extra=None):
    out = []
    for item in data.get("response") or []:
        pl = item.get("player") or {}
        for st in item.get("statistics") or [{}]:
            row = {"league": league, "season": season, "player_id": pl.get("id"), "player": pl.get("name"),
                   "age": pl.get("age"), "nationality": pl.get("nationality"), "height": pl.get("height"),
                   "weight": pl.get("weight"), "injured": pl.get("injured"),
                   "team_id": gp(st, "team.id"), "team": gp(st, "team.name"), "stat_league_id": gp(st, "league.id")}
            for c in PLAYER_COLS:
                row[c.replace(".", "_")] = gp(st, c)
            if extra: row.update(extra)
            out.append(row)
    return out


def rows_team_stats(ctx, data):
    r = data.get("response")
    if not r or isinstance(r, list):
        return []
    paths = [p for p in json.load(open(FIELDS_JSON, encoding="utf-8"))["/teams/statistics"]]
    row = {"league": ctx["league"], "season": ctx["season"], "team_id": gp(r, "team.id"), "team": gp(r, "team.name")}
    for p in paths:
        row[p] = gp(r, p)
    return [row]


def rows_lineups(ctx, data):
    out = []
    for t in data.get("response") or []:
        for kind, key in (("1", "startXI"), ("0", "substitutes")):
            for p in t.get(key) or []:
                pl = p.get("player") or {}
                out.append({"fixture_id": ctx["fixture"], "team_id": gp(t, "team.id"), "team": gp(t, "team.name"),
                            "formation": t.get("formation"), "coach_id": gp(t, "coach.id"), "coach": gp(t, "coach.name"),
                            "starter": kind, "player_id": pl.get("id"), "player": pl.get("name"), "number": pl.get("number"),
                            "pos": pl.get("pos"), "grid": pl.get("grid")})
    return out


def rows_predictions(ctx, data):
    r = (data.get("response") or [None])[0]
    if not r:
        return []
    raw_paths = json.load(open(FIELDS_JSON, encoding="utf-8"))["/predictions"]       # "[].predictions.winner.id"
    paths = [p[3:] for p in raw_paths if p.startswith("[].") and "[]" not in p[3:]]    # без списъците (h2h)
    row = {"fixture_id": ctx["fixture"]}
    for p in paths:
        row[p] = gp(r, p)
    return [row]


STAT_TYPES = ["Shots on Goal", "Shots off Goal", "Total Shots", "Blocked Shots", "Shots insidebox", "Shots outsidebox", "Fouls",
              "Corner Kicks", "Offsides", "Ball Possession", "Yellow Cards", "Red Cards", "Goalkeeper Saves", "Total passes",
              "Passes accurate", "Passes %", "expected_goals", "goals_prevented"]


def rows_stats_gaps(ctx, data):
    out = []
    for t in data.get("response") or []:
        vals = {x.get("type"): x.get("value") for x in t.get("statistics") or []}
        row = {"fixture_id": ctx["fixture"], "team_id": gp(t, "team.id"), "team": gp(t, "team.name")}
        for k in STAT_TYPES:
            row[k.replace(" ", "_").replace("%", "pct")] = vals.get(k, "")
        out.append(row)
    return out


def rows_sidelined(ctx, data):
    return [{"player_id": ctx["player"], "type": x.get("type"), "start": x.get("start"), "end": x.get("end")}
            for x in data.get("response") or []]


def rows_profiles(ctx, data):
    out = []
    for x in data.get("response") or []:
        p = x.get("player") or {}
        out.append({"player_id": p.get("id"), "player": p.get("name"), "firstname": p.get("firstname"), "lastname": p.get("lastname"),
                    "age": p.get("age"), "birth_date": gp(p, "birth.date"), "birth_place": gp(p, "birth.place"),
                    "birth_country": gp(p, "birth.country"), "nationality": p.get("nationality"), "height": p.get("height"),
                    "weight": p.get("weight"), "number": p.get("number"), "position": p.get("position")})
    return out


def rows_trophies(ctx, data):
    return [{"player_id": ctx["player"], "league": x.get("league"), "country": x.get("country"), "season": x.get("season"),
             "place": x.get("place")} for x in data.get("response") or []]


def rows_coachs(ctx, data):
    out = []
    for c in data.get("response") or []:
        for car in c.get("career") or [{}]:
            out.append({"query_team_id": ctx["team"], "coach_id": c.get("id"), "coach": c.get("name"), "age": c.get("age"),
                        "birth_date": gp(c, "birth.date"), "nationality": c.get("nationality"),
                        "career_team_id": gp(car, "team.id"), "career_team": gp(car, "team.name"),
                        "start": car.get("start"), "end": car.get("end")})
    return out


def rows_transfers(ctx, data):
    out = []
    for x in data.get("response") or []:
        for t in x.get("transfers") or []:
            out.append({"query_team_id": ctx["team"], "player_id": gp(x, "player.id"), "player": gp(x, "player.name"),
                        "date": t.get("date"), "type": t.get("type"), "in_team_id": gp(t, "teams.in.id"),
                        "in_team": gp(t, "teams.in.name"), "out_team_id": gp(t, "teams.out.id"), "out_team": gp(t, "teams.out.name")})
    return out


def rows_squads(ctx, data):
    out = []
    for x in data.get("response") or []:
        for p in x.get("players") or []:
            out.append({"team_id": gp(x, "team.id"), "team": gp(x, "team.name"), "player_id": p.get("id"),
                        "player": p.get("name"), "age": p.get("age"), "number": p.get("number"), "position": p.get("position")})
    return out


# ---------------------------------------------------------------- описание на наборите (ред = приоритет)
# scope: ls = лига+сезон; fx = мач; team = отбор (глобално); player = играч (глобално); ts = лига+сезон+отбор
SETS = {
    "fixtures":      dict(scope="ls", ep="/fixtures", params=lambda c: {"league": c["lid"], "season": c["season"]}, rows=rows_fixtures, cov=None, refresh=True),
    "injuries":      dict(scope="ls", ep="/injuries", params=lambda c: {"league": c["lid"], "season": c["season"]}, rows=rows_injuries, cov="injuries", refresh=True),
    "standings":     dict(scope="ls", ep="/standings", params=lambda c: {"league": c["lid"], "season": c["season"]}, rows=rows_standings, cov="standings", refresh=True),
    "teams":         dict(scope="ls", ep="/teams", params=lambda c: {"league": c["lid"], "season": c["season"]}, rows=rows_teams, cov=None, refresh=True),
    "tops":          dict(scope="ls", kind="tops", cov="top_scorers", refresh=True),
    "players_season": dict(scope="ls", kind="players_season", cov="players", refresh=True),
    "team_stats":    dict(scope="ts", ep="/teams/statistics", params=lambda c: {"league": c["lid"], "season": c["season"], "team": c["team"]}, rows=rows_team_stats, refresh=True),
    "coachs":        dict(scope="team", ep="/coachs", params=lambda c: {"team": c["team"]}, rows=rows_coachs),
    "transfers":     dict(scope="team", ep="/transfers", params=lambda c: {"team": c["team"]}, rows=rows_transfers),
    "squads":        dict(scope="team", ep="/players/squads", params=lambda c: {"team": c["team"]}, rows=rows_squads),
    "fixtures_full": dict(scope="batch", kind="batch"),    # /fixtures?ids=a-b-..(до 20): състави + пълна статистика (+ събития/играчи за 2022-23)
    "sidelined":     dict(scope="player", ep="/sidelined", params=lambda c: {"player": c["player"]}, rows=rows_sidelined),
    "predictions":   dict(scope="fx", ep="/predictions", params=lambda c: {"fixture": c["fixture"]}, rows=rows_predictions),
    "profiles":      dict(scope="player", ep="/players/profiles", params=lambda c: {"player": c["player"]}, rows=rows_profiles),
    "trophies":      dict(scope="player", ep="/trophies", params=lambda c: {"player": c["player"]}, rows=rows_trophies),
}


# ---------------------------------------------------------------- файлове
def csv_path(name, league):
    return os.path.join(bc.REPO, f"{league}_{name}.csv" if league else f"api_{name}.csv")


def prog_path(name, league):
    return os.path.join(bc.REPO, f"{league}_{name}_progress.txt" if league else f"api_{name}_progress.txt")


def read_progress(path):
    done = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if parts and parts[0]:
                    done[parts[0]] = parts[1] if len(parts) > 1 else ""
    return done


def mark(path, key):
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{key}\t{now()}\n")


def raw_append(name, fname, params, data):
    d = os.path.join(bc.REPO, "api_raw", name)
    os.makedirs(d, exist_ok=True)
    with gzip.open(os.path.join(d, fname + ".jsonl.gz"), "at", encoding="utf-8") as g:
        g.write(json.dumps({"params": params, "fetched_at": now(), "data": data}, ensure_ascii=False) + "\n")


_present = {}


def fixtures_in(path):
    if path not in _present:
        ids = set()
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, newline="", encoding="utf-8") as f:
                rd = csv.reader(f)
                header = next(rd, [])
                i = header.index("fixture_id") if "fixture_id" in header else None
                if i is not None:
                    ids = {r[i] for r in rd if len(r) > i}
        _present[path] = ids
    return _present[path]


def write_rows(path, rows, fetched_at, dedupe_by_fixture=False):
    if not rows:
        return
    if fetched_at:
        for r in rows:
            r["fetched_at"] = fetched_at
    if dedupe_by_fixture:
        present = fixtures_in(path)
        fid = str(rows[0]["fixture_id"])
        if fid in present:
            return
        present.add(fid)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    fields = list(rows[0].keys())
    if not new:
        with open(path, newline="", encoding="utf-8") as f:
            fields = next(csv.reader(f))
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def disk_ok():
    st = os.statvfs(bc.REPO)
    return st.f_bavail * st.f_frsize / 1e9 >= MIN_FREE_GB


# ---------------------------------------------------------------- универси (какво трябва да се тегли)
def coverage():
    cov = {}
    if os.path.exists(COVERAGE_CSV):
        df = pd.read_csv(COVERAGE_CSV)
        for r in df.to_dict("records"):
            cov[(r["league"], int(r["season"]))] = r
    return cov


def due(ts, season, refresh):
    if not ts:
        return True
    if refresh and season == CURRENT_SEASON:
        try:
            return datetime.now() - datetime.fromisoformat(ts) > timedelta(days=REFRESH_DAYS)
        except ValueError:
            return True
    return False


def build_jobs(name):
    """[(league_or_None, [item,...])]; item = dict с контекста на заявката (ключът е item["key"])."""
    s = SETS[name]
    scope = s["scope"]
    jobs = []
    cov = coverage()
    if scope == "ls":
        for league in LEAGUES:
            done = read_progress(prog_path(name, league))
            items = []
            for season in SEASONS:
                c = cov.get((league, season))
                if s.get("cov") and c is not None and str(c.get(s["cov"])) != "True":
                    continue
                key = str(season)
                if due(done.get(key), season, s.get("refresh")):
                    items.append({"key": key, "league": league, "lid": LEAGUE_IDS[league], "season": season})
            jobs.append((league, items))
    elif scope == "ts":
        for league in LEAGUES:
            tp = csv_path("teams", league)
            done = read_progress(prog_path(name, league))
            items = []
            if os.path.exists(tp):
                t = pd.read_csv(tp, usecols=["season", "team_id"]).drop_duplicates()
                for season, team in zip(t.season, t.team_id):
                    key = f"{int(season)}|{int(team)}"
                    if due(done.get(key), int(season), s.get("refresh")):
                        items.append({"key": key, "league": league, "lid": LEAGUE_IDS[league], "season": int(season), "team": int(team)})
            jobs.append((league, items))
    elif scope == "fx":
        for league in LEAGUES:
            done = read_progress(prog_path(name, league))
            items = [{"key": str(f), "league": league, "fixture": f, "season": sn, "date": d}
                     for f, sn, d in bc.finished_fixtures(league, MIN_SEASON_FIXTURE_SETS) if str(f) not in done]
            jobs.append((league, items))
    elif scope == "batch":
        for league in LEAGUES:
            done = read_progress(prog_path(name, league))
            by_season = {}
            for f, sn, d in bc.finished_fixtures(league, 0):
                if str(f) not in done:
                    by_season.setdefault(sn, []).append((f, d))
            items = []
            for sn, lst in sorted(by_season.items()):
                for i in range(0, len(lst), BATCH):
                    chunk = lst[i:i + BATCH]
                    items.append({"key": "-".join(str(f) for f, _ in chunk), "league": league, "season": sn,
                                  "fixtures": [f for f, _ in chunk], "dates": {f: str(d) for f, d in chunk}})
            jobs.append((league, items))
    elif scope == "team":
        done = read_progress(prog_path(name, None))
        seen, items = set(), []
        for league in LEAGUES:
            tp = csv_path("teams", league)
            if os.path.exists(tp):
                for team in pd.read_csv(tp, usecols=["team_id"]).team_id.dropna().astype(int).unique():
                    if team not in seen:
                        seen.add(team)
                        if str(team) not in done:
                            items.append({"key": str(team), "team": int(team)})
        jobs.append((None, items))
    elif scope == "player":
        done = read_progress(prog_path(name, None))
        ids = set()
        for league in LEAGUES:
            p = os.path.join(bc.REPO, f"{league}_player_stats_extra.csv")
            if os.path.exists(p) and os.path.getsize(p) > 0:
                ids |= set(pd.read_csv(p, usecols=["player_id"]).player_id.dropna().astype(int))
        items = [{"key": str(i), "player": i} for i in sorted(ids) if str(i) not in done and i > 0]
        jobs.append((None, items))
    return jobs


# ---------------------------------------------------------------- изпълнение на един елемент
def process(fetcher, name, league, item):
    s = SETS[name]
    scope = s["scope"]
    kind = s.get("kind")
    ts = now()
    if kind == "batch":
        params = {"ids": item["key"]}
        data = fetcher.get("/fixtures", params)
        if data is None:
            return False
        raw_append(name, f"{league}_{item['season']}", params, data)
        recent_cut = (datetime.now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
        for x in data.get("response") or []:
            fid = x["fixture"]["id"]
            if not x.get("lineups") and not x.get("statistics") and item["dates"].get(fid, "")[:10] >= recent_cut:
                continue                       # скорошен мач без данни - пак по-късно
            ctx = {"fixture": fid}
            write_rows(csv_path("lineups", league), rows_lineups(ctx, {"response": x.get("lineups")}), ts, dedupe_by_fixture=True)
            write_rows(csv_path("stats_full", league), rows_stats_gaps(ctx, {"response": x.get("statistics")}), ts, dedupe_by_fixture=True)
            if item["season"] < OLD_SEASON_BELOW:
                ev = fe.parse(fid, {"response": x.get("events")})
                write_rows(csv_path("events_pre2024", league), ev, None, dedupe_by_fixture=True)
                _, extra = fps.parse(fid, {"response": x.get("players")})
                write_rows(csv_path("player_stats_extra_pre2024", league), extra, None, dedupe_by_fixture=True)
            mark(prog_path(name, league), fid)
        got = {x["fixture"]["id"] for x in data.get("response") or []}
        return bool(got)
    if kind == "players_season":
        all_rows, pages, page = [], 1, 1
        while page <= pages:
            params = {"league": item["lid"], "season": item["season"], "page": page}
            data = fetcher.get("/players", params)
            if data is None:
                return False
            raw_append(name, f"{league}_{item['season']}", params, data)
            pages = int((data.get("paging") or {}).get("total") or 1)
            all_rows += player_rows(league, item["season"], data)
            page += 1
        write_rows(csv_path(name, league), all_rows, ts)
        mark(prog_path(name, league), item["key"])
        return True
    if kind == "tops":
        all_rows = []
        for lst, ep in (("scorers", "topscorers"), ("assists", "topassists"), ("yellow", "topyellowcards"), ("red", "topredcards")):
            params = {"league": item["lid"], "season": item["season"]}
            data = fetcher.get(f"/players/{ep}", params)
            if data is None:
                return False
            raw_append(name, f"{league}_{item['season']}_{lst}", params, data)
            for rank, r in enumerate(player_rows(league, item["season"], data, {"list": lst}), 1):
                r["rank"] = rank
                all_rows.append(r)
        write_rows(csv_path(name, league), all_rows, ts)
        mark(prog_path(name, league), item["key"])
        return True
    params = s["params"](item)
    data = fetcher.get(s["ep"], params)
    if data is None:
        return False
    rows = s["rows"](item, data)
    if scope == "fx" and not (data.get("response")) and str(item.get("date", ""))[:10] >= (datetime.now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d"):
        fetcher.log(f"  {name} {league} {item['key']}: още няма данни (скорошен мач) - пак по-късно")
        return False
    if scope in ("ls", "ts", "fx"):
        raw_name = f"{league}_{item['season']}"
    elif scope == "team":
        raw_name = f"teams_{item['team'] // 500}"
    else:
        raw_name = f"players_{item['player'] // 2000}"
    raw_append(name, raw_name, params, data)
    write_rows(csv_path(name, league if scope in ("ls", "ts", "fx") else None), rows, ts, dedupe_by_fixture=(scope == "fx"))
    mark(prog_path(name, league if scope in ("ls", "ts", "fx") else None), item["key"])
    return True


def main(only=None, dry_run=False, max_items=None):
    fetcher = bc.Fetcher(LOG_PATH)
    names = [n for n in SETS if only is None or n in only]
    total = {}
    plan = []
    for n in names:
        jobs = build_jobs(n)
        total[n] = sum(len(items) for _, items in jobs)
        plan.append((n, jobs))
    fetcher.log(f"опашка (елементи): {total}")
    if dry_run:
        return
    done = 0
    for n, jobs in plan:
        if n != names[0]:
            jobs = build_jobs(n)          # наборите по отбор/сезон зависят от предишните - прочита се наново
        if not any(items for _, items in jobs):
            continue
        if not disk_ok():
            fetcher.log(f"под {MIN_FREE_GB} GB свободни - спирам")
            return
        fetcher.log(f"=== набор {n} ===")
        by_key = {}
        flat = []
        for league, items in jobs:
            flat.append((league, [it["key"] for it in items]))
            for it in items:
                by_key[(league, it["key"])] = it
        left = None if max_items is None else max_items - done
        if left is not None and left <= 0:
            return
        done += bc.run_queue(fetcher, flat, lambda lg, k, n=n, by_key=by_key: process(fetcher, n, lg, by_key[(lg, k)]), max_items=left)
        if fetcher.rate_limited or fetcher.time_left() <= 0 or (fetcher.remaining_day is not None and fetcher.remaining_day < fetcher.floor):
            return


if __name__ == "__main__":
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
    sets = next((a.split("=")[1].split(",") for a in sys.argv if a.startswith("--sets=")), None)
    main(only=sets, dry_run="--dry-run" in sys.argv, max_items=limit)
