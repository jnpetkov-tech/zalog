"""validation/zhivo_drive_20261001.py - ZADACHA_ZHIVO т.1/5: пуска compute_grouped_markets + top_picks върху предстоящите мачове от тестова layer_live база.
Употреба: python zhivo_drive_20261001.py <папка с кода> <0|1 = LAYER_LIVE> <изход.json>   (папката: живата или копие с пач; тестовата база - до скрипта: test_layer.db)
Само четене на живата система (не логва, не пише); тестовата layer_live база се прави с layer_live.refresh(horizon_h=720) върху scratch DB."""
import sys, os, json
srcdir, layer, out = sys.argv[1], sys.argv[2], sys.argv[3]
os.chdir(srcdir); sys.path.insert(0, srcdir)
import warnings; warnings.filterwarnings("ignore")
import config
import match_predictor_app as mpa
import system_tracker as st
import pandas as pd
SP = os.path.dirname(os.path.abspath(__file__))
patched = hasattr(mpa, "get_ft_lambdas_live")
if patched:
    import layer_live as ll
    ll.DB_PATH = os.path.join(SP, "test_layer.db"); ll.LOG_PATH = os.path.join(SP, "test_layer_live.log")
    config.LAYER_LIVE = (layer == "1")
import layer_shadow as ls
fx = ls.load_fixtures()
import sqlite3
ids = [r[0] for r in sqlite3.connect(os.path.join(SP, "test_layer.db")).execute("select fixture_id from layer_live order by fixture_id")]
fx = fx[fx["fixture_id"].isin(ids)].sort_values("ts")
res = {}
for r in fx.itertuples():
    league, home, away, fid = r.league, r.home, r.away, int(r.fixture_id)
    hi = ai = 0
    c = st.get_cached_injuries(fid)
    if c is not None: hi, ai, _ = c
    kw = {"fixture_id": fid} if patched else {}
    try:
        groups, extra = mpa.compute_grouped_markets(league, home, away, hi, ai, real_odds=None, **kw)
    except Exception as e:
        res[fid] = {"error": repr(e)}; continue
    if not groups: continue
    (teams, team_idx, ft_model, ht_model, h2_model, *_r) = mpa.get_models(league)
    from production_pipeline import predict_ht_ft
    import football_lib as fl
    lam, mu = extra[0], extra[1]
    lh, mh = fl.get_lambdas(ht_model, team_idx, home, away); l2, m2 = fl.get_lambdas(h2_model, team_idx, home, away)
    htft = predict_ht_ft(lh, mh, l2, m2)
    tp = {"layer": False}
    if patched:
        lam_, mu_, ver = mpa.get_ft_lambdas_live(fid, ft_model, team_idx, home, away, hi, ai)
        picks, _ = mpa.top_picks_with_code(lam_, mu_, home, away, htft, league, None, 8, ft_model.get("rho", 0.0), layer=ver is not None)
    else:
        lam_, mu_ = mpa.get_ft_lambdas(ft_model, team_idx, home, away, hi, ai)
        picks, _ = mpa.top_picks_with_code(lam_, mu_, home, away, htft, league, None, 8, ft_model.get("rho", 0.0))
    res[fid] = {"league": league, "home": home, "away": away, "lam": repr(lam), "mu": repr(mu),
                "groups": [[t, [[repr(x) if not isinstance(x, (str, type(None))) else x for x in it] for it in items]] for t, items, _h in groups],
                "picks": [[a, repr(b), c] for a, b, c in picks], "extra": [repr(extra[2]), repr(extra[3])]}
json.dump(res, open(out, "w"), ensure_ascii=False, indent=0, sort_keys=True)
print("fixtures", len(res), "errors", sum(1 for v in res.values() if "error" in v))
