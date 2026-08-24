"""
web/daily.py — основните "разглеждай прогнози" маршрути (/, /daily, /manual,
/live), извадени от match_predictor_app.py (ARCHITECTURE.md, Граница 4,
последна част: маршрутите излизат по blueprint-и).

Регистрира се чрез register_daily_routes(app, ctx), по същия модел като
web/results.py, web/value.py, web/admin.py - избягва кръгов импорт с
match_predictor_app.py. Модел/бизнес логиката (get_models,
compute_grouped_markets, _predict_matches_for_league и т.н.) остава в
match_predictor_app.py, подадена през ctx - виж CLAUDE_HANDOFF.md за
пълната обосновка на тази граница.
"""
from flask import Blueprint, request, render_template, make_response
from datetime import date, timedelta, datetime
from concurrent.futures import ThreadPoolExecutor

BG_WEEKDAYS = ["Понеделник", "Вторник", "Сряда", "Четвъртък", "Петък", "Събота", "Неделя"]

DAILY_SORT_OPTIONS = ("date", "value", "confident")


def _daily_sort_key(sort):
    """Ключ за сортиране на upcoming_matches при sort='value'/'confident' -
    мачове без картичка/прогноза (нов отбор, чака следващо изчисление) или
    без положителен EV (build_pick_card връща card['value']=None) отиват
    най-долу, не най-горе, затова -inf вместо 0 при липса."""
    if sort == "value":
        def key(m):
            card = m.get("card")
            ev = card.get("value", {}).get("ev") if card and card.get("value") else None
            return ev if ev is not None else float("-inf")
        return key
    def key(m):
        pct = m.get("pct")
        return pct if pct is not None else float("-inf")
    return key


def date_group_label(date_str):
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return date_str[:10]
    today = date.today()
    if d == today:
        return "Днес"
    elif d == today + timedelta(days=1):
        return "Утре"
    else:
        return f"{BG_WEEKDAYS[d.weekday()]}, {d.strftime('%d.%m')}"


def register_daily_routes(app, ctx):
    DAYS_AHEAD = ctx["DAYS_AHEAD"]
    LIVE_STATUSES = ctx["LIVE_STATUSES"]
    FINISHED_STATUSES = ctx["FINISHED_STATUSES"]
    ALL_LEAGUES = ctx["ALL_LEAGUES"]
    LEAGUE_FLAGS = ctx["LEAGUE_FLAGS"]
    st = ctx["st"]
    evaluation = ctx["evaluation"]
    ps = ctx["ps"]
    policy = ctx["policy"]
    to_cyrillic = ctx["to_cyrillic"]
    fl = ctx["fl"]
    get_models = ctx["get_models"]
    get_leagues = ctx["get_leagues"]
    compute_grouped_markets = ctx["compute_grouped_markets"]
    _daily_use_snapshot = ctx["_daily_use_snapshot"]
    _predict_matches_for_league = ctx["_predict_matches_for_league"]
    fetch_fixture_id_for_today = ctx["fetch_fixture_id_for_today"]
    get_refresh_state = ctx["get_refresh_state"]

    daily_bp = Blueprint("daily", __name__)

    @daily_bp.route("/")
    def index_home():
        predictions = st.list_predictions()
        won = sum(1 for p in predictions if p["status"] == "won")
        lost = sum(1 for p in predictions if p["status"] == "lost")
        pending = sum(1 for p in predictions if p["status"] == "pending")
        total_settled = won + lost
        win_rate = (won / total_settled * 100) if total_settled else None
        overall = {"won": won, "lost": lost, "pending": pending, "win_rate": win_rate}
        # Фаза I.3: честна метрика само върху ПУБЛИКУВАНИТЕ прогнози (виж
        # evaluation.py, Фаза I.2) - връща плочката, скрита в Фаза H.2.
        eval_summary = evaluation.summary(predictions, policy)
        today_str = date.today().isoformat()
        today_preds = [p for p in predictions if p["status"] == "pending" and str(p["match_date"])[:10] == today_str]
        match_groups = {}
        for p in today_preds:
            key = (p["match_date"], p["home_team"], p["away_team"], p["league"])
            match_groups.setdefault(key, []).append(p)
        top_matches = []
        for (mdate, home, away, league), preds in match_groups.items():
            ranked = ps.rank_logged_rows(preds, league, policy, n=1)
            if not ranked:
                continue
            top_pred = ranked[0]
            top_matches.append({"date": mdate, "home": home, "away": away, "league": league, "top_pred": top_pred})
        top_matches.sort(key=lambda m: -m["top_pred"]["pick_pct"])
        top_matches = top_matches[:5]
        return render_template("index.html", active_page='home', overall=overall,
                                        top_matches=top_matches, cyrillic=to_cyrillic,
                                        promised_avg=eval_summary["promised_avg"],
                                        actual_pct=eval_summary["actual_pct"],
                                        n_settled=eval_summary["n_settled"],
                                        refresh_state=get_refresh_state())

    @daily_bp.route("/manual")
    def index():
        league = request.args.get("league", "bulgaria")
        home = request.args.get("home", "")
        away = request.args.get("away", "")
        teams = get_models(league)[0]
        cyrillic = {t: to_cyrillic(t, league) for t in teams}

        groups, extra_info = (None, None)
        if home and away:
            groups, extra_info = compute_grouped_markets(league, home, away)

        return render_template("manual.html", leagues=get_leagues(), selected_league=league,
                                        teams=teams, home=home, away=away, groups=groups,
                                        extra_info=extra_info, cyrillic=cyrillic, active_page='manual')

    @daily_bp.route("/daily")
    def daily():
        league = request.args.get("league", "bulgaria")
        from_str = request.args.get("from_date", "")
        to_str = request.args.get("to_date", "")

        sort = request.args.get("sort")
        if sort not in DAILY_SORT_OPTIONS:
            sort = request.cookies.get("daily_sort")
        if sort not in DAILY_SORT_OPTIONS:
            sort = "date"

        from_date = None
        to_date = None
        if from_str:
            try:
                from_date = date.fromisoformat(from_str)
            except ValueError:
                pass
        if to_str:
            try:
                to_date = date.fromisoformat(to_str)
            except ValueError:
                pass

        default_from = date.today()
        default_to = date.today() + timedelta(days=DAYS_AHEAD)

        use_snapshot = _daily_use_snapshot(request)

        # Партида 3, довършване (21.08.2026): ако build_predictions_snapshot.py
        # гръмне през нощта и не успее да презапише таблицата, /daily (в
        # snapshot режим) би сервирал старите редове мълчаливо, без Дака да
        # разбере. Проверка: най-новият computed_at в цялата таблица - ако е
        # по-стар от ~2 часа (build-predictions-snapshot.timer тръгва на 30
        # мин), предупреждаваме на страницата, по образец на api_error банера
        # по-долу.
        snapshot_stale_warning = None
        if use_snapshot:
            freshness = st.get_snapshot_freshness()
            if freshness is None:
                snapshot_stale_warning = ("Снимката с прогнози (predictions_snapshot) е празна - фоновата задача "
                                           "build_predictions_snapshot.py вероятно още не е пускана успешно.")
            else:
                try:
                    age_hours = (datetime.now() - datetime.fromisoformat(freshness)).total_seconds() / 3600
                    if age_hours > 2:
                        snapshot_stale_warning = (
                            f"Прогнозите не са преизчислявани от {age_hours:.1f} часа "
                            f"(последно смятане: {freshness[:16].replace('T', ' ')}) - фоновата задача вероятно е спряла. "
                            "Показваме последните успешно запазени данни, не най-новите.")
                except (ValueError, TypeError):
                    pass

        matches = []
        api_error = None
        if league == "all":
            league_keys = list(get_leagues().keys())
            with ThreadPoolExecutor(max_workers=min(8, len(league_keys) or 1)) as executor:
                futures = [executor.submit(_predict_matches_for_league, lg, from_date, to_date, use_snapshot)
                           for lg in league_keys]
                for fut in futures:
                    lg_matches, lg_api_error = fut.result()
                    matches.extend(lg_matches)
                    if lg_api_error and not api_error:
                        api_error = lg_api_error
            league_name = "Всички лиги"
        else:
            matches, api_error = _predict_matches_for_league(league, from_date, to_date, use_snapshot)
            league_name = get_leagues()[league]

        matches.sort(key=lambda m: m["date"])
        for _m in matches:
            _m["date_label"] = date_group_label(_m["date"])

        # Фаза N.4, етап 2 (20.08.2026): мачове, отбелязани от Дака като
        # "пропусни" (виж st.set_match_note()//match_detail), се махат от
        # основните раздели и отиват в отделен раздел "Пропуснати" по-долу -
        # чисто визуално местене, не пипа prediction/pick_pct на нищо.
        notes_map = st.get_all_match_notes()
        for _m in matches:
            _n = notes_map.get(_m["fixture_id"])
            _m["note"] = _n["note"] if _n else None
            _m["skipped"] = bool(_n and _n["skip"])
        skipped_matches = [m for m in matches if m["skipped"]]
        matches = [m for m in matches if not m["skipped"]]

        def _classify(m):
            s = m.get("status_short") or "NS"
            if s in LIVE_STATUSES:
                return "live"
            if s in FINISHED_STATUSES:
                return "finished"
            return "upcoming"

        live_matches = [m for m in matches if _classify(m) == "live"]
        upcoming_matches = [m for m in matches if _classify(m) == "upcoming"]
        finished_matches = [m for m in matches if _classify(m) == "finished"]
        for _i, _m in enumerate(upcoming_matches):
            _m["idx"] = _i

        def _group_by_league(ms):
            groups = {}
            for m in ms:
                groups.setdefault(m["league"], []).append(m)
            result = []
            for lg_key, lg_matches in groups.items():
                result.append({
                    "key": lg_key,
                    "name": ALL_LEAGUES.get(lg_key, {}).get("name", lg_key),
                    "flag": LEAGUE_FLAGS.get(lg_key, "⚽"),
                    "matches": lg_matches,
                })
            result.sort(key=lambda g: g["name"])
            return result

        live_groups = _group_by_league(live_matches)
        finished_groups = _group_by_league(finished_matches)
        skipped_groups = _group_by_league(skipped_matches)

        # Подредба по стойност/сигурност смесва мачовете от всички лиги в
        # един общ списък (groupирането по лига отпада) - само за
        # "Предстоящи", виж искането на Дака 24.08.2026. По дата си остава
        # групирано по лига, както преди.
        if sort == "date":
            upcoming_groups = _group_by_league(upcoming_matches)
            upcoming_flat = None
        else:
            upcoming_groups = None
            upcoming_flat = sorted(upcoming_matches, key=_daily_sort_key(sort), reverse=True)

        resp = make_response(render_template("daily.html", leagues=get_leagues(), selected_league=league,
                                        league_name=league_name, days_ahead=DAYS_AHEAD,
                                        api_error=api_error, snapshot_stale_warning=snapshot_stale_warning,
                                        live_groups=live_groups, upcoming_groups=upcoming_groups,
                                        upcoming_flat=upcoming_flat, upcoming_sort=sort, finished_groups=finished_groups,
                                        skipped_groups=skipped_groups, skipped_count=len(skipped_matches),
                                        live_count=len(live_matches), upcoming_count=len(upcoming_matches), finished_count=len(finished_matches),
                                        total_upcoming=len(upcoming_matches),
                                        from_value=(from_date or default_from).isoformat(),
                                        to_value=(to_date or default_to).isoformat(), active_page='daily'))
        resp.set_cookie("daily_sort", sort, max_age=31536000, samesite="Lax")
        return resp

    @daily_bp.route("/live")
    def live():
        league = request.args.get("league", "bulgaria")
        home = request.args.get("home", "")
        away = request.args.get("away", "")
        minute = int(request.args.get("minute", 45))
        hg = int(request.args.get("hg", 0))
        ag = int(request.args.get("ag", 0))
        teams, team_idx, ft_model, ht_model, h2_model = get_models(league)[:5]
        cyrillic = {t: to_cyrillic(t, league) for t in teams}
        result = None
        fixture_id = None
        if home and away:
            lam_ht, mu_ht = fl.get_lambdas(ht_model, team_idx, home, away)
            lam_2h, mu_2h = fl.get_lambdas(h2_model, team_idx, home, away)
            if lam_ht is not None:
                result = fl.live_match_probs_v2(lam_ht, mu_ht, lam_2h, mu_2h, minute, hg, ag)
                fixture_id = fetch_fixture_id_for_today(league, home, away)
        return render_template("live.html", leagues=get_leagues(), selected_league=league,
                                        teams=teams, home=home, away=away, minute=minute, hg=hg, ag=ag,
                                        result=result, cyrillic=cyrillic, fixture_id=fixture_id,
                                        today=date.today().isoformat(), active_page='live')

    app.register_blueprint(daily_bp)
