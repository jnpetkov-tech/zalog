import csv, re, sqlite3, glob
from collections import Counter, defaultdict
import pandas as pd
R=list(csv.DictReader(open('validation/nacionalni_b_machove_20260924.csv')))
yth=lambda r: bool(re.search(r'U\d\d| W$|Women',r['home']+' '+r['away']))
days=[f'2026-09-{d:02d}' for d in range(24,31)]+[f'2026-10-{d:02d}' for d in range(1,4)]
c=sqlite3.connect('file:predictions.db?mode=ro',uri=True)
club=Counter(); 
for fid,ld in c.execute("select distinct fixture_id, substr(match_date,1,10) from predictions_snapshot"): club[ld]+=1
tab=defaultdict(Counter); youth=Counter()
for r in R:
    d=r['date'][:10]
    if d in days and r['status'] not in ('CANC','PST'):
        if yth(r): youth[d]+=1
        else: tab[d][r['league']]+=1
leagues=sorted({l for d in tab for l in tab[d]})
out=[]
for d in days:
    row=dict(date=d, club_matches_in_snapshot=club.get(d,0), national_senior_total=sum(tab[d].values()), national_youth_friendlies=youth[d])
    for l in leagues: row[l]=tab[d][l]
    out.append(row)
w=csv.DictWriter(open('validation/nacionalni_v_sledvashti_10_dni_20260924.csv','w',newline=''),fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
for r in out: print(r)
