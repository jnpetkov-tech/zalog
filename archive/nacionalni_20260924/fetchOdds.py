import csv, json
from api import get
R={r['fixture_id']:r for r in csv.DictReader(open('/home/inkas/sportbg-predictor/validation/nacionalni_b_machove_20260924.csv'))}
calls=[('/odds',{'league':5,'season':2026,'page':1},'odds_5_p1'),('/odds',{'league':5,'season':2026,'page':2},'odds_5_p2'),
       ('/odds',{'league':10,'season':2026,'page':1},'odds_10_p1'),('/odds',{'league':36,'season':2027,'page':1},'odds_36_p1'),
       ('/odds',{'league':536,'season':2025,'page':1},'odds_536_p1'),
       ('/odds',{'fixture':1637929},'odds_fin_1637929'),('/odds',{'fixture':1537579},'odds_fin_1537579')]
rows=[]
for p,prm,name in calls:
    d=get(p,prm,name)
    if not d['response']:
        rows.append(dict(source=name,fixture_id=prm.get('fixture',''),league='',date='',home='',away='',status='',bookmakers=0,has_1x2=0,has_ou25=0,has_btts=0,n_bk_1x2=0,n_bk_ou25=0,n_bk_btts=0)); continue
    for x in d['response']:
        fid=str(x['fixture']['id']); m=R.get(fid,{})
        bk=x.get('bookmakers',[])
        def nb(pred): return sum(any(pred(b) for b in B['bets']) for B in bk)
        n1=nb(lambda b:b['name']=='Match Winner')
        n2=nb(lambda b:b['name']=='Goals Over/Under' and any(v['value']=='Over 2.5' for v in b['values']))
        n3=nb(lambda b:b['name']=='Both Teams Score')
        rows.append(dict(source=name,fixture_id=fid,league=x['league']['name'],date=x['fixture']['date'][:16],home=m.get('home','?'),away=m.get('away','?'),status=m.get('status','?'),
            bookmakers=len(bk),has_1x2=int(n1>0),has_ou25=int(n2>0),has_btts=int(n3>0),n_bk_1x2=n1,n_bk_ou25=n2,n_bk_btts=n3))
    print(name,'paging',d.get('paging'),'results',d.get('results'))
w=csv.DictWriter(open('/home/inkas/sportbg-predictor/validation/nacionalni_b_koeficienti_izvadka_20260924.csv','w',newline=''),fieldnames=list(rows[0]))
w.writeheader(); w.writerows(rows)
for r in rows: print(r['source'],r['date'],r['home'],'-',r['away'],r['status'],'bk',r['bookmakers'],'1x2/ou/btts',r['n_bk_1x2'],r['n_bk_ou25'],r['n_bk_btts'])
