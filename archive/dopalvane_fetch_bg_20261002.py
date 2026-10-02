"""archive/dopalvane_fetch_bg_20261002.py - ZADACHA_DOPALVANE т.2.2 (02.10.2026), еднократно.

Изиграните (FT) мачове на bulgaria от сезоните 2022-2025, които липсват в bulgaria_merged_full.csv, нямат статистика
никъде локално (bulgaria_stats_full.csv и api_raw/fixtures_full покриват само мачовете, които вече са във файла).
Тегли ги през /fixtures?ids= (до 20 мача на заявка) с общия Fetcher (backfill_common - резерв за сайта, темпо, спиране
при 429). Суровите отговори -> api_raw/fixtures_full/bulgaria_<сезон>.jsonl.gz (същия формат като fetch_api_sets.py).
Нищо друго не пише. Мачовете от 2020-2021 са в hist/ (статистика в hist/bulgaria_stats_full.csv) - не се теглят.
Употреба: venv/bin/python3 archive/dopalvane_fetch_bg_20261002.py [--dry-run]
"""
import gzip
import json
import os
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import pandas as pd  # noqa: E402

import backfill_common as bc  # noqa: E402

LEAGUE = "bulgaria"
SEASONS = (2022, 2023, 2024, 2025)
BATCH = 20
LOG = os.path.join(REPO, "dopalvane_fetch_log.txt")


def missing_ids():
    m = pd.read_csv(f"{LEAGUE}_merged_full.csv", low_memory=False)
    fx = pd.read_csv(f"{LEAGUE}_fixtures.csv", low_memory=False).sort_values("fetched_at")
    fx = fx.drop_duplicates("fixture_id", keep="last")
    fx = fx[(fx["status"] == "FT") & fx["season"].isin(SEASONS) & ~fx["fixture_id"].isin(set(m["fixture_id"]))]
    done = set()
    for s in SEASONS:
        p = os.path.join(REPO, "api_raw", "fixtures_full", f"{LEAGUE}_{s}.jsonl.gz")
        if os.path.exists(p):
            for line in gzip.open(p, "rt", encoding="utf-8"):
                for x in json.loads(line)["data"].get("response") or []:
                    if x.get("statistics"):
                        done.add(x["fixture"]["id"])
    fx = fx[~fx["fixture_id"].isin(done)]
    return fx.sort_values(["season", "fixture_id"])[["fixture_id", "season"]]


def main():
    dry = "--dry-run" in sys.argv
    todo = missing_ids()
    batches = []
    for s, g in todo.groupby("season"):
        ids = g["fixture_id"].astype(int).tolist()
        batches += [(int(s), ids[i:i + BATCH]) for i in range(0, len(ids), BATCH)]
    print(f"{len(todo)} мача, {len(batches)} заявки", flush=True)
    if dry or not batches:
        return
    f = bc.Fetcher(LOG)
    f.floor = bc.live_reserve()[0]
    f.log(f"остават днес {f.check_quota_now()}, резерв {f.floor}; {len(batches)} заявки")
    d = os.path.join(REPO, "api_raw", "fixtures_full")
    got = 0
    for season, ids in batches:
        params = {"ids": "-".join(map(str, ids))}
        data = f.get("/fixtures", params)
        if data is None:
            f.log(f"  без отговор за {season} {ids[0]}..")
            continue
        with gzip.open(os.path.join(d, f"{LEAGUE}_{season}.jsonl.gz"), "at", encoding="utf-8") as g:
            g.write(json.dumps({"params": params, "fetched_at": datetime.now().isoformat(timespec="seconds"),
                                "data": data}, ensure_ascii=False) + "\n")
        got += len(data.get("response") or [])
    f.log(f"готово: {f.calls} заявки, {got} мача")


if __name__ == "__main__":
    main()
