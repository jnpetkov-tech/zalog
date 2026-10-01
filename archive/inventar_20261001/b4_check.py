"""Б4: проверка на изтеглените набори - редове, мачове/елементи, дубликати по ключ, сурови файлове -> validation/api_teglene_20261001.csv"""
import os, sys, glob, csv, gzip
import pandas as pd
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); os.chdir(REPO)
SPECS = {  # набор: (файл-шаблон, ключ за дубликат (при снимки с fetched_at - включва я))
    "fixtures": ("{l}_fixtures.csv", ["fixture_id", "fetched_at"]),
    "injuries": ("{l}_injuries.csv", ["season", "fixture_id", "team_id", "player_id", "fetched_at"]),
    "standings": ("{l}_standings.csv", ["season", "group", "team_id", "fetched_at"]),
    "teams": ("{l}_teams.csv", ["season", "team_id", "fetched_at"]),
    "tops": ("{l}_tops.csv", ["season", "list", "rank", "fetched_at"]),
    "players_season": ("{l}_players_season.csv", ["season", "player_id", "team_id", "stat_league_id", "fetched_at"]),
    "team_stats": ("{l}_team_stats.csv", ["season", "team_id", "fetched_at"]),
    "lineups": ("{l}_lineups.csv", ["fixture_id", "team_id", "player_id", "starter"]),
    "stats_full": ("{l}_stats_full.csv", ["fixture_id", "team_id"]),
    "events_pre2024": ("{l}_events_pre2024.csv", ["fixture_id", "event_index"]),
    "player_stats_extra_pre2024": ("{l}_player_stats_extra_pre2024.csv", ["fixture_id", "team_id", "player_id", "player_name"]),
    "coachs": ("api_coachs.csv", ["query_team_id", "coach_id", "career_team_id", "start"]),
    "transfers": ("api_transfers.csv", ["query_team_id", "player_id", "date", "in_team_id", "out_team_id"]),
    "squads": ("api_squads.csv", ["team_id", "player_id", "fetched_at"]),
    "sidelined": ("api_sidelined.csv", ["player_id", "type", "start", "end"]),
    "predictions": ("{l}_predictions.csv", ["fixture_id"]),
    "profiles": ("api_profiles.csv", ["player_id"]),
    "trophies": ("api_trophies.csv", ["player_id", "league", "season", "place"]),
}
LG = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal", "champions_league", "europa_league", "conference_league",
      "france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
rows = []
for name, (pat, key) in SPECS.items():
    files = [pat.format(l=l) for l in LG] if "{l}" in pat else [pat]
    n = dup = nfix = 0; present = 0
    for f in files:
        if not os.path.exists(f) or os.path.getsize(f) == 0: continue
        present += 1
        d = pd.read_csv(f, low_memory=False)
        n += len(d); dup += int(d.duplicated(subset=[k for k in key if k in d.columns]).sum())
        if "fixture_id" in d: nfix += d.fixture_id.nunique()
    raws = glob.glob(f"api_raw/{'fixtures_full' if name in ('lineups','stats_full','events_pre2024','player_stats_extra_pre2024') else name}/*.jsonl.gz")
    rows.append([name, present, n, nfix or "", dup, len(raws)])
with open("validation/api_teglene_20261001.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["набор", "файлове", "редове", "мача", "дубликати_по_ключ", "сурови_gz"]); w.writerows(rows)
for r in rows: print(r)
