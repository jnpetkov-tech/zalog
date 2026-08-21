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
        matches, api_error = mpa._predict_matches_for_league_impl(league, None, None)
        rows = []
        for m in matches:
            if m.get("pct") is None or not m.get("picks"):
                continue
            for p in m["picks"]:
                rows.append({
                    "fixture_id": m["fixture_id"], "league": league,
                    "match_date": m["date"], "home_team": m["home"], "away_team": m["away"],
                    "market_code": p["code"], "pick_label": p["label"], "pick_pct": p["pct"],
                    "fair_odds": p["odds"], "ev": None, "model_version": model_version,
                })
        st.save_snapshot_predictions(rows)
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
