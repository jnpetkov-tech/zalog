import sys, json, random, os
libdir = sys.argv[1]; out = sys.argv[2]; enable = sys.argv[3] == "1"
if libdir != "live":
    sys.path.insert(0, libdir)
sys.path.insert(1, "/home/inkas/sportbg-predictor")
os.chdir("/home/inkas/sportbg-predictor")
import prediction_policy as policy
if enable:
    policy.CALIBRATION_ENABLED = True
import match_predictor_app as mpa
print(mpa.__file__, policy.__file__, file=sys.stderr)
random.seed(1)
res = {}
for lg in ["bulgaria", "england", "italy", "germany2", "champions_league"]:
    teams, team_idx, ft, *_ = mpa.get_models(lg)
    for _ in range(12):
        h, a = random.sample(teams, 2)
        g, _x = mpa.compute_grouped_markets(lg, h, a, 1, 2, real_odds=None)
        rows = {r[3]: r[1] for _t, items, _h in g for r in items if len(r) > 3}
        lam, mu = mpa.get_ft_lambdas(ft, team_idx, h, a, 1, 2)
        picks, _u = mpa.top_picks_with_code(lam, mu, h, a, {"1/1": 0.3, "X/X": 0.2}, lg, market_odds=None, n=8, rho=ft.get("rho", 0.0))
        res[f"{lg}|{h}|{a}"] = {"groups": rows, "picks": [[p[2], p[1]] for p in picks]}
json.dump(res, open(out, "w"))
