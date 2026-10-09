"""features/leak_check_v2.py - проверка срещу изтичане за новите колони на features_table_v2 (ZADACHA_VSICHKO_OT_API, етап 1).

200 случайни мача (seed 42) от v2: новите признаци се смятат НАНОВО с данни, отрязани до началото на мача:
  build_features.truncate (резултати/състави само на мачове със ts < ts на мача; от самия мач - съставът), рейтинги само на мачове със
  ts < ts, трансфери с дата < ts, записи за извън игра със start < ts (краят им остава какъвто е в API-то - затова вариантът "с края"
  sid_* носи риск, който тази проверка НЕ хваща; виж отделния отчет за sidelined), възрастта - от датата на раждане.
Сравнение ТОЧНО (==, NaN==NaN, с допуск 1e-9 за плаваща запетая). Изход: validation/tablica_v2_iztichane_20261009.md.
Употреба: nice -n 19 venv/bin/python3 features/leak_check_v2.py [--procs 8]
"""
import bisect
import copy
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from features import build_features as bf  # noqa: E402
from features import build_features_v2 as v2  # noqa: E402

N_SAMPLE, SEED = 200, 42
S = TAB = None


def cut_sources(fid, ts):
    s2 = copy.copy(S)
    s2.raw = bf.truncate(S.raw, ts, fid)
    s2.recs = bf.team_match_records(s2.raw)
    s2.hist = bf.History(s2.recs)
    s2.p_ts, s2.p_cs = {}, {}
    for p, arr in S.p_ts.items():
        i = bisect.bisect_left(arr, ts)
        if i:
            s2.p_ts[p] = arr[:i]
            s2.p_cs[p] = S.p_cs[p][:i + 1]
    s2.t_ts, s2.t_v = {}, {}
    for t, arr in S.t_ts.items():
        i = bisect.bisect_left(arr, ts)
        if i:
            s2.t_ts[t], s2.t_v[t] = arr[:i], S.t_v[t][:i]
    s2.tr_in = {k: [x for x in v if x[0] < ts] for k, v in S.tr_in.items()}
    s2.tr_out = {k: [x for x in v if x[0] < ts] for k, v in S.tr_out.items()}
    s2.sid = {k: [x for x in v if x[0] < ts] for k, v in S.sid.items()}
    s2._usual_cache = {}
    return s2


def check(fid):
    ts = int(S.fx_by_id.loc[fid, "ts"])
    got = cut_sources(fid, ts).row(fid)
    want = TAB.loc[fid]
    bad = []
    for k, v in got.items():
        w = want[k]
        if (pd.isna(v) and pd.isna(w)) or (not pd.isna(v) and not pd.isna(w) and abs(float(v) - float(w)) < 1e-9):
            continue
        bad.append((k, w, v))
    return fid, bad


def main():
    global S, TAB
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 8
    TAB = pd.read_csv(v2.OUT, float_precision="round_trip").set_index("fixture_id")
    S = v2.Sources()
    rng = np.random.default_rng(SEED)
    ids = [int(x) for x in rng.choice(TAB.index.to_numpy(), N_SAMPLE, replace=False)]
    with Pool(procs) as pool:
        res = pool.map(check, ids)
    ok = sum(1 for _f, b in res if not b)
    bad_cols = {}
    for f, b in res:
        for k, w, v in b:
            bad_cols.setdefault(k, []).append((f, w, v))
    L = ["# Проверка срещу изтичане — нови признаци (features_table_v2) — 09.10.2026", "",
         f"Скрипт: `features/leak_check_v2.py`. {N_SAMPLE} случайни мача (seed {SEED}); новите колони смятани наново с данни, отрязани до "
         "началото на мача, и сравнени с таблицата.", "",
         f"**Резултат: {ok}/{N_SAMPLE} мача съвпадат напълно.**", ""]
    if bad_cols:
        L += ["| колона | разминавания | пример (мач, таблица, наново) |", "|---|---|---|"]
        for k, lst in sorted(bad_cols.items()):
            L.append(f"| {k} | {len(lst)} | {lst[0]} |")
    L += ["", "Ограничение: записите „извън игра“ (`sid_*`) са отрязани по `start`, но краят им (`end`) е такъв, какъвто API-то го връща днес "
          "— ако краят се попълва със закъснение, вариантът с края знае нещо от бъдещето, което тази проверка не може да види. Затова има и "
          "вариант само със start (`sidS_*`)."]
    out = "\n".join(L) + "\n"
    open(os.path.join(ROOT, "validation", "tablica_v2_iztichane_20261009.md"), "w", encoding="utf-8").write(out)
    print(out)


if __name__ == "__main__":
    main()
