"""validation/odds_cache_widening_20260902.py - Т.4 от заданието на Дака:
измерва колко от показваните ПРЕДСТОЯЩИ прогнози (7 дни напред, всички
лиги, predictions_snapshot - същия източник, който /prognozi чете) имат
"Разлика с пазара" (пресметната market_pct/diff) и колко имат сметаем
implied EV за guard-а (pick_selection.MAX_TRUSTWORTHY_EV) - ПРЕДИ и СЛЕД
разширението на odds_cache (ODDS_CACHE_MARKETS, system_tracker.py).

READ-ONLY спрямо предсказанията - не пише нищо в predictions_log/
predictions_snapshot. Приема --db <path> за да може да се пусне и срещу
мигрирана ТЕСТОВА копие на базата (веднага след схема-разширението,
преди истинско опресняване), без да пипа живия predictions.db. Без
аргумент чете живата база директно (за измерването СЛЕД истинско
опресняване, когато Дака вече е рестартирал услугата).

Пише/презаписва секцията с числа в validation/odds_cache_widening_20260902.md
чрез ръчно копиране на резултата - виж инструкциите в самия .md файл за
кога и как да се пусне повторно.
"""
import sys
import os
import argparse
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

import system_tracker as st
import pick_selection as ps
import prediction_policy as policy

DAY_TAB_COUNT = 7


def snapshot_ev_pct(fixture_id, code, pick_pct):
    """Копие на web/prognozi.py::_snapshot_ev_pct() - вика pick_selection.
    _row_ev_pct()/MAX_TRUSTWORTHY_EV директно, не преизобретява формулата."""
    cached_odds = st.get_cached_odds(fixture_id)
    odds_key = st.MARKET_ODDS_MAP.get(code)
    market_odds_val = cached_odds.get(odds_key) if (cached_odds and odds_key) else None
    if not market_odds_val or not pick_pct:
        return None
    our_fair_odds = round(100.0 / pick_pct, 2)
    return ps._row_ev_pct({"market_odds": market_odds_val, "our_fair_odds": our_fair_odds})


def market_pct_for(fixture_id, code, cached_odds):
    """Опростено копие на web/prognozi.py::_row_diff() - само дали
    "Разлика с пазара" би имала стойност (devig-нат пазарен %), без Flask
    контекста. Покрива само home_win/draw/away_win/over25/under25 - СЪЩОТО
    ограничение като _market_info_for_pick() в match_predictor_app.py."""
    if not cached_odds:
        return None
    try:
        if code in ("home_win", "draw", "away_win"):
            h, d, a = cached_odds.get("home_win"), cached_odds.get("draw"), cached_odds.get("away_win")
            if not (h and d and a):
                return None
            return 1.0  # само дали е сметаемо, не точната стойност
        if code in ("over25", "under25"):
            o, u = cached_odds.get("over25"), cached_odds.get("under25")
            if not (o and u):
                return None
            return 1.0
    except (TypeError, ZeroDivisionError):
        return None
    return None


def measure():
    today = date.today()
    from_date = today.isoformat()
    to_date = (today + timedelta(days=DAY_TAB_COUNT - 1)).isoformat()

    snap_rows = st.get_snapshot_rows_for_date_range(from_date, to_date)
    notes_map = st.get_all_match_notes()

    snap_by_fixture = {}
    for r in snap_rows:
        snap_by_fixture.setdefault(r["fixture_id"], []).append(r)

    n_shown_with_pick = 0
    n_has_diff = 0
    n_ev_computable = 0

    for fixture_id, rows in snap_by_fixture.items():
        league = rows[0]["league"]
        note = notes_map.get(fixture_id)
        if note and note["skip"]:
            continue
        top = ps.top_pick_for_match(rows, league, policy)
        if not top:
            continue
        n_shown_with_pick += 1

        cached_odds = st.get_cached_odds(fixture_id)
        if market_pct_for(fixture_id, top["market_code"], cached_odds) is not None:
            n_has_diff += 1

        ev_pct = snapshot_ev_pct(fixture_id, top["market_code"], top["pick_pct"])
        if ev_pct is not None:
            n_ev_computable += 1

    return {
        "n_shown_with_pick": n_shown_with_pick,
        "n_has_diff": n_has_diff,
        "n_ev_computable": n_ev_computable,
        "window": (from_date, to_date),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="път до predictions.db (по подразбиране живата база)")
    args = ap.parse_args()
    if args.db:
        st.DB_PATH = args.db
        print(f"(четено от {args.db})")
    else:
        print(f"(четено от живата база: {st.DB_PATH})")

    r = measure()
    print(f"Прозорец: {r['window'][0]}..{r['window'][1]}")
    print(f"Показвани предстоящи прогнози: {r['n_shown_with_pick']}")
    print(f"...с 'Разлика с пазара' (market_pct сметаем): {r['n_has_diff']}")
    print(f"...с сметаем implied EV (guard-а): {r['n_ev_computable']}")


if __name__ == "__main__":
    main()
