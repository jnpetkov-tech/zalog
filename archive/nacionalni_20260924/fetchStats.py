import csv, re, random, json
from api import get
FIN={"FT","AET","PEN","AWD","WO"}
R=[r for r in csv.DictReader(open('/home/inkas/sportbg-predictor/validation/nacionalni_b_machove_20260924.csv')) if r['status'] in FIN]
yth=lambda r: bool(re.search(r'U\d\d| W$|Women',r['home']+' '+r['away']))
COMPS=['10','5','36','29','960','30','32']
rows=[]
for lid in COMPS:
    pool=sorted([r for r in R if r['league_id']==lid and not yth(r)], key=lambda r:r['fixture_id'])
    random.seed(20260924); smp=random.sample(pool,20)
    ids='-'.join(r['fixture_id'] for r in smp)
    d=get('/fixtures',{'ids':ids},f'stats_{lid}')
    for m in d['response']:
        st={}
        for side,tb in zip(('home','away'),m.get('statistics',[])[:2]):
            for s in tb.get('statistics',[]): st[(side,s['type'])]=s['value']
        def has(t): return int(st.get(('home',t)) is not None and st.get(('away',t)) is not None)
        rows.append(dict(fixture_id=m['fixture']['id'], league_id=lid, league=m['league']['name'], season=m['league']['season'], date=m['fixture']['date'][:10],
            home=m['teams']['home']['name'], away=m['teams']['away']['name'], has_any_stats=int(bool(st)),
            xg=has('expected_goals'), shots=has('Total Shots'), shots_on_goal=has('Shots on Goal'), possession=has('Ball Possession'), corners=has('Corner Kicks')))
w=csv.DictWriter(open('/home/inkas/sportbg-predictor/validation/nacionalni_b_statistika_izvadka_20260924.csv','w',newline=''), fieldnames=list(rows[0]))
w.writeheader(); w.writerows(rows)
from collections import defaultdict
g=defaultdict(list)
for r in rows: g[r['league']].append(r)
for k,v in g.items():
    print(f"{k:42s} n={len(v)} статистика {sum(r['has_any_stats'] for r in v)} xG {sum(r['xg'] for r in v)} удари {sum(r['shots'] for r in v)} владение {sum(r['possession'] for r in v)} корнери {sum(r['corners'] for r in v)}")
    # xG by season
    bys=defaultdict(lambda:[0,0])
    for r in v: bys[r['season']][0]+=1; bys[r['season']][1]+=r['xg']
    print('    xG по сезон (n, с xG):', dict(sorted(bys.items())))
