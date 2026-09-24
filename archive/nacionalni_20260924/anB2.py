import csv, re, statistics
from collections import Counter, defaultdict
from datetime import datetime
FIN={"FT","AET","PEN","AWD","WO"}
R=[r for r in csv.DictReader(open('/home/inkas/sportbg-predictor/validation/nacionalni_b_machove_20260924.csv')) if r['status'] in FIN]
yth=lambda r: bool(re.search(r'U\d\d| W$|Women',r['home']+' '+r['away']))
fr=[r for r in R if r['league_id']=='10']
print('friendlies завършени',len(fr),'от тях младежки',sum(yth(r) for r in fr))
for s in ['2022','2023','2024','2025','2026']:
    x=[r for r in fr if r['season']==s]; print(' ',s,'сеньори',sum(not yth(r) for r in x),'младежи',sum(yth(r) for r in x))
S=[r for r in R if not yth(r)]
print('\nпо турнир (сеньори): мачове, голове/мач, равни %, |разлика|>=3 %, домакин печели %')
g=defaultdict(list)
for r in S: g[r['league']].append(r)
out=[]
for k,v in sorted(g.items(), key=lambda kv:-len(kv[1])):
    gl=[int(r['hg'])+int(r['ag']) for r in v]; gd=[abs(int(r['hg'])-int(r['ag'])) for r in v]
    hw=sum(int(r['hg'])>int(r['ag']) for r in v); dr=sum(int(r['hg'])==int(r['ag']) for r in v)
    o25=sum(x>2 for x in gl); btts=sum(int(r['hg'])>0 and int(r['ag'])>0 for r in v)
    print(f'{k:45s} {len(v):5d} {statistics.mean(gl):.2f}  равни {100*dr/len(v):.0f}%  разл>=3 {100*sum(x>=3 for x in gd)/len(v):.0f}%  дом {100*hw/len(v):.0f}%  над2.5 {100*o25/len(v):.0f}% двата {100*btts/len(v):.0f}%')
# gaps between matches per team (senior, all comps)
dates=defaultdict(list)
for r in S:
    d=datetime.fromisoformat(r['date'])
    dates[r['home_id']].append(d); dates[r['away_id']].append(d)
gaps=[]
for t,ds in dates.items():
    ds.sort(); gaps+= [(b-a).days for a,b in zip(ds,ds[1:])]
gaps.sort()
print('\nпаузи между мачове на отбор (дни): медиана',statistics.median(gaps),'75%',gaps[3*len(gaps)//4],'90%',gaps[9*len(gaps)//10], '% >60 дни', round(100*sum(g>60 for g in gaps)/len(gaps)))
# matches per team 2024-09-24..2026-09-24 (2 years)
c=Counter()
for r in S:
    if r['date']>='2024-09-24': c[r['home_id']]+=1; c[r['away_id']]+=1
v=sorted(c.values()); print('последните 2 години: отбори',len(v),'медиана',statistics.median(v),'25%',v[len(v)//4],'75%',v[3*len(v)//4])
