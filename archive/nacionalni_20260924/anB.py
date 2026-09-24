import json, glob, csv, statistics, re
from collections import Counter, defaultdict
FIN={"FT","AET","PEN","AWD","WO"}
rows=[]
for fn in sorted(glob.glob('raw_fx_*.json')):
    d=json.load(open(fn))
    for m in d['response']:
        rows.append(dict(fixture_id=m['fixture']['id'], league_id=m['league']['id'], league=m['league']['name'], season=m['league']['season'],
            round=m['league']['round'], date=m['fixture']['date'][:16], status=m['fixture']['status']['short'],
            home_id=m['teams']['home']['id'], home=m['teams']['home']['name'], away_id=m['teams']['away']['id'], away=m['teams']['away']['name'],
            hg=m['goals']['home'], ag=m['goals']['away'], neutral_venue_city=(m['fixture']['venue'] or {}).get('city')))
w=csv.DictWriter(open('/home/inkas/sportbg-predictor/validation/nacionalni_b_machove_20260924.csv','w',newline=''), fieldnames=list(rows[0]))
w.writeheader(); w.writerows(rows)
fin=[r for r in rows if r['status'] in FIN]
print('всички редове',len(rows),'завършени',len(fin))
# youth/women check in friendlies
odd=[r['home'] for r in rows if re.search(r'U\d\d| W$|Women|Olympic',r['home'])]
print('младежки/жени в списъка:',len(odd), Counter(odd).most_common(8))
by=defaultdict(Counter)
for r in fin: by[(r['league_id'],r['league'])][r['season']]+=1
tot={k:sum(v.values()) for k,v in by.items()}
for k in sorted(tot,key=lambda k:-tot[k]):
    teams=set()
    for r in fin:
        if r['league_id']==k[0]: teams|={r['home_id'],r['away_id']}
    print(k, dict(sorted(by[k].items())), 'общо',tot[k], 'отбори',len(teams))
# matches per team across ALL fetched comps, seniors only
senior=[r for r in fin if not re.search(r'U\d\d| W$|Women',r['home']+' '+r['away'])]
cnt=Counter()
for r in senior: cnt[r['home_id']]+=1; cnt[r['away_id']]+=1
v=sorted(cnt.values())
print('сеньорски завършени',len(senior),'отбори',len(cnt),'медиана мачове/отбор',statistics.median(v),'квартили',v[len(v)//4],v[3*len(v)//4])
# per year 2025-09-24..2026-09-24
last=[r for r in senior if r['date']>='2025-09-24']
c2=Counter()
for r in last: c2[r['home_id']]+=1; c2[r['away_id']]+=1
print('последните 12 мес: мачове',len(last),'отбори',len(c2),'медиана/отбор',statistics.median(c2.values()))
# which friendlies are senior national? count club-like names
names=Counter(r['home'] for r in fin if r['league_id']==10)
print('friendlies примерни:',names.most_common(15))
# per-team medians restricted to UEFA teams: teams appearing in NL
nl=set()
for r in fin:
    if r['league_id'] in (5,32,960): nl|={r['home_id'],r['away_id']}
vn=sorted(cnt[t] for t in nl)
print('европейски отбори',len(nl),'медиана',statistics.median(vn),'мин',vn[0],'макс',vn[-1])
json.dump({str(k):v for k,v in cnt.items()},open('teamcnt.json','w'))
