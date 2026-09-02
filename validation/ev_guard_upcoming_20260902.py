"""validation/ev_guard_upcoming_20260902.py - Точка 4 от заданието на Дака
(02.09.2026): колко от ПОКАЗВАНИТЕ В МОМЕНТА предстоящи мачове (7 дни
напред, всички лиги, predictions_snapshot - същия източник като /prognozi)
биха отпаднали в "Мачове без доверена прогноза", сега когато EV guard-ът
(pick_selection.MAX_TRUSTWORTHY_EV) важи и за витрината, не само за
историята (виж web/prognozi.py::_snapshot_ev_pct, добавена в тази партида).

READ-ONLY: не пипа pick_selection.py/system_tracker.py/web/prognozi.py -
само чете и възпроизвежда СЪЩАТА логика, която вече живее там (същите
функции, извикани директно: pick_selection.top_pick_for_match/_row_ev_pct/
MAX_TRUSTWORTHY_EV, system_tracker.get_cached_odds/MARKET_ODDS_MAP).

Пише validation/ev_guard_upcoming_20260902.md.
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

import system_tracker as st
import pick_selection as ps
import prediction_policy as policy

DAY_TAB_COUNT = 7  # съвпада с web/prognozi.py::DAY_TAB_COUNT


def snapshot_ev_pct(fixture_id, code, pick_pct):
    """Буквално копие на web/prognozi.py::_snapshot_ev_pct() - същата
    функция, извън Flask closure-а не може да се импортира директно, но
    вика СЪЩИТЕ pick_selection.* функции/константа, не преизобретява
    формулата/прага."""
    cached_odds = st.get_cached_odds(fixture_id)
    odds_key = st.MARKET_ODDS_MAP.get(code)
    market_odds_val = cached_odds.get(odds_key) if (cached_odds and odds_key) else None
    if not market_odds_val or not pick_pct:
        return None
    our_fair_odds = round(100.0 / pick_pct, 2)
    return ps._row_ev_pct({"market_odds": market_odds_val, "our_fair_odds": our_fair_odds})


def main():
    today = date.today()
    from_date = today.isoformat()
    to_date = (today + timedelta(days=DAY_TAB_COUNT - 1)).isoformat()

    snap_rows = st.get_snapshot_rows_for_date_range(from_date, to_date)
    notes_map = st.get_all_match_notes()

    snap_by_fixture = {}
    for r in snap_rows:
        snap_by_fixture.setdefault(r["fixture_id"], []).append(r)

    n_total_matches = len(snap_by_fixture)
    n_skipped_by_note = 0
    n_no_pick_already = 0
    n_shown_with_pick = 0
    n_ev_computable = 0
    n_ev_not_computable = 0
    n_dropped = 0
    dropped_detail = []

    for fixture_id, rows in snap_by_fixture.items():
        league = rows[0]["league"]
        note = notes_map.get(fixture_id)
        if note and note["skip"]:
            n_skipped_by_note += 1
            continue

        top = ps.top_pick_for_match(rows, league, policy)
        if not top:
            n_no_pick_already += 1
            continue

        n_shown_with_pick += 1
        ev_pct = snapshot_ev_pct(fixture_id, top["market_code"], top["pick_pct"])
        if ev_pct is None:
            n_ev_not_computable += 1
            continue
        n_ev_computable += 1
        if ev_pct > ps.MAX_TRUSTWORTHY_EV:
            n_dropped += 1
            dropped_detail.append({
                "fixture_id": fixture_id, "league": league,
                "match_date": rows[0]["match_date"],
                "home_team": rows[0]["home_team"], "away_team": rows[0]["away_team"],
                "market_code": top["market_code"], "pick_pct": top["pick_pct"],
                "ev_pct": round(ev_pct, 1),
            })

    by_league = {}
    for d in dropped_detail:
        by_league.setdefault(d["league"], 0)
        by_league[d["league"]] += 1

    lines = []
    lines.append(f"# EV guard за предстоящи мачове (/prognozi) - измерване {today.isoformat()}\n")
    lines.append("Точка 4 от заданието на Дака - колко от показваните В МОМЕНТА предстоящи "
                  f"мачове ({from_date}..{to_date}, {DAY_TAB_COUNT} дни, всички лиги, "
                  "`predictions_snapshot` - същия източник, който `/prognozi` чете) биха "
                  "отпаднали в \"Мачове без доверена прогноза\", след като EV guard-ът "
                  "(`pick_selection.MAX_TRUSTWORTHY_EV`) вече важи и за витрината "
                  "(`web/prognozi.py::_snapshot_ev_pct`), не само за историята.\n")

    lines.append("## Числата\n")
    lines.append("| | брой |")
    lines.append("|---|---:|")
    lines.append(f"| Мачове в снимката за прозореца | {n_total_matches} |")
    lines.append(f"| Пропуснати от Дака (skip бележка) | {n_skipped_by_note} |")
    lines.append(f"| Вече без доверена прогноза (преди guard-а) | {n_no_pick_already} |")
    lines.append(f"| Показвани с прогноза (преди guard-а) | {n_shown_with_pick} |")
    lines.append(f"| ...от тях EV е СМЕТАЕМ (кеширан коефициент за пазара) | {n_ev_computable} |")
    lines.append(f"| ...от тях EV НЕ е сметаем (показва се както досега) | {n_ev_not_computable} |")
    lines.append(f"| **Биха отпаднали заради EV>40%** | **{n_dropped}** |")
    lines.append("")

    if n_dropped == 0:
        lines.append("**0.** Пуснато е реалната заявка (не предположение) - в момента "
                      "guard-ът не маха нито един предстоящ мач от витрината. Не значи, че "
                      "никога няма да го направи - зависи от бъдещи модел/пазар разминавания.\n")
    else:
        lines.append("## По лига\n")
        lines.append("| Лига | брой отпаднали |")
        lines.append("|---|---:|")
        for league, n in sorted(by_league.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {league} | {n} |")
        lines.append("")
        lines.append("## Детайл\n")
        lines.append("| Мач | Дата | Пазар | pick% | EV% |")
        lines.append("|---|---|---|---:|---:|")
        for d in dropped_detail:
            lines.append(f"| {d['home_team']} — {d['away_team']} ({d['league']}) | {d['match_date']} | "
                          f"{d['market_code']} | {d['pick_pct']:.1f}% | {d['ev_pct']:+.1f}% |")
        lines.append("")

    lines.append("## Точка 5 - /daily (админската) има ли същата дупка?\n")
    lines.append(
        "**Да, същия клас дупка съществува и там - НЕ поправено в тази партида, само "
        "докладвано.** `match_predictor_app.py::top_pick_with_code()`/`top_picks_with_code()` "
        "(главният списък на `/daily`, \"Днес\") строят `candidates` през `_raw_candidates(lam, "
        "mu, home, away, ht_ft_probs, market_odds, rho=rho)` - `market_odds` СЕ подава живо (за "
        "смесване на вероятността с пазара, `BLEND_WEIGHTS`), но резултатните `candidates` са "
        "чисти `(label, prob, code)` tuple-и без коефициент - точно същата структура, която "
        "`pick_selection.rank_candidates()` вика (за разлика от `rank_logged_rows()`, guard-нат в "
        "предишния commit). Implied EV е физически несмятаем в `rank_candidates()` СЕГА - "
        "коефициентът никога не стига до отделния кандидат, само до блендването преди това.\n")
    lines.append(
        "Второстепенните `/daily` секции (\"Уверени прогнози\"/`confident_matches` - през "
        "`ps.rank_logged_rows()` върху `predictions_log` редове; \"Стойностни\"/`value_matches` - "
        "през `get_value_opportunities()`) НЕ са засегнати: първата вече минава през guard-натия "
        "`rank_logged_rows()` от предишния commit автоматично, втората има собствен, по-строг "
        "таван (15% edge < 40%).\n")

    lines.append("## Честно ограничение\n")
    lines.append(f"EV е сметаем само за {n_ev_computable} от {n_shown_with_pick} показвани "
                  "прогнози - `st.get_cached_odds()` (`odds_cache` таблицата) пази коефициенти "
                  "само за пет пазара (home_win/draw/away_win/over25/under25), не пълния "
                  "`MARKET_ODDS_MAP`. За избран пазар извън тези пет (dc_1x, btts, htft, "
                  "cards/corners и т.н.) guard-ът е физически неприложим на витрината - "
                  "показва се както досега, съгласно т.3 от заданието (\"не гадай\"). Това е "
                  "СЪЩОТО структурно ограничение, отбелязано в `validation/"
                  "ev_guard_applied_20260902.md` за историята, само пренесено тук.\n")

    report = "\n".join(lines)
    with open("validation/ev_guard_upcoming_20260902.md", "w", encoding="utf-8") as f:
        f.write(report)
    print(report)


if __name__ == "__main__":
    main()
