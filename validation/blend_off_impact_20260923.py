"""ZADACHA_MODEL1.md, ЧАСТ Б (23.09.2026): какво се сменя, когато
BLEND_WEIGHTS стане 0.0 навсякъде (чист модел, без смесване с пазара).

Само измерване - не пише в базата. Пуска се ПРЕДИ промяната на живия
файл: "преди" = теглата, които са в match_predictor_app.py в момента;
"след" = същата сметка с BLEND_WEIGHTS подменени в паметта на 0.0.

Две извадки (и в двете - само мачове с ред в odds_cache; без коефициент
смесване няма и двете страни са еднакви по определение):
- "upcoming": предстоящите мачове в predictions_snapshot (match_date >=
  днес) - това, което сайтът показва в момента;
- "logged": всички мачове в predictions_log с 1X2 коефициент в odds_cache
  (последния кеширан), пресметнати с ДНЕШНИТЕ модели - по-голяма извадка
  за същия въпрос, не възстановяване на историческите числа. НАМАЛЕНО
  (23.09.2026, еднократна сесия, пълната извадка е твърде бавна): случайни
  LOGGED_SAMPLE_N=200 мача, random.Random(42) - възпроизводимо.
Контузиите - от injuries_cache (без ограничение за възраст), иначе 0.

Три броя, всеки преди/след:
1. 1X2 сбор извън 97-103% - правилото в web/prognozi.py
   (MARKET_SUM_TOLERANCE_PCT), приложено върху числата от
   compute_grouped_markets().
2. EV > MAX_TRUSTWORTHY_EV (40%) в compute_grouped_markets() -
   distrusted_bets (таблицата "Разлики с пазара" на /match_detail).
3. EV > 40% по формулата на pick_selection._row_ev_pct() (market_odds /
   our_fair_odds - 1, our_fair_odds = 100/pick_pct - точно както
   system_tracker.log_all_markets() го записва), върху всички кодове с
   коефициент, и отделно само върху publishable кодове за лигата.

Изход: validation/blend_off_impact_20260923.csv (ред на мач, колона sample).
"""
import csv
import os
import random
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import match_predictor_app as mpa  # noqa: E402
import system_tracker as st  # noqa: E402
import prediction_policy as policy  # noqa: E402
from web.prognozi import MARKET_SUM_TOLERANCE_PCT  # noqa: E402

OUT = os.path.join(ROOT, "validation", "blend_off_impact_20260923.csv")
ZERO = {k: 0.0 for k in mpa.BLEND_WEIGHTS}
LOGGED_SAMPLE_N = 200


def fixtures():
    conn = st.get_conn()
    upcoming = conn.execute("""
        SELECT DISTINCT s.fixture_id, s.league, s.home_team, s.away_team, s.match_date
        FROM predictions_snapshot s JOIN odds_cache o ON o.fixture_id = s.fixture_id
        WHERE s.match_date >= ?
        ORDER BY s.match_date""", (date.today().isoformat(),)).fetchall()
    logged = conn.execute("""
        SELECT DISTINCT p.fixture_id, p.league, p.home_team, p.away_team, p.match_date
        FROM predictions_log p JOIN odds_cache o ON o.fixture_id = p.fixture_id
        WHERE o.home_odds IS NOT NULL
        ORDER BY p.match_date""").fetchall()
    logged = [tuple(r) for r in logged]
    if len(logged) > LOGGED_SAMPLE_N:
        logged = sorted(random.Random(42).sample(logged, LOGGED_SAMPLE_N), key=lambda r: r[4])
    rows = [("upcoming",) + tuple(r) for r in upcoming] + [("logged",) + tuple(r) for r in logged]
    inj = {r[0]: (r[1] or 0, r[2] or 0) for r in conn.execute(
        "SELECT fixture_id, home_injuries, away_injuries FROM injuries_cache")}
    conn.close()
    return rows, inj


def measure(league, home, away, hi, ai, odds):
    groups, extra = mpa.compute_grouped_markets(league, home, away, hi, ai, real_odds=odds)
    if not groups:
        return None
    pct = {r[3]: r[1] for _t, items, _h in groups for r in items if len(r) > 3 and r[3]}
    x12 = [pct.get(c) for c in ("home_win", "draw", "away_win")]
    x12_sum = sum(x12) if None not in x12 else None
    distrusted = len(extra[6])
    ev_all = ev_pub = 0
    for code, p in pct.items():
        key = st.MARKET_ODDS_MAP.get(code)
        mo = odds.get(key) if key else None
        if not mo or p <= 0:
            continue
        fair = round(100 / p, 2)
        if (mo / fair - 1) * 100.0 > 40.0:
            ev_all += 1
            if policy.is_publishable(league, code):
                ev_pub += 1
    return {"x12_sum": x12_sum, "distrusted": distrusted, "ev_all": ev_all, "ev_pub": ev_pub,
            "copy_codes": len(extra[7])}


def set_weights(w):
    """Подменя теглата в паметта; MARKET_COPY_CODES се смята от тях при
    import, затова се преизчислява със същата формула."""
    mpa.BLEND_WEIGHTS.clear(); mpa.BLEND_WEIGHTS.update(w)
    mpa.MARKET_COPY_CODES = {c for c, v in mpa.BLEND_WEIGHTS.items() if v >= 1.0}


def main():
    current = dict(mpa.BLEND_WEIGHTS)
    rows, inj = fixtures()
    out = []
    for sample, fid, league, home, away, md in rows:
        odds = st.get_cached_odds(fid)
        hi, ai = inj.get(fid, (0, 0))
        set_weights(current)
        before = measure(league, home, away, hi, ai, odds)
        set_weights(ZERO)
        after = measure(league, home, away, hi, ai, odds)
        set_weights(current)
        if not before or not after:
            continue
        out.append({"sample": sample, "fixture_id": fid, "league": league, "match_date": md,
                    **{f"{k}_before": v for k, v in before.items()},
                    **{f"{k}_after": v for k, v in after.items()}})
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)

    def off(v):
        return v is not None and abs(v - 100.0) > MARKET_SUM_TOLERANCE_PCT

    print(f"Теглата преди: {current}")
    print(f"Извадка logged: {LOGGED_SAMPLE_N} случайни мача (seed 42)")
    for sample in ("upcoming", "logged"):
        report(sample, [r for r in out if r["sample"] == sample], off)


def report(sample, out, off):
    has_x12 = [r for r in out if r["x12_sum_before"] is not None]
    print(f"== {sample}: мачове {len(out)}; с 1X2: {len(has_x12)}")
    for tag in ("before", "after"):
        sums = [r[f"x12_sum_{tag}"] for r in has_x12]
        print(f"[{tag}] 1X2 сбор мин/макс: {min(sums):.2f} / {max(sums):.2f}; "
              f"извън 97-103%: {sum(off(s) for s in sums)}")
        print(f"[{tag}] distrusted_bets (EV>40%, compute_grouped_markets): "
              f"{sum(r[f'distrusted_{tag}'] for r in out)} реда в "
              f"{sum(1 for r in out if r[f'distrusted_{tag}'])} мача")
        print(f"[{tag}] EV>40% по pick_selection формулата: всички кодове {sum(r[f'ev_all_{tag}'] for r in out)}, "
              f"publishable {sum(r[f'ev_pub_{tag}'] for r in out)}")
        print(f"[{tag}] мачове с 'пазарна оценка' кодове: {sum(1 for r in out if r[f'copy_codes_{tag}'])}")


if __name__ == "__main__":
    main()
