"""validation/pazar_vun_20261001.py - ZADACHA_TABLICA, стъпка 5(а) (01.10.2026): пазарът вън от логиката на избора.

Днес pick_selection.rank_logged_rows() изключва кандидат, чийто implied EV (market_odds / our_fair_odds - 1) е над 40%
(MAX_TRUSTWORTHY_EV) - т.е. ИЗБОРЪТ на публикуваната прогноза ползва пазарния коефициент. Решението на Дака: пазарът да е само мерило.
Тук се симулира замяна на този предпазител с ВЪТРЕШЕН (без коефициент) и се брои колко мача сменят прогнозата. НИЩО не се прилага.

Вътрешни предпазители (всички от данни, известни преди мача):
  K  - малко история: най-малкият брой изиграни мачове на двата отбора в последните 365 дни (всички 17 лиги, fixtures API) < K;
  X  - екстремни очаквани голове от ядрото (lam или mu извън [0.35; 3.2]) - известно само за вече изиграни мачове в features/core_lam_mu.csv;
  P  - предпазителят работи само за "уверени" кандидати: pick_pct >= P (иначе - за всички кандидати на мача).
Варианти: V1 = K<к (всички кандидати на мача); V2 = K<к и pick_pct>=65; V3 = X и pick_pct>=65; V4 = (K<к или X) и pick_pct>=65.
Сравнение с днешното правило: смяна на прогнозата / мачът остава без прогноза / същото; припокриване с реда, изключен от EV предпазителя.
Изход: validation/pazar_vun_20261001.md и .csv.
"""
import bisect
import os
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import pick_selection as ps  # noqa: E402
import prediction_policy as policy  # noqa: E402

LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal", "champions_league", "europa_league",
           "conference_league", "france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
HI = 65.0
KS = [6, 10, 15]


def load_fixture_info():
    parts = [pd.read_csv(f"{l}_fixtures.csv", low_memory=False) for l in LEAGUES if os.path.exists(f"{l}_fixtures.csv")]
    fx = pd.concat(parts).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["timestamp"].notna()]
    fx["ts"] = fx["timestamp"].astype("int64")
    fx["fin"] = fx["status"].isin(["FT", "AET", "PEN"])
    by_team = defaultdict(list)
    for r in fx[fx["fin"]].itertuples():
        by_team[int(r.home_id)].append(r.ts)
        by_team[int(r.away_id)].append(r.ts)
    for t in by_team:
        by_team[t].sort()
    info = {}
    for r in fx.itertuples():
        def n_prior(t):
            lst = by_team.get(int(t), [])
            return bisect.bisect_left(lst, r.ts) - bisect.bisect_left(lst, r.ts - 365 * 86400)
        info[int(r.fixture_id)] = min(n_prior(r.home_id), n_prior(r.away_id))
    return info


def main():
    n_prior = load_fixture_info()
    core = pd.read_csv("features/core_lam_mu.csv", usecols=["fixture_id", "lam", "mu"]).set_index("fixture_id")
    con = sqlite3.connect("file:" + os.path.join(ROOT, "predictions.db") + "?mode=ro", uri=True)
    rows = pd.read_sql_query("select id, fixture_id, league, match_date, market_code, pick_pct, status, market_odds, our_fair_odds from predictions_log", con).to_dict("records")
    con.close()
    groups = defaultdict(list)
    for r in rows:
        groups[r["fixture_id"]].append(r)

    def run(guard):
        """guard(row) -> True, ако редът се изключва. Връща {fixture_id: избран ред или None}."""
        out = {}
        for fid, g in groups.items():
            ranked = ps._apply_rules(g, g[0]["league"], policy, get_pct=lambda r: r["pick_pct"] or 0, get_code=lambda r: r["market_code"],
                                     n=1, full_fallback=False, get_ev=(lambda r: float("inf") if guard(r) else None))
            out[fid] = ranked[0] if ranked else None
        return out

    ev_rule = {fid: (ps.rank_logged_rows(g, g[0]["league"], policy, n=1) or [None])[0] for fid, g in groups.items()}
    none_rule = run(lambda r: False)
    ev_excl = {r["id"] for r in rows if (ps._row_ev_pct(r) or 0) > ps.MAX_TRUSTWORTHY_EV}
    extreme = lambda fid: (fid in core.index) and (not (0.35 <= core.loc[fid, "lam"] <= 3.2) or not (0.35 <= core.loc[fid, "mu"] <= 3.2))

    variants = {}
    for k in KS:
        low = lambda r, k=k: n_prior.get(int(r["fixture_id"]), 99) < k
        variants[f"V1 (К<{k}, всички кандидати)"] = lambda r, low=low: low(r)
        variants[f"V2 (К<{k} и pick>={HI:.0f}%)"] = lambda r, low=low: low(r) and (r["pick_pct"] or 0) >= HI
        variants[f"V4 (К<{k} или X, pick>={HI:.0f}%)"] = lambda r, low=low: (low(r) or extreme(int(r["fixture_id"]))) and (r["pick_pct"] or 0) >= HI
    variants[f"V3 (X, pick>={HI:.0f}%)"] = lambda r: extreme(int(r["fixture_id"])) and (r["pick_pct"] or 0) >= HI

    def cmp(a, b):
        same = chg = lost = gained = 0
        for fid in groups:
            x, y = a[fid], b[fid]
            if x is None and y is None:
                continue
            if x is None: gained += 1
            elif y is None: lost += 1
            elif x["market_code"] == y["market_code"]: same += 1
            else: chg += 1
        return same, chg, lost, gained

    total_pub = sum(1 for v in ev_rule.values() if v is not None)
    base = cmp(ev_rule, none_rule)
    out_rows = [{"вариант": "днешното правило (EV>40%) -> без никакъв предпазител", "същото": base[0], "друга прогноза": base[1], "без прогноза": base[2], "нова прогноза": base[3]}]
    res = {}
    for name, g in variants.items():
        r = run(g)
        res[name] = r
        s = cmp(ev_rule, r)
        out_rows.append({"вариант": name, "същото": s[0], "друга прогноза": s[1], "без прогноза": s[2], "нова прогноза": s[3]})
    df = pd.DataFrame(out_rows)
    df.to_csv("validation/pazar_vun_20261001.csv", index=False)

    # припокриване на ниво ред: EV-изключените срещу вътрешните
    ov = []
    elig = [r for r in rows if policy.is_top_pick_eligible(r["league"], r["market_code"], allow_weak=True)]
    for name, g in variants.items():
        flagged = {r["id"] for r in elig if g(r)}
        e = {r["id"] for r in elig if r["id"] in ev_excl}
        inter = len(flagged & e)
        ov.append({"вариант": name, "EV-изключени (eligible)": len(e), "вътрешно изключени": len(flagged), "общи": inter,
                   "дял от EV-изключените, уловени": inter / len(e) if e else float("nan")})
    ovdf = pd.DataFrame(ov)

    # успеваемост на избраните прогнози (уредените)
    def hit(sel):
        s = [v for v in sel.values() if v is not None and v["status"] in ("won", "lost")]
        return len(s), (sum(1 for v in s if v["status"] == "won") / len(s)) if s else float("nan"), (np.mean([v["pick_pct"] for v in s]) / 100 if s else float("nan"))
    hrows = [{"правило": "днешно (EV>40%)", **dict(zip(["уредени", "познати", "обещано"], hit(ev_rule)))},
             {"правило": "без предпазител", **dict(zip(["уредени", "познати", "обещано"], hit(none_rule)))}]
    for name, r in res.items():
        hrows.append({"правило": name, **dict(zip(["уредени", "познати", "обещано"], hit(r)))})
    hdf = pd.DataFrame(hrows)

    L = ["# Пазарът вън от логиката на избора — симулация — 01.10.2026", "",
         "Скрипт: `validation/pazar_vun_20261001.py`. Данни: целият `predictions_log` (само четене; " f"{len(groups)} мача, {len(rows)} реда). **Нищо не е приложено** — пач: `pazar_vun.patch`.", "",
         "## Какво прави днес пазарът в избора", "",
         f"`pick_selection.rank_logged_rows()` изключва кандидат, чийто implied EV (`market_odds / our_fair_odds − 1`) е над {ps.MAX_TRUSTWORTHY_EV:.0f}%. "
         f"Така пазарният коефициент влияе върху това КОЯ прогноза се публикува. Днес публикуваме прогноза за {total_pub} от {len(groups)} мача; "
         f"изключените от EV предпазителя редове (всички, не само eligible): {len(ev_excl)}.", "",
         "## Предлаган вътрешен предпазител (без коефициент)", "",
         "- **К — малко история:** най-малкият брой изиграни мачове на двата отбора в последните 365 дни (всички 17 лиги) е под К (нов/повишен отбор, начало на сезона).",
         "- **X — екстремно ядро:** очакваните голове на ядрото `lam` или `mu` са извън [0.35; 3.2] (само за вече изиграни мачове; за предстоящите — известно след пускането на слоя/ядрото).",
         f"- Предпазителят изключва кандидати, а не целия мач, когато е ограничен до уверените (pick ≥ {HI:.0f}%) — така мачът запазва по-предпазлива прогноза, вместо да остане без.", "",
         "## Колко мача сменят прогнозата (спрямо днешното правило)", "",
         "| вариант | същото | друга прогноза | без прогноза | нова прогноза |", "|---|---|---|---|---|"]
    for r in out_rows:
        L.append(f"| {r['вариант']} | {r['същото']} | {r['друга прогноза']} | {r['без прогноза']} | {r['нова прогноза']} |")
    L += ["", "(„без никакъв предпазител“ показва колко мача днес сменя самият EV предпазител.)", "",
          "## Припокриване с реда, изключен от EV предпазителя (само eligible кандидати)", "",
          "| вариант | EV-изключени | вътрешно изключени | общи | дял от EV-изключените, уловени |", "|---|---|---|---|---|"]
    for r in ovdf.itertuples():
        L.append(f"| {r.вариант} | {r._2} | {r._3} | {r.общи} | {r._5:.2f} |")
    L += ["", "## Успеваемост на избраните прогнози (уредени) — информативно, малки извадки", "",
          "| правило | уредени | познати | обещано |", "|---|---|---|---|"]
    for r in hdf.itertuples():
        L.append(f"| {r.правило} | {r.уредени} | {r.познати:.3f} | {r.обещано:.3f} |")
    open("validation/pazar_vun_20261001.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
