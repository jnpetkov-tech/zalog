"""validation/zhivo_sravnenie_20261001.py - ZADACHA_ZHIVO т.5: стар (ядро) срещу нов (слой) изход върху предстоящите мачове.
Вход: два JSON от zhivo_drive_20261001.py (core, layer). Изход: validation/zhivo_sravnenie_20261001.md/.csv.
Мерки: (1) колко мача сменят топ прогнозата - суровата (rank_candidates, както в снимката) и публикуваната (rank_logged_rows с вътрешния предпазител);
(2) 10-те най-големи разлики в процентите; (3) сборове по пазар около 100%; (4) симулация на internal_guard с новите вероятности."""
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import pick_selection as ps  # noqa: E402
import prediction_policy as policy  # noqa: E402

import re


def num(x):
    return float(re.sub(r"^np\.float64\((.*)\)$", r"\1", x)) if isinstance(x, str) else float(x)


core = json.load(open(sys.argv[1]))
lay = json.load(open(sys.argv[2]))
ids = [k for k in core if k in lay and "error" not in core[k] and "error" not in lay[k]]


def rows_of(rec, fid):
    out = []
    for _title, items in rec["groups"]:
        for it in items:
            code = it[3]
            if code:
                out.append({"fixture_id": int(fid), "league": rec["league"], "market_code": code, "pick_label": it[0], "pick_pct": num(it[1])})
    return out


def pct_map(rec):
    return {it[3]: num(it[1]) for _t, items in rec["groups"] for it in items if it[3]}


# (1) смяна на топ прогнозата
raw_same = raw_chg = pub_same = pub_chg = pub_none_core = pub_none_lay = 0
changes = []
for fid in ids:
    c, l = core[fid], lay[fid]
    rc, rl = c["picks"][0], l["picks"][0]
    if rc[2] == rl[2]:
        raw_same += 1
    else:
        raw_chg += 1
    pc = ps.top_pick_for_match(rows_of(c, fid), c["league"], policy)
    pl = ps.top_pick_for_match(rows_of(l, fid), l["league"], policy)
    if pc is None and pl is None:
        continue
    if pc is None:
        pub_none_core += 1
    elif pl is None:
        pub_none_lay += 1
    elif pc["market_code"] == pl["market_code"]:
        pub_same += 1
    else:
        pub_chg += 1
        changes.append((fid, c["home"], c["away"], pc["market_code"], pc["pick_pct"], pl["market_code"], pl["pick_pct"]))

# (2) най-големи разлики в процентите (по пазар, всички кодове от групите; корнери/htft са непроменени -> 0)
diffs = []
for fid in ids:
    a, b = pct_map(core[fid]), pct_map(lay[fid])
    for code in a:
        if code in b:
            diffs.append((abs(b[code] - a[code]), fid, core[fid]["league"], core[fid]["home"], core[fid]["away"], code, a[code], b[code]))
diffs.sort(reverse=True)
by_code = defaultdict(list)
for d, _f, _l, _h, _a, code, _x, _y in diffs:
    by_code[code].append(d)

# (3) сборове по пазар около 100%
def sums(rec):
    m = pct_map(rec)
    s = {"1X2": m["home_win"] + m["draw"] + m["away_win"], "над/под 2.5": m["over25"] + m["under25"], "двата вкарват": m["btts_yes"] + m["btts_no"],
         "дом. над/под 1.5": m["home_over15"] + m["home_under15"], "гост над/под 1.5": m["away_over15"] + m["away_under15"],
         "двоен шанс (1X+X2+12)/2": (m["dc_1x"] + m["dc_x2"] + m["dc_12"]) / 2}
    return s
sc = pd.DataFrame([sums(core[f]) for f in ids]); sl = pd.DataFrame([sums(lay[f]) for f in ids])

# (4) internal_guard със слоя: нови уверени (>=65%) кандидати/мачове
def guard_stats(recs):
    n_hi = n_flag = n_match_hi = 0
    for fid in ids:
        rows = rows_of(recs[fid], fid)
        hi = [r for r in rows if r["pick_pct"] >= 65.0 and policy.is_top_pick_eligible(r["league"], r["market_code"], allow_weak=True) and r["pick_pct"] < 95]
        n_hi += len(hi)
        n_match_hi += 1 if hi else 0
        import internal_guard as ig
        n_flag += sum(1 for r in hi if ig.flagged(r))
    return n_hi, n_match_hi, n_flag
gc, gl = guard_stats(core), guard_stats(lay)

lam_ch = [(abs(num(lay[f]["lam"]) / num(core[f]["lam"]) - 1), abs(num(lay[f]["mu"]) / num(core[f]["mu"]) - 1)) for f in ids]
lam_arr = np.array(lam_ch)

L = ["# Слоят в живата прогноза: стар (ядро) срещу нов (ядро+слой) изход върху предстоящите мачове — 01.10.2026", "",
     f"Скрипт: `validation/zhivo_sravnenie_20261001.py` (+ `zhivo_drive_20261001.py`). Мачове: {len(ids)} предстоящи (2.10–31.10.2026, 17 лиги, набор AB, калибрация за слоя). "
     "Сравнението е между ИЗХОДА НА ЖИВИЯ КОД с `LAYER_LIVE=0` и с `LAYER_LIVE=1` (същата функция `compute_grouped_markets` + `top_picks_with_code`). "
     "Предстоящите мачове са до 4 седмици напред — признаците им са смятани днес (в живо ще се смятат на всеки 30 мин).", "",
     "## Смяна на топ прогнозата", "",
     f"- Сурова топ прогноза (`rank_candidates`, както я записва снимката): същата {raw_same}, друга {raw_chg} ({100*raw_chg/len(ids):.1f}%).",
     f"- Публикувана (`top_pick_for_match` с вътрешния предпазител, както я показва /prognozi): същата {pub_same}, друга {pub_chg} ({100*pub_chg/max(1,pub_same+pub_chg):.1f}%), "
     f"без прогноза със слоя (имало с ядрото) {pub_none_lay}, нова със слоя (нямало с ядрото) {pub_none_core}.", "",
     f"Промяна на очакваните голове: средно |Δ| lam {lam_arr[:,0].mean()*100:.1f}%, mu {lam_arr[:,1].mean()*100:.1f}%; максимум {lam_arr.max()*100:.1f}%.", "",
     "## 10-те най-големи разлики в процентите (слой − ядро, процентни пункта)", "",
     "| мач | пазар | ядро % | слой % | разлика |", "|---|---|---|---|---|"]
for d, fid, lg, h, a, code, x, y in diffs[:10]:
    L.append(f"| {h} – {a} ({lg}, {fid}) | {code} | {x:.1f} | {y:.1f} | {y-x:+.1f} |")
L += ["", "Средна |разлика| по пазар (п.п.): " + ", ".join(f"{c} {np.mean(v):.2f}" for c, v in sorted(by_code.items(), key=lambda kv: -np.mean(kv[1]))[:8]) + " … (корнери, полувреме/край — 0.00, непроменени)", "",
      "## Сборове по пазар (трябва ~100%)", "", "| пазар | ядро: мин–макс | слой: мин–макс |", "|---|---|---|"]
for col in sc.columns:
    L.append(f"| {col} | {sc[col].min():.2f} – {sc[col].max():.2f} | {sl[col].min():.2f} – {sl[col].max():.2f} |")
L += ["", "## internal_guard с новите вероятности", "",
      f"Уверени кандидати (pick ≥ 65%, допустими) върху тези {len(ids)} мача: ядро {gc[0]} кандидата в {gc[1]} мача, от тях флагнати от предпазителя {gc[2]}; "
      f"слой {gl[0]} кандидата в {gl[1]} мача, флагнати {gl[2]}. Колко мача сменят прогноза / нови / без прогноза — виж реда „Публикувана“ по-горе (вече минава през предпазителя).", ""]
if changes:
    L += ["Мачове със сменена публикувана прогноза (първите 15):", "", "| мач | ядро: пазар (%) | слой: пазар (%) |", "|---|---|---|"]
    for fid, h, a, c1, p1, c2, p2 in changes[:15]:
        L.append(f"| {h} – {a} ({fid}) | {c1} ({p1:.1f}) | {c2} ({p2:.1f}) |")
open("validation/zhivo_sravnenie_20261001.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
pd.DataFrame([{"fixture_id": fid, "market_code": code, "core_pct": x, "layer_pct": y} for _d, fid, _l, _h, _a, code, x, y in diffs]).to_csv("validation/zhivo_sravnenie_20261001.csv", index=False)
print("\n".join(L))
