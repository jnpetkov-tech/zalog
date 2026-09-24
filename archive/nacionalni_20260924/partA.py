import json, csv
d=json.load(open('raw_leagues_world.json'))
NAT = {1,4,5,6,7,9,10,19,21,22,23,24,25,28,29,30,31,32,33,34,35,36,37,480,535,536,766,804,805,806,807,808,849,858,859,860,913,916,960,1008,1038,1207,1222,1247,803,1045,919,911}
# 803 Asian Games / 480 Olympics / 919 Mediterranean / 911 SEA Games / 1045 Pan Am = U23 formally, marked separately
U23 = {480,803,919,911,1045}
rows=[]
for x in sorted(d['response'], key=lambda x:x['league']['id']):
    L=x['league']
    if L['id'] not in NAT: continue
    for s in x['seasons']:
        if s['year']<2021: continue
        c=s['coverage']; f=c['fixtures']
        rows.append(dict(id=L['id'], name=L['name'], u23=int(L['id'] in U23), season=s['year'], start=s['start'], end=s['end'], current=int(s['current']),
            cov_events=int(f['events']), cov_lineups=int(f['lineups']), cov_stats=int(f['statistics_fixtures']), cov_players=int(f['statistics_players']),
            cov_standings=int(c['standings']), cov_injuries=int(c['injuries']), cov_predictions=int(c['predictions']), cov_odds=int(c['odds'])))
w=csv.DictWriter(open('/home/inkas/sportbg-predictor/validation/nacionalni_a_turniri_20260924.csv','w',newline=''), fieldnames=list(rows[0]))
w.writeheader(); w.writerows(rows)
from collections import defaultdict
g=defaultdict(list)
for r in rows: g[(r['id'],r['name'])].append(r)
for (i,n),rs in g.items():
    yrs=[r['season'] for r in rs]
    print(i,n,'| сезони:',yrs,'| stats:',''.join(str(r['cov_stats']) for r in rs),'| odds:',''.join(str(r['cov_odds']) for r in rs), '|', rs[-1]['start'], rs[-1]['end'])
