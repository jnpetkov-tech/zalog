"""
web/match.py — маршрути за детайли на мач и залози (/match_detail,
/save_match_note, /place_bet_market, /place_bet_single/<idx>, /place_combo,
/check_results, /my_bets), извадени от match_predictor_app.py
(ARCHITECTURE.md, Граница 4, последна част: маршрутите излизат по
blueprint-и).

Регистрира се чрез register_match_routes(app, ctx), по същия модел като
web/results.py, web/value.py, web/admin.py, web/daily.py - избягва кръгов
импорт с match_predictor_app.py. Модел/бизнес логиката (get_models,
compute_grouped_markets, fair_odds) остава в match_predictor_app.py,
подадена през ctx.
"""
from flask import Blueprint, request, redirect, url_for, render_template
from datetime import datetime
from scipy.stats import poisson


def register_match_routes(app, ctx):
    get_models = ctx["get_models"]
    st = ctx["st"]
    fetch_fixture_injuries = ctx["fetch_fixture_injuries"]
    fetch_fixture_odds = ctx["fetch_fixture_odds"]
    fetch_lineups_available = ctx["fetch_lineups_available"]
    fetch_fixture_predictions = ctx["fetch_fixture_predictions"]
    fetch_team_recent_form = ctx["fetch_team_recent_form"]
    fetch_league_standings_for_teams = ctx["fetch_league_standings_for_teams"]
    fetch_fixture_lineups_full = ctx["fetch_fixture_lineups_full"]
    to_cyrillic = ctx["to_cyrillic"]
    ALL_LEAGUES = ctx["ALL_LEAGUES"]
    compute_grouped_markets = ctx["compute_grouped_markets"]
    fair_odds = ctx["fair_odds"]
    pp = ctx["pp"]
    bt = ctx["bt"]
    API_KEY = ctx["API_KEY"]
    BASE_URL = ctx["BASE_URL"]
    requests = ctx["requests"]

    match_bp = Blueprint("match", __name__)

    @match_bp.route("/match_detail")
    def match_detail():
        league = request.args.get("league", "bulgaria")
        fixture_id = request.args.get("fixture_id")
        home = request.args.get("home")
        away = request.args.get("away")
        match_date = request.args.get("date")
        home_inj, away_inj = 0, 0
        inj_note = None
        has_injuries = get_models(league)[10]
        if fixture_id:
            # Фаза N.3 (20.08.2026): кеш-първо (st.get_cached_injuries), само при
            # "студен"/изтекъл кеш живо API извикване - същия модел като хотфикса
            # за /daily (12.08.2026). Показваме контузиите на страницата за
            # ВСИЧКИ лиги (чисто информативно), но подаваме числата на модела по-
            # долу само ако has_injuries е вярно - без промяна в поведението на
            # самата прогноза спрямо преди тази промяна.
            cached_inj = st.get_cached_injuries(int(fixture_id))
            if cached_inj is not None:
                fetched_home, fetched_away, ok = cached_inj
            else:
                fetched_home, fetched_away, ok = fetch_fixture_injuries(int(fixture_id))
                st.set_cached_injuries(int(fixture_id), fetched_home, fetched_away, ok)
            if ok:
                inj_note = f"Контузии: {to_cyrillic(home, league)} {fetched_home}, {to_cyrillic(away, league)} {fetched_away}"
            else:
                inj_note = "Няма данни за контузии за този мач (все още)"
            if has_injuries:
                home_inj, away_inj = fetched_home, fetched_away
        real_odds = None
        lineups_confirmed = False
        api_predictions = None
        player_props_data = None
        form_standings = None
        if fixture_id:
            real_odds = fetch_fixture_odds(int(fixture_id))
            lineups_confirmed = fetch_lineups_available(int(fixture_id))
            api_predictions = fetch_fixture_predictions(int(fixture_id))
            # Фаза P.1 (21.08.2026): последни 5 мача + класиране - кеш-първо
            # (st.get_cached_form_standings), същия модел като инжуриите (N.3).
            # team id-тата идват безплатно от api_predictions по-горе - без тях
            # (напр. API-Football грешка/квота) просто не показваме секцията.
            cached_fs = st.get_cached_form_standings(int(fixture_id))
            if cached_fs is not None:
                form_standings = cached_fs
            elif api_predictions and api_predictions.get("home_id") and api_predictions.get("away_id"):
                try:
                    match_dt = datetime.strptime((match_date or "")[:10], "%Y-%m-%d")
                except (ValueError, TypeError):
                    match_dt = datetime.now()
                season = match_dt.year if match_dt.month >= 7 else match_dt.year - 1
                league_id = ALL_LEAGUES.get(league, {}).get("id")
                if league_id:
                    home_id, away_id = api_predictions["home_id"], api_predictions["away_id"]
                    home_last5 = fetch_team_recent_form(home_id, league_id, season, int(fixture_id))
                    away_last5 = fetch_team_recent_form(away_id, league_id, season, int(fixture_id))
                    standings = fetch_league_standings_for_teams(league_id, season, home_id, away_id)
                    form_standings = {
                        "home_last5": home_last5, "away_last5": away_last5,
                        "home_standing": standings["home"] if standings else None,
                        "away_standing": standings["away"] if standings else None,
                        "total_teams": standings["total_teams"] if standings else None,
                    }
                    st.set_cached_form_standings(int(fixture_id), form_standings)
        groups, extra_info = compute_grouped_markets(league, home, away, home_inj, away_inj, real_odds=real_odds)
        if lineups_confirmed and extra_info:
            try:
                lineup_full = fetch_fixture_lineups_full(int(fixture_id))
                if lineup_full:
                    lam, mu = extra_info[0], extra_info[1]
                    p_at_least_one_goal = 1 - poisson.pmf(0, lam) * poisson.pmf(0, mu)
                    player_props_data = pp.predict_player_props(league, lineup_full, p_at_least_one_goal)
            except Exception:
                player_props_data = None
        if groups:
            new_groups = []
            for title, items, has_form in groups:
                new_items = [row + (fair_odds(row[1]),) for row in items]
                new_groups.append((title, new_items, has_form))
            groups = new_groups
        home_cy, away_cy = to_cyrillic(home, league), to_cyrillic(away, league)
        # Фаза N.4, етап 1 (20.08.2026): виж st.get_match_note() - ръчна бележка
        # + флаг "пропусни", редактирани направо тук, на страницата на мача.
        match_note = st.get_match_note(int(fixture_id)) if fixture_id else None
        return render_template("match_detail.html", groups=groups, extra_info=extra_info,
                                        home=home, away=away, home_cy=home_cy, away_cy=away_cy,
                                        date=match_date, fixture_id=fixture_id, selected_league=league,
                                        real_odds=real_odds, lineups_confirmed=lineups_confirmed, inj_note=inj_note,
                                        match_note=match_note,
                                        api_predictions=api_predictions, player_props=player_props_data,
                                        form_standings=form_standings, active_page='daily')

    @match_bp.route("/save_match_note", methods=["POST"])
    def save_match_note_route():
        # Фаза N.4, етап 1-2 (20.08.2026): ръчна бележка/контекст + флаг
        # "пропусни мача" - виж st.set_match_note(). Категорична забрана,
        # записана изрично от Дака: това НИКОГА не пипа pick_pct/прогнозата,
        # чисто информативно + изключва мача от препоръчания списък на /daily
        # (мести се в отделен раздел "Пропуснати", виж daily()).
        fixture_id = int(request.form["fixture_id"])
        note = request.form.get("note", "").strip() or None
        skip = bool(request.form.get("skip"))
        st.set_match_note(fixture_id, note, skip)
        return redirect(url_for("match.match_detail", league=request.form["league"],
                                  fixture_id=fixture_id, home=request.form["home"],
                                  away=request.form["away"], date=request.form["date"]))

    @match_bp.route("/place_bet_market", methods=["POST"])
    def place_bet_market_route():
        bt.place_bet(
            request.form["league"], int(request.form["fixture_id"]), request.form["date"],
            request.form["home"], request.form["away"], request.form["market_code"],
            request.form["pick_label"], float(request.form["pick_pct"]),
        )
        return redirect(url_for("match.match_detail", league=request.form["league"],
                                  fixture_id=request.form["fixture_id"], home=request.form["home"],
                                  away=request.form["away"], date=request.form["date"]))

    @match_bp.route("/place_bet_single/<int:idx>", methods=["POST"])
    def place_bet_single_route(idx):
        bt.place_bet(
            request.form[f"league_{idx}"], int(request.form[f"fixture_id_{idx}"]),
            request.form[f"date_{idx}"], request.form[f"home_{idx}"], request.form[f"away_{idx}"],
            request.form[f"code_{idx}"], request.form[f"pick_{idx}"], float(request.form[f"pct_{idx}"]),
        )
        league = request.form.get(f"league_{idx}", "bulgaria")
        return redirect(url_for("daily.daily", league=league))

    @match_bp.route("/place_combo", methods=["POST"])
    def place_combo_route():
        total = int(request.form["total"])
        selected = [i for i in range(total) if request.form.get(f"sel_{i}")]
        if selected:
            combo_id = bt.next_combo_id()
            for i in selected:
                bt.place_bet(
                    request.form[f"league_{i}"], int(request.form[f"fixture_id_{i}"]),
                    request.form[f"date_{i}"], request.form[f"home_{i}"], request.form[f"away_{i}"],
                    request.form[f"code_{i}"], request.form[f"pick_{i}"], float(request.form[f"pct_{i}"]),
                    combo_id=combo_id,
                )
        league = request.form.get("league_0", "bulgaria")
        return redirect(url_for("daily.daily", league=league))

    @match_bp.route("/check_results", methods=["POST"])
    def check_results_route():
        bt.check_results(API_KEY, BASE_URL, requests)
        return redirect(url_for("match.my_bets"))

    @match_bp.route("/my_bets")
    def my_bets():
        bets = bt.list_bets()
        stats = bt.get_stats()

        singles = [b for b in bets if b["combo_id"] is None]

        match_groups = {}
        for b in singles:
            key = (b["match_date"], b["home_team"], b["away_team"])
            match_groups.setdefault(key, []).append(b)

        single_matches = []
        for (mdate, home, away), group_bets in match_groups.items():
            group_bets.sort(key=lambda x: -x["pick_pct"])
            won = sum(1 for x in group_bets if x["status"] == "won")
            lost = sum(1 for x in group_bets if x["status"] == "lost")
            pending = sum(1 for x in group_bets if x["status"] == "pending")
            single_matches.append({
                "date": mdate, "home": home, "away": away, "bets": group_bets,
                "won": won, "lost": lost, "pending": pending,
            })
        single_matches.sort(key=lambda m: m["date"], reverse=True)
        active_matches = [m for m in single_matches if m["pending"] > 0]
        completed_matches = [m for m in single_matches if m["pending"] == 0]

        combo_groups = {}
        for b in bets:
            if b["combo_id"] is not None:
                combo_groups.setdefault(b["combo_id"], []).append(b)

        combos = []
        for combo_id, legs in sorted(combo_groups.items(), key=lambda x: -x[0]):
            combined_pct = 1.0
            for leg in legs:
                combined_pct *= leg["pick_pct"] / 100
            combined_pct *= 100

            statuses = [leg["status"] for leg in legs]
            if "lost" in statuses:
                combo_status = "lost"
            elif all(s == "won" for s in statuses):
                combo_status = "won"
            else:
                combo_status = "pending"

            combos.append({"combo_id": combo_id, "legs": legs, "combined_pct": combined_pct, "status": combo_status})

        active_combos = [c for c in combos if c["status"] == "pending"]
        completed_combos = [c for c in combos if c["status"] != "pending"]

        return render_template("my_bets.html",
                                        active_matches=active_matches, completed_matches=completed_matches,
                                        active_combos=active_combos, completed_combos=completed_combos,
                                        stats=stats, cyrillic=to_cyrillic, active_page='my_bets')

    app.register_blueprint(match_bp)
