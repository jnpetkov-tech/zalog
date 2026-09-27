"""
validation/otbrana_20260927_sprawka.py - СПРАВКА, добавена СЛЕД резултатите на
otbrana_20260927.py (не е настройка за избор, не променя решението).
Въпрос: ако вместо коефициент, фитван всяка седмица по лига, се ползва ЕДНО общо число
b за всички лиги (log на допуснатите += b * брой отсъстващи от тройката), колко се печели
в най-добрия случай? Сегашният модел (контролът) * exp(b * def_abs); b от 0.02 до 0.08.
b=0.04 ~ ефектът от теста с голмайстора (+4% на отсъстващ). Изход: _sprawka.csv.
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)
import kalibraciq_xg_20260923 as kx  # noqa: E402
import otbrana_20260927 as O  # noqa: E402

res = pd.read_pickle(O.RES_PKL)
base = res[res.setting == O.SETTINGS[0][0]].sort_values(["league", "fixture_id"]).reset_index(drop=True)
F = pd.read_pickle(O.OFE.OUT_PKL)
names = {}
for lg in O.LEAGUES:
    m = pd.read_csv(f"{lg}_merged_full.csv", usecols=["fixture_id", "home_team", "away_team"])
    names.update({int(f): (h, a) for f, h, a in zip(m.fixture_id, m.home_team, m.away_team)})
d = F.set_index(["fixture_id", "team"])["def_abs"].to_dict()
dh = np.array([d.get((f, names[f][0]), 0.0) for f in base.fixture_id])
da = np.array([d.get((f, names[f][1]), 0.0) for f in base.fixture_id])
early = (pd.to_datetime(base.date) < kx.CUT).to_numpy()
_, _, b0 = O.evaluate(base)
rows = []
for b in (0.02, 0.03, 0.04, 0.05, 0.06, 0.08):
    t = base.copy()
    t["lam"] = base.lam * np.exp(b * da)
    t["mu"] = base.mu * np.exp(b * dh)
    _, _, br = O.evaluate(t)
    for half, m in (("ранна", early), ("късна", ~early)):
        c = kx.ci(br[m], b0[m])
        rows.append({"b": b, "половина": half, "разлика": c[0], "lo": c[1], "hi": c[2]})
R = pd.DataFrame(rows)
R.round(6).to_csv("validation/otbrana_20260927_sprawka.csv", index=False)
print(R.round(5).to_string(index=False))
