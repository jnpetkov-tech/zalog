"""Б1а: /leagues за 17-те лиги -> coverage на всеки сезон >= 2022 -> validation/api_pokritie_20261001.csv
(17 заявки; суровите отговори - api_raw/leagues/<лига>.json.gz, извън git)."""
import os, sys, json, gzip, csv
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO); os.chdir(REPO)
import backfill_common as bc
LEAGUE_IDS = {"bulgaria": 172, "england": 39, "germany": 78, "spain": 140, "france": 61, "champions_league": 2,
              "europa_league": 3, "conference_league": 848, "italy": 135, "portugal": 94, "france2": 62, "spain2": 141,
              "italy2": 136, "portugal2": 95, "bulgaria2": 173, "england2": 40, "germany2": 79}
FIX = ["events", "lineups", "statistics_fixtures", "statistics_players"]
TOP = ["standings", "players", "top_scorers", "top_assists", "top_cards", "injuries", "predictions", "odds"]
f = bc.Fetcher(os.path.join(REPO, "api_raw", "inventar_log.txt")); f.check_quota_now()
rows = []
for name, lid in LEAGUE_IDS.items():
    d = f.get("/leagues", {"id": lid})
    with gzip.open(f"api_raw/leagues/{name}.json.gz", "wt", encoding="utf-8") as g: json.dump(d, g, ensure_ascii=False)
    for item in d["response"]:
        for s in item["seasons"]:
            if s["year"] < 2022: continue
            c = s.get("coverage") or {}; fx = c.get("fixtures") or {}
            r = {"league": name, "league_id": lid, "season": s["year"], "start": s.get("start"), "end": s.get("end"), "current": s.get("current")}
            for k in FIX: r[k] = fx.get(k)
            for k in TOP: r[k] = c.get(k)
            rows.append(r)
out = "validation/api_pokritie_20261001.csv"
with open(out, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(len(rows), "реда; заявки", f.calls)
