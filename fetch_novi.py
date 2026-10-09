"""fetch_novi.py - купи и нови първенства, история 2022-2026 (ZADACHA_VSICHKO_OT_API, етап 2, 09.10.2026). САМО събиране, нищо не се показва.

Същата машина като fetch_api_sets.py (внася го и подменя в СВОЯ процес само списъка с лиги и пътищата - самият файл не е пипан):
правилата на backfill_common.py (резерв за сайта, спиране при 429, прекъсваемост, *_progress.txt), заявките през api_football._api_get.
Всичко се пише в папка novi/ ({ключ}_<набор>.csv, {ключ}_<набор>_progress.txt) - нито един файл, който чете живият код (те са в корена).
Суровите отговори: api_raw/<набор>/{ключ}_<сезон>.jsonl.gz (нови имена). /fixtures?ids= пише състави, пълна статистика, събития и
играчи за ВСИЧКИ сезони (в корена старите сезони отиват в *_pre2024 - тук няма жив код, който да ги чете).

ID-тата - от /leagues по държава (archive/vsichko_ot_api_20261009/leagues_inventar.json, суровото в api_raw/leagues/inventar_20261009.jsonl.gz).
Първенства: само тези, при които /leagues казва, че има статистика И състави (виж validation/novi_ligi_20261009.md).

crontab (inkas): 17,47 * * * *  flock -n /tmp/fetch_novi.lock venv/bin/python3 fetch_novi.py
Лог: novi/fetch_novi_log.txt.  Ръчно: venv/bin/python3 fetch_novi.py [--sets=a,b] [--limit=N] [--dry-run]
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import backfill_common as bc  # noqa: E402
import fetch_api_sets as fas  # noqa: E402

NOVI = os.path.join(ROOT, "novi")
os.makedirs(NOVI, exist_ok=True)

LEAGUE_IDS = {
    # първенства (статистика + състави по /leagues)
    "netherlands": 88, "netherlands2": 89, "turkey": 203, "turkey2": 204, "belgium": 144, "belgium2": 145,
    "scotland": 179, "greece": 197, "romania": 283,
    # купи
    "cup_bulgaria": 174, "cup_fa": 45, "cup_league": 48, "cup_copa_del_rey": 143, "cup_dfb": 81,
    "cup_coppa_italia": 137, "cup_coupe_de_france": 66, "cup_taca_portugal": 96,
}
SETS_ORDER = ["fixtures", "injuries", "fixtures_full", "teams", "standings", "coachs", "transfers", "squads", "profiles"]
RENAME = {"events_pre2024": "events", "player_stats_extra_pre2024": "player_stats_extra"}


def csv_path(name, league):
    name = RENAME.get(name, name)
    return os.path.join(NOVI, f"{league}_{name}.csv") if league else os.path.join(NOVI, f"api_{name}.csv")


def prog_path(name, league):
    return os.path.join(NOVI, f"{league}_{name}_progress.txt") if league else os.path.join(NOVI, f"api_{name}_progress.txt")


def finished_fixtures(league, min_season):
    """(fixture_id, season, date) на изиграните мачове от novi/{ключ}_fixtures.csv (последният ред на мач), най-старите първи."""
    p = csv_path("fixtures", league)
    if not os.path.exists(p) or not os.path.getsize(p):
        return []
    df = pd.read_csv(p, usecols=["fixture_id", "season", "date_utc", "status", "fetched_at"])
    df = df.sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    df = df[df["status"].isin(["FT", "AET", "PEN"]) & (df["season"] >= min_season)].sort_values("date_utc")
    return [(int(f), int(s), str(d)[:10]) for f, s, d in zip(df["fixture_id"], df["season"], df["date_utc"])]


_orig_build_jobs = fas.build_jobs


def build_jobs(name):
    if fas.SETS[name]["scope"] == "player":
        # профилите (възраст) на играчите от новите лиги, които още ги няма и в корена (api_profiles_progress.txt)
        done = set(fas.read_progress(prog_path(name, None))) | set(fas.read_progress(os.path.join(ROOT, f"api_{name}_progress.txt")))
        ids = set()
        for lg in LEAGUE_IDS:
            p = csv_path("player_stats_extra", lg)
            if os.path.exists(p) and os.path.getsize(p):
                ids |= set(pd.read_csv(p, usecols=["player_id"]).player_id.dropna().astype(int))
        return [(None, [{"key": str(i), "player": i} for i in sorted(ids) if str(i) not in done and i > 0])]
    return _orig_build_jobs(name)


# подмяна само в този процес
fas.LEAGUE_IDS = LEAGUE_IDS
fas.LEAGUES = list(LEAGUE_IDS)
fas.csv_path = csv_path
fas.prog_path = prog_path
fas.OLD_SEASON_BELOW = 10 ** 6
fas.COVERAGE_CSV = os.path.join(NOVI, "_няма.csv")
fas.LOG_PATH = os.path.join(NOVI, "fetch_novi_log.txt")
fas.build_jobs = build_jobs
bc.finished_fixtures = finished_fixtures
fas.SETS = {k: fas.SETS[k] for k in SETS_ORDER}


if __name__ == "__main__":
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
    sets = next((a.split("=")[1].split(",") for a in sys.argv if a.startswith("--sets=")), None)
    fas.main(only=sets, dry_run="--dry-run" in sys.argv, max_items=limit)
