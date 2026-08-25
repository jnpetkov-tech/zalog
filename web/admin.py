"""
web/admin.py — административни/диагностични маршрути, извадени от
match_predictor_app.py (ARCHITECTURE.md, Граница 4, последна част:
маршрутите излизат по blueprint-и).

Регистрира се чрез register_admin_routes(app, ctx), по същия модел като
web/results.py и web/value.py - избягва кръгов импорт с match_predictor_app.py.
Бизнес логиката зад тези маршрути (run_refresh_all, run_refresh_odds_cache,
run_refresh_injuries_cache, run_diagnostics, update_injuries_for_league,
_odds_needs_refresh) остава в match_predictor_app.py, подадена през ctx -
само тънките @app.route обвивки се преместиха тук, не логиката зад тях
(виж CLAUDE_HANDOFF.md за пълната обосновка на тази граница).
"""
from flask import Blueprint, request, redirect, url_for, render_template, send_file
import os
import glob
import io
import tarfile
from datetime import datetime
import pick_selection as ps


def register_admin_routes(app, ctx):
    ALL_LEAGUES = ctx["ALL_LEAGUES"]
    LEAGUE_FLAGS = ctx["LEAGUE_FLAGS"]
    load_active_leagues = ctx["load_active_leagues"]
    ACTIVE_LEAGUES_COOKIE = ctx["ACTIVE_LEAGUES_COOKIE"]
    run_refresh_all = ctx["run_refresh_all"]
    run_refresh_odds_cache = ctx["run_refresh_odds_cache"]
    run_refresh_injuries_cache = ctx["run_refresh_injuries_cache"]
    run_diagnostics = ctx["run_diagnostics"]
    _try_start_refresh = ctx["_try_start_refresh"]
    get_refresh_state = ctx["get_refresh_state"]
    BASE_STYLE = ctx["BASE_STYLE"]
    st = ctx["st"]
    market_label = ctx["market_label"]
    policy = ctx["policy"]
    to_cyrillic = ctx["to_cyrillic"]
    API_KEY = ctx["API_KEY"]
    BASE_URL = ctx["BASE_URL"]
    requests = ctx["requests"]

    admin_bp = Blueprint("admin", __name__)

    def render_refresh_confirmation(done, label):
        message = f"✅ {label}" if done else "🔄 Стартирано, продължава на фон"
        return render_template("refresh_confirmation.html", BASE_STYLE=BASE_STYLE, message=message)

    def render_refresh_busy():
        # Партида 8 (23.08.2026): втори клик върху /refresh_all или
        # /refresh_odds_cache_manual, докато същият вид опресняване вече
        # тече - вижте _try_start_refresh в match_predictor_app.py.
        return render_template("refresh_confirmation.html", BASE_STYLE=BASE_STYLE,
                                message="⏳ Вече тече друго опресняване – изчакай да приключи, преди да пуснеш ново.")

    def _group_matches_by_league(matches):
        groups = {}
        for m in matches:
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

    @admin_bp.route("/leagues_admin", methods=["GET", "POST"])
    def leagues_admin():
        if request.method == "POST":
            selected = [k for k in ALL_LEAGUES.keys() if request.form.get(f"league_{k}")]
            if not selected:
                selected = ["bulgaria"]
            resp = redirect(url_for("admin.leagues_admin", saved=1))
            resp.set_cookie(ACTIVE_LEAGUES_COOKIE, ",".join(selected), max_age=60*60*24*365)
            return resp
        active = load_active_leagues()
        saved = request.args.get("saved") == "1"
        return render_template("leagues_admin.html", all_leagues=ALL_LEAGUES, active=active, saved=saved,
                                        active_page='leagues_admin', refresh_state=get_refresh_state())

    @admin_bp.route("/refresh_all", methods=["POST"])
    def refresh_all_route():
        thread = _try_start_refresh("all", run_refresh_all)
        if thread is None:
            return render_refresh_busy()
        thread.join(timeout=6)
        return render_refresh_confirmation(not thread.is_alive(), "Опреснени всички лиги")

    @admin_bp.route("/refresh_odds_cache", methods=["POST"])
    def refresh_odds_cache_route():
        thread = _try_start_refresh("odds", run_refresh_odds_cache)
        return ("BUSY", 200) if thread is None else ("OK", 200)

    @admin_bp.route("/refresh_injuries_cache", methods=["POST"])
    def refresh_injuries_cache_route():
        thread = _try_start_refresh("injuries", run_refresh_injuries_cache)
        return ("BUSY", 200) if thread is None else ("OK", 200)

    @admin_bp.route("/refresh_odds_cache_manual", methods=["POST"])
    def refresh_odds_cache_manual_route():
        thread = _try_start_refresh("odds", run_refresh_odds_cache)
        if thread is None:
            return render_refresh_busy()
        thread.join(timeout=6)
        return render_refresh_confirmation(not thread.is_alive(), "Готово")

    @admin_bp.route("/refresh_status")
    def refresh_status():
        try:
            with open("refresh_log.txt", encoding="utf-8") as f:
                content = f.read()
            content = "\n".join(content.splitlines()[-200:])
        except FileNotFoundError:
            content = "Все още няма стартирано опресняване."

        return render_template("refresh_status.html", BASE_STYLE=BASE_STYLE, content=content)
        # Мъртъв/недостижим код по-долу (от преди Партида 5) - никога не се изпълнява
        # (след безусловен return по-горе), пренесен непипнат за вярност на "чисто
        # преместване", виж CLAUDE_HANDOFF.md, раздела за Партида 5, стъпка 4.
        return render_template_string(LEAGUES_ADMIN_TEMPLATE, all_leagues=ALL_LEAGUES, active=active, saved=saved, active_page='leagues_admin')
        active = load_active_leagues()
        return render_template_string(LEAGUES_ADMIN_TEMPLATE, all_leagues=ALL_LEAGUES, active=active, saved=saved, active_page='leagues_admin')

    @admin_bp.route("/system_check")
    def system_check():
        predictions = st.list_predictions()

        won = sum(1 for p in predictions if p["status"] == "won")
        lost = sum(1 for p in predictions if p["status"] == "lost")
        pending = sum(1 for p in predictions if p["status"] == "pending")
        total_settled = won + lost
        win_rate = (won / total_settled * 100) if total_settled else None
        overall = {"won": won, "lost": lost, "pending": pending, "win_rate": win_rate}

        by_market = st.get_stats_by_market()
        by_market.sort(key=lambda m: (m["win_rate"] is None, -(m["win_rate"] or 0)))
        by_league = st.get_stats_by_league()
        by_league.sort(key=lambda l: (l["win_rate"] is None, -(l["win_rate"] or 0)))
        for m in by_market:
            m["label"] = market_label(m["market_code"])
        for l in by_league:
            l["display_name"] = ALL_LEAGUES.get(l["league"], {}).get("name", l["league"])

        market_min_sample = [m for m in by_market if (m["won"] + m["lost"]) >= 10]
        best_markets = market_min_sample[:5]
        worst_markets = list(reversed(market_min_sample[-5:])) if len(market_min_sample) > 5 else []

        league_options = sorted({(l["league"], l["display_name"]) for l in by_league}, key=lambda x: x[1])
        market_options = sorted({(m["market_code"], m["label"]) for m in by_market}, key=lambda x: x[1])

        filter_league = request.args.get("f_league", "")
        filter_market = request.args.get("f_market", "")
        filter_status = request.args.get("f_status", "")
        search_q = request.args.get("q", "").strip()

        filtered = predictions
        if filter_league:
            filtered = [p for p in filtered if p["league"] == filter_league]
        if filter_market:
            filtered = [p for p in filtered if p["market_code"] == filter_market]
        if filter_status:
            filtered = [p for p in filtered if p["status"] == filter_status]

        match_groups = {}
        for p in filtered:
            key = p["fixture_id"]
            match_groups.setdefault(key, {"fixture_id": key, "date": p["match_date"], "home": p["home_team"],
                                            "away": p["away_team"], "league": p["league"], "predictions": []})
            match_groups[key]["predictions"].append(p)

        all_matches = list(match_groups.values())
        for m in all_matches:
            m["pending_count"] = sum(1 for p in m["predictions"] if p["status"] == "pending")
            # Стъпка 1 (PREUSTROYSTVO.md, 25.08.2026): единствената функция за
            # "коя е прогнозата за мача" - виж pick_selection.top_pick_for_match()
            # докстринга. Може да върне None, ако нищо публикуемо е логнато за
            # мача (напр. само corners/cards - виж Находка 3 от одита) -
            # преди това пропадаше до тях мълчаливо.
            m["top_pred"] = ps.top_pick_for_match(m["predictions"], m["league"], policy)
            m["other_count"] = len(m["predictions"]) - (1 if m["top_pred"] else 0)
            m["home_cy"] = to_cyrillic(m["home"], m["league"])
            m["away_cy"] = to_cyrillic(m["away"], m["league"])
            m["actual_hg"] = next((p["actual_home_goals"] for p in m["predictions"] if p["actual_home_goals"] is not None), None)
            m["actual_ag"] = next((p["actual_away_goals"] for p in m["predictions"] if p["actual_away_goals"] is not None), None)

        if search_q:
            q_lower = search_q.lower()
            all_matches = [m for m in all_matches if q_lower in m["home_cy"].lower() or q_lower in m["away_cy"].lower()
                           or q_lower in m["home"].lower() or q_lower in m["away"].lower()]

        pending_all = sorted([m for m in all_matches if m["pending_count"] > 0], key=lambda m: m["date"])
        completed_all = sorted([m for m in all_matches if m["pending_count"] == 0], key=lambda m: m["date"], reverse=True)

        PAGE_SIZE = 25

        total_pending = len(pending_all)
        total_pending_pages = max(1, (total_pending + PAGE_SIZE - 1) // PAGE_SIZE)
        try:
            ppage = max(1, int(request.args.get("ppage", "1")))
        except ValueError:
            ppage = 1
        ppage = min(ppage, total_pending_pages)
        pstart = (ppage - 1) * PAGE_SIZE
        pending_matches = pending_all[pstart:pstart + PAGE_SIZE]

        total_completed = len(completed_all)
        total_pages = max(1, (total_completed + PAGE_SIZE - 1) // PAGE_SIZE)
        try:
            page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            page = 1
        page = min(page, total_pages)
        start = (page - 1) * PAGE_SIZE
        completed_matches = completed_all[start:start + PAGE_SIZE]

        pending_groups = _group_matches_by_league(pending_matches)
        completed_groups = _group_matches_by_league(completed_matches)
        return render_template("system_check.html", overall=overall, by_market=by_market,
                                        by_league=by_league, pending_matches=pending_matches,
                                        completed_matches=completed_matches, cyrillic=to_cyrillic,
                                        pending_groups=pending_groups, completed_groups=completed_groups,
                                        filter_league=filter_league, filter_market=filter_market, filter_status=filter_status,
                                        league_options=league_options, market_options=market_options,
                                        page=page, total_pages=total_pages, total_completed=total_completed,
                                        ppage=ppage, total_pending_pages=total_pending_pages, total_pending=total_pending,
                                        best_markets=best_markets, worst_markets=worst_markets, search_q=search_q, active_page='system_check')

    @admin_bp.route("/system_check_results", methods=["POST"])
    def system_check_results_route():
        st.check_results(API_KEY, BASE_URL, requests)
        return redirect(url_for("admin.system_check"))

    @admin_bp.route("/match_result")
    def match_result():
        fixture_id = request.args.get("fixture_id")
        if not fixture_id:
            return redirect(url_for("admin.system_check"))
        predictions = st.get_predictions_for_fixture(int(fixture_id))
        if not predictions:
            return redirect(url_for("admin.system_check"))
        first = predictions[0]
        league = first["league"]
        home_cy = to_cyrillic(first["home_team"], league)
        away_cy = to_cyrillic(first["away_team"], league)
        actual_hg = next((p["actual_home_goals"] for p in predictions if p["actual_home_goals"] is not None), None)
        actual_ag = next((p["actual_away_goals"] for p in predictions if p["actual_away_goals"] is not None), None)
        for p in predictions:
            p["label"] = market_label(p["market_code"])
        won_count = sum(1 for p in predictions if p["status"] == "won")
        lost_count = sum(1 for p in predictions if p["status"] == "lost")
        league_name = ALL_LEAGUES.get(league, {}).get("name", league)
        return render_template("match_result.html", predictions=predictions, home_cy=home_cy, away_cy=away_cy,
                                        league_name=league_name, match_date=first["match_date"],
                                        actual_hg=actual_hg, actual_ag=actual_ag, won_count=won_count, lost_count=lost_count,
                                        active_page='system_check')

    @admin_bp.route("/diagnostics")
    def diagnostics():
        results = run_diagnostics()
        return render_template("diagnostics.html", results=results, active_page='diagnostics')

    @admin_bp.route("/diagnostics/backup")
    def diagnostics_backup():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for db_file in ["predictions.db", "bets.db"]:
                if os.path.exists(db_file):
                    tar.add(db_file)
            for csv_file in glob.glob("*_merged_full.csv"):
                tar.add(csv_file)
        buf.seek(0)
        return send_file(buf, mimetype="application/gzip", as_attachment=True,
                          download_name=f"sportbg_backup_{ts}.tar.gz")

    app.register_blueprint(admin_bp)
