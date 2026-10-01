"""Снимка на тегленията (ред/покритие/дубликати) по лига - пуска се ПРЕДИ и СЛЕД
догонването след Ultra плана (01.10.2026).
Употреба: venv/bin/python3 archive/teglene_ultra_20261001/snimka.py pered|sled
Пише validation/teglene_ultra_20261001_{pered|sled}.csv. Само четене на данните."""
import os, sys, csv
import pandas as pd
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO); os.chdir(REPO)
import backfill_common as bc

label = sys.argv[1]
KINDS = {  # вид: (csv, progress, ключ за дубликат)
    "events": ("{l}_events.csv", "{l}_events_progress.txt", ["fixture_id", "event_index"]),
    "players_main": ("{l}_player_stats.csv", "{l}_player_stats_progress.txt", ["fixture_id", "team", "player_id"]),
    "players_extra": ("{l}_player_stats_extra.csv", "{l}_player_stats_extra_progress.txt", ["fixture_id", "team_id", "player_id"]),
}
rows = []
for league in bc.MAIN_LEAGUES + bc.SECOND_DIVISIONS:
    universe = {f for f, _, _ in bc.finished_fixtures(league, 2024)}
    for kind, (c, p, key) in KINDS.items():
        csv_p, prog_p = c.format(l=league), p.format(l=league)
        done = bc.read_done(prog_p) & universe
        n_rows = dups = with_data = 0
        if os.path.exists(csv_p) and os.path.getsize(csv_p) > 0:
            df = pd.read_csv(csv_p, usecols=lambda x: x in key)
            n_rows = len(df)
            dups = int(df.duplicated(subset=key).sum())
            with_data = df["fixture_id"].nunique()
        with_data_in_scope = with_data  # мачовете с поне един ред
        rows.append({"league": league, "kind": kind, "fixtures_in_scope": len(universe),
                     "done": len(done), "left": len(universe) - len(done),
                     "with_data": with_data_in_scope,
                     "api_has_none": max(len(done) - with_data_in_scope, 0),
                     "csv_rows": n_rows, "duplicate_rows": dups})
out = os.path.join(REPO, "validation", f"teglene_ultra_20261001_{label}.csv")
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(out)
df = pd.DataFrame(rows)
print(df.groupby("kind")[["fixtures_in_scope", "done", "left", "with_data", "api_has_none", "csv_rows", "duplicate_rows"]].sum())
