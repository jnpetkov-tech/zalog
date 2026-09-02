"""
build_predictions_snapshot.py — Партида 3, Стъпка 2 (21.08.2026,
ARCHITECTURE.md, Граница 2: „смятане срещу показване").

Смята прогнозите за следващите DAYS_AHEAD дни за всички (активни) лиги и
пълни predictions_snapshot (виж system_tracker.save_snapshot_predictions/
clear_stale_snapshot, Стъпка 1). Засега РЪЧЕН скрипт - НЕ е закачен към
systemd timer (Стъпка 3) и `/daily` все още НЕ го чете (Стъпка 4). Пуска
се и не променя нищо в поведението на живата страница.

Преизползва СЪЩАТА логика, която `/daily` вика на всяка заявка
(`_predict_matches_for_league_impl`) - internal import на
match_predictor_app, по образец на nightly_snapshot.py/
refresh_pending_odds.py (виж CLAUDE_HANDOFF.md, работен протокол, import
alias-и). Страничен ефект, наследен от тази функция и запазен нарочно:
логва нови fixture-и в predictions_log (st.already_logged/log_all_markets)
- същото, което вече се случва при всяко зареждане на /daily днес, само
че сега може да се случи и без никой да е отворил страницата.

model_version = кратък git commit hash на HEAD в момента на смятане -
позволява по-късно честно сравнение какво е казвал моделът преди/след
бъдеща промяна, от реални данни, без ръчно поддържан version string.

Употреба: python3 build_predictions_snapshot.py
"""
import subprocess
import time
from datetime import date

import match_predictor_app as mpa
import system_tracker as st


def get_model_version():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd="/home/inkas/sportbg-predictor",
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def _extra_market_rows(league, m, model_version):
    """НОЩ 02.09.2026 (задача 3, NOSHT2.md): compute_grouped_markets() вече
    смята до 24 пазара за всеки мач (нула нови API заявки - real_odds идва
    от кеша, home_inj/away_inj вече изчислени в m по-горе), но само 8-те
    сурови кандидата (m["picks"]) стигаха до predictions_snapshot. Тук
    добавяме остатъка (is_candidate=0) - страницата на мача ги показва в
    пълната таблица, top_pick_for_match() (Задача 3, границата) никога не
    ги вижда, защото web/prognozi.py филтрира по is_candidate=1 преди да
    подаде редовете натам."""
    cached_odds = st.get_cached_odds(m["fixture_id"])
    groups, _ = mpa.compute_grouped_markets(
        league, m["home"], m["away"], m.get("home_inj", 0), m.get("away_inj", 0),
        real_odds=cached_odds,
    )
    if not groups:
        return []
    rows = []
    for _title, items, _has_form in groups:
        for item in items:
            if len(item) <= 3 or not item[3]:
                continue
            label, pct, _form, code = item[0], item[1], item[2], item[3]
            fair = round(100.0 / pct, 2) if pct > 0 else None
            rows.append({
                "fixture_id": m["fixture_id"], "league": league,
                "match_date": m["date"], "home_team": m["home"], "away_team": m["away"],
                "market_code": code, "pick_label": label, "pick_pct": pct,
                "fair_odds": fair, "ev": None, "model_version": model_version,
                "is_candidate": 0,
            })
    return rows


def build():
    model_version = get_model_version()
    # mpa.get_leagues() филтрира по бисквитка от браузъра (кой Дака е
    # избрал да вижда) - няма HTTP заявка тук, за да я прочете, пада с
    # "Working outside of request context". Смятаме за ВСИЧКИ регистрирани
    # лиги нарочно - филтърът по бисквитка си остава на мястото, където му
    # е мястото: при ЧЕТЕНЕ от таблицата в /daily (Стъпка 4), не тук.
    leagues = list(mpa.ALL_LEAGUES.keys())
    total_rows = 0
    total_matches = 0
    t0 = time.time()
    for league in leagues:
        t_lg = time.time()
        matches, api_error = mpa._predict_matches_for_league_impl(league, None, None, use_fixture_cache=True)
        rows = []
        meta_rows = []
        for m in matches:
            # НОЩ 02.09.2026 (задача 2): fixture_meta - лого на двата отбора,
            # за ВСЕКИ мач в снимката (не само тези с прогноза) - логата вече
            # са в m["home_logo"]/m["away_logo"] от fetch_upcoming_fixtures(),
            # нула допълнителни заявки.
            meta_rows.append({
                "fixture_id": m["fixture_id"], "league": league, "match_date": m["date"],
                "home_team": m["home"], "away_team": m["away"],
                "home_logo": m.get("home_logo"), "away_logo": m.get("away_logo"),
            })
            if m.get("pct") is None or not m.get("picks"):
                continue
            candidate_codes = set()
            for p in m["picks"]:
                candidate_codes.add(p["code"])
                rows.append({
                    "fixture_id": m["fixture_id"], "league": league,
                    "match_date": m["date"], "home_team": m["home"], "away_team": m["away"],
                    "market_code": p["code"], "pick_label": p["label"], "pick_pct": p["pct"],
                    "fair_odds": p["odds"], "ev": None, "model_version": model_version,
                    "is_candidate": 1,
                })
            for extra_row in _extra_market_rows(league, m, model_version):
                if extra_row["market_code"] in candidate_codes:
                    continue  # вече записан по-горе от m["picks"] - същата формула/число
                rows.append(extra_row)
        st.save_snapshot_predictions(rows)
        st.save_fixture_meta(meta_rows)
        elapsed = time.time() - t_lg
        status = f"api_error={api_error!r}" if api_error else "ok"
        print(f"[{league}] {len(matches)} мача, {len(rows)} реда записани, {elapsed:.1f}s, {status}", flush=True)
        total_rows += len(rows)
        total_matches += len(matches)

    st.clear_stale_snapshot(date.today().isoformat())
    print(f"\nОбщо: {total_matches} мача, {total_rows} реда, {len(leagues)} лиги, "
          f"{time.time()-t0:.1f}s, model_version={model_version}")


if __name__ == "__main__":
    build()
