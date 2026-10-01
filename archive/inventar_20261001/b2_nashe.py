"""Б2: какво имаме локално - по набор: редове, мачове, период, колони -> validation/api_nashe_20261001.csv"""
import os, sys, glob, csv
import pandas as pd
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(REPO); sys.path.insert(0, REPO)
import backfill_common as bc
LG = bc.MAIN_LEAGUES + bc.SECOND_DIVISIONS
out = []
def add(name, pattern, per_league=True, fixcol="fixture_id", datecol=None, teamcols=None):
    for l in (LG if per_league else [None]):
        f = pattern.format(l=l)
        if not os.path.exists(f) or os.path.getsize(f) == 0: out.append([name, l, f, 0, 0, "", "", ""]); continue
        d = pd.read_csv(f, low_memory=False)
        n_fx = d[fixcol].nunique() if fixcol in d else ""
        per = ""
        if datecol and datecol in d: per = f"{str(d[datecol].min())[:10]}..{str(d[datecol].max())[:10]}"
        elif "season" in d: per = f"сезон {d.season.min()}..{d.season.max()}"
        out.append([name, l, f, len(d), n_fx, per, len(d.columns), ";".join(d.columns)])
add("мачове (merged_full: резултат+статистика на мача, 1 ред/мач)", "{l}_merged_full.csv", datecol="date")
add("статистика по отбор (match_statistics, 1 ред/отбор/мач)", "{l}_match_statistics.csv")
add("стара история (full_history: само резултат)", "{l}_full_history.csv", datecol="date")
add("играчи по мач (основен)", "{l}_player_stats.csv")
add("играчи по мач (extra: удари, подавания...)", "{l}_player_stats_extra.csv")
add("събития в мача", "{l}_events.csv")
add("контузии (4 лиги x 3 сезона)", "injuries_all_leagues.csv", per_league=False)
add("контузии УЕФА", "injuries_uefa.csv", per_league=False)
add("футбол-дата.ко.ук коефициенти (отваряне+затваряне)", "{l}_with_odds.csv", datecol="date")
add("национални отбори (мачове)", "nationals_merged_full.csv", per_league=False, datecol="date")
with open("validation/api_nashe_20261001.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["набор", "лига", "файл", "редове", "мача", "период", "колони_брой", "колони"]); w.writerows(out)
df = pd.DataFrame(out, columns=["набор", "лига", "файл", "редове", "мача", "период", "бр", "кол"])
print(df.groupby("набор")[["редове"]].sum().to_string())
print(df[df.набор.str.startswith("мачове")][["лига", "редове", "период"]].to_string(index=False))
