"""Проверка: новият fit_goals_direct_covariate() с параметри по подразбиране = старият (lam/mu, 4 лиги)."""
import importlib.util, sys, os, time
import numpy as np, pandas as pd
ROOT="/home/inkas/sportbg-predictor"; sys.path.insert(0, ROOT); os.chdir(ROOT)
import football_lib as old
spec=importlib.util.spec_from_file_location("fl_new", sys.argv[1]); new=importlib.util.module_from_spec(spec); spec.loader.exec_module(new)
SET={"england": {"intercept": True, "tempo_mult": 3.0}, "germany": {"intercept": True, "tempo_mult": 3.0},
     "spain": {"intercept": True, "tempo_mult": 3.0}, "france": {"intercept": True, "tempo_mult": 1.0}}
out=[]
for lg, kw in SET.items():
    df=old.load_league_data(lg); teams,n,ti=old.get_team_index(df); ref=df["date"].max(); xi=old.LEAGUE_XI.get(lg, old.XI)
    for k in (kw, {}):
        t0=time.time(); a=old.fit_goals_direct_covariate(df, ref, ti, n, "home_injuries", "away_injuries", xi=xi, **k)
        b=new.fit_goals_direct_covariate(df, ref, ti, n, "home_injuries", "away_injuries", xi=xi, **k)
        fin=df.dropna(subset=["home_goals"]).tail(300)
        d=0.0
        for h,aw,hc,ac in zip(fin.home_team, fin.away_team, fin.home_injuries.fillna(0), fin.away_injuries.fillna(0)):
            l1,m1=old.get_lambdas_direct(a,ti,h,aw,hc,ac); l2,m2=new.get_lambdas_direct(b,ti,h,aw,hc,ac)
            d=max(d,abs(l1-l2),abs(m1-m2))
        same_x = all(np.array_equal(np.asarray(a[q]), np.asarray(b[q])) for q in ("attack","defence")) and a["home_adv"]==b["home_adv"] and a["beta_direct"]==b["beta_direct"]
        out.append(f"{lg} {k or 'без настройки'}: макс. разлика lam/mu {d:.2e}; параметрите бит по бит: {same_x}; rho нов {b['rho']}; {time.time()-t0:.0f}s")
        print(out[-1], flush=True)
open(sys.argv[2],"w").write("\n".join(out)+"\n")
