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

Заключване (ZADACHA_SASTAVI_BARZO, 02.10.2026): пълната снимка (systemd, на 30 мин) и бързата (snapshot_final.py - само мачовете с нов
final ред по съставите, crontab на 5 мин) пишат в едни и същи таблици - build() взема общ файлов ключ SNAPSHOT_LOCK, двете никога не
вървят едновременно; по-късно започналата смята и пише последна, т.е. с по-новите данни.

Употреба: python3 build_predictions_snapshot.py
"""
import fcntl
import subprocess
import time
from datetime import date

import layer_live
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


def _model_version_for(model_version, m):
    """ZADACHA_ZHIVO: мач, минал през слоя, носи версията му в model_version (напр. 'a1b2c3d+слой:20261001_7d29039'); на ядрото - само git hash."""
    return f"{model_version}+слой:{m['layer_version']}" if m.get("layer_version") else model_version


def _new_market_rows(league, m, model_version, std_rows=None):
    """ZADACHA_RAZVITIE т.5: новите пазари (extra_markets.py) - от СЪЩИТЕ lam/mu като compute_grouped_markets() (ядро + слой, контузиите
    на мача) и rho на модела -> extra_markets_snapshot (отделна таблица, само страницата на мача). Връща винаги [] - в
    predictions_snapshot не влиза нищо ново. EXTRA_MARKETS=0 или грешка -> нищо не се записва."""
    import extra_markets
    if not extra_markets.enabled():
        return []
    try:
        models = mpa.get_models(league)
        teams, team_idx, ft_model = models[:3]
        if m["home"] not in team_idx or m["away"] not in team_idx:
            return []
        lam, mu, _ver = mpa.get_ft_lambdas_live(m["fixture_id"], ft_model, team_idx, m["home"], m["away"],
                                                m.get("home_inj", 0), m.get("away_inj", 0))
        corners = htft = None
        if extra_markets.show_all():
            # ZADACHA_VSICHKO: същите модели като compute_grouped_markets() - корнерите (corners_model), полувреме/край (ht/2h модели)
            try:
                ht_model, h2_model, corners_model = models[3], models[4], models[5]
                if corners_model and "glm" in corners_model:
                    lc, mc = mpa.fl.corners_pressure_lambdas(corners_model, team_idx, m["home"], m["away"])
                    if lc is not None:
                        corners = (lc, mc, corners_model["alpha"])
                lh, mh = mpa.fl.get_lambdas(ht_model, team_idx, m["home"], m["away"])
                l2, m2 = mpa.fl.get_lambdas(h2_model, team_idx, m["home"], m["away"])
                htft = mpa.predict_ht_ft(lh, mh, l2, m2)
            except Exception as e:
                print(f"[всички пазари] {league} {m.get('fixture_id')}: {type(e).__name__}: {e}", flush=True)
        items = extra_markets.compute(league, lam, mu, ft_model.get("rho", 0.0),
                                      mpa.to_cyrillic(m["home"], league), mpa.to_cyrillic(m["away"], league),
                                      home=m["home"], away=m["away"], corners=corners, htft=htft)
        extra_markets.save_snapshot(m["fixture_id"], league, m["date"], items, model_version)
        if extra_markets.show_all() and std_rows:
            # т.4: всеки показан пазар - веднъж в дневника (и стандартните редове на мача, вкл. непубликуемите)
            extra_markets.log_first(m["fixture_id"], league, m["date"],
                                    [(r["market_code"], r["pick_label"], r["pick_pct"]) for r in std_rows
                                     if r["fixture_id"] == m["fixture_id"] and r["pick_pct"] is not None], model_version)
    except Exception as e:
        print(f"[нови пазари] {league} {m.get('fixture_id')}: {type(e).__name__}: {e}", flush=True)
    return []      # нищо в predictions_snapshot - новите пазари живеят в extra_markets_snapshot (виж extra_markets.py)


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
        real_odds=cached_odds, fixture_id=m["fixture_id"],
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
    rows += _new_market_rows(league, m, model_version, std_rows=rows)
    return rows


SNAPSHOT_LOCK = "/tmp/predictions_snapshot_build.lock"


def acquire_lock(wait_seconds):
    """Общият ключ на пълната и бързата снимка. -> отворен файл (държи ключа до затваряне/край на процеса) или None след wait_seconds."""
    f = open(SNAPSHOT_LOCK, "a")
    t0 = time.time()
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except OSError:
            if time.time() - t0 >= wait_seconds:
                f.close()
                return None
            time.sleep(2)


def build(only_fixtures=None):
    """only_fixtures=None - пълната снимка (както винаги). Множество fixture_id - бързият режим (snapshot_final.py): само лигите на тези мачове,
    записват се САМО техните редове; без слоя AB (layer_live.refresh), без clear_stale_snapshot. Ключът се взема от извикващия."""
    model_version = get_model_version()
    # mpa.get_leagues() филтрира по бисквитка от браузъра (кой Дака е
    # избрал да вижда) - няма HTTP заявка тук, за да я прочете, пада с
    # "Working outside of request context". Смятаме за ВСИЧКИ регистрирани
    # лиги нарочно - филтърът по бисквитка си остава на мястото, където му
    # е мястото: при ЧЕТЕНЕ от таблицата в /daily (Стъпка 4), не тук.
    leagues = list(mpa.ALL_LEAGUES.keys())
    if only_fixtures is not None:
        leagues = sorted({lg for _fid, lg in only_fixtures.items()}, key=leagues.index)
        layer_live._cache["at"] = 0.0              # final редовете - прочетени наново, не от кеша на процеса
    if layer_live.enabled() and only_fixtures is None:
        # ZADACHA_ZHIVO: слоят смята очакваните голове на предстоящите мачове ПРЕДИ цикъла (грешка вътре -> мачовете падат на ядрото, не гърми)
        n_rows, n_sched, secs = layer_live.refresh()
        print(f"[слой] {n_rows}/{n_sched} мача през слоя, {secs:.1f}s", flush=True)
    total_rows = 0
    total_matches = 0
    t0 = time.time()
    for league in leagues:
        t_lg = time.time()
        matches, api_error = mpa._predict_matches_for_league_impl(league, None, None, use_fixture_cache=True)
        if only_fixtures is not None:
            matches = [m for m in matches if m["fixture_id"] in only_fixtures]
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
                    "fair_odds": p["odds"], "ev": None, "model_version": _model_version_for(model_version, m),
                    "is_candidate": 1,
                })
            for extra_row in _extra_market_rows(league, m, _model_version_for(model_version, m)):
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

    if only_fixtures is None:
        st.clear_stale_snapshot(date.today().isoformat())
    print(f"\nОбщо: {total_matches} мача, {total_rows} реда, {len(leagues)} лиги, "
          f"{time.time()-t0:.1f}s, model_version={model_version}")


if __name__ == "__main__":
    _lk = acquire_lock(300)
    if _lk is None:
        print("ключът на снимката е зает над 300 с (бързата снимка?) - продължавам без него", flush=True)
    build()
