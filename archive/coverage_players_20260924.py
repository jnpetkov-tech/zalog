"""Покритие на статистиката по играчи по лига и сезон (ZADACHA_GOLQMA 2.5) ->
validation/igrachi_pokritie_20260924.csv. Мач "с данни" = има поне един ред в
{лига}_player_stats.csv; "проверен" = в *_progress.txt (питан в API-то)."""
import os, sys
import pandas as pd
sys.path.insert(0, "/home/inkas/sportbg-predictor")
os.chdir("/home/inkas/sportbg-predictor")
import backfill_common as bc
rows = []
for lg in bc.MAIN_LEAGUES + bc.SECOND_DIVISIONS:
    m = pd.read_csv(f"{lg}_merged_full.csv", usecols=["fixture_id", "season"])
    p = f"{lg}_player_stats.csv"
    have = set(pd.read_csv(p, usecols=["fixture_id"]).fixture_id) if os.path.exists(p) else set()
    done = bc.read_done(f"{lg}_player_stats_progress.txt")
    ex = f"{lg}_player_stats_extra.csv"
    have_x = set(pd.read_csv(ex, usecols=["fixture_id"]).fixture_id) if os.path.exists(ex) and os.path.getsize(ex) > 200 else set()
    for season, g in m.groupby("season"):
        if season < 2024:
            continue
        f = set(g.fixture_id)
        rows.append({"лига": lg, "сезон": season, "мачове": len(f), "проверени": len(f & done),
                     "с данни за играчи": len(f & have), "с удари (_extra)": len(f & have_x)})
d = pd.DataFrame(rows)
d.to_csv(sys.argv[1] if len(sys.argv) > 1 else "/dev/stdout", index=False)
