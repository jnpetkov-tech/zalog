import ast

PATH = "match_predictor_app.py"

with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

assert lines[860].strip() == "def daily():", f"Line 861 mismatch: {lines[860]!r}"
assert "to_value=(to_date or default_to).isoformat())" in lines[938], f"Line 939 mismatch: {lines[938]!r}"

new_block = '''def _predict_matches_for_league(league, from_date, to_date):
    fixtures, api_error = fetch_upcoming_fixtures(league, from_date, to_date)
    (teams, team_idx, ft_model, ht_model, h2_model, corners_model, cards_model,
     offsides_model, recent_model, recent_matches_count, has_injuries) = get_models(league)

    matches = []
    for f in fixtures:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        if home not in team_idx or away not in team_idx:
            continue
        match_date = f["fixture"]["date"][:16].replace("T", " ")
        fixture_id = f["fixture"]["id"]

        home_inj, away_inj = 0, 0
        inj_note = None
        if has_injuries:
            home_inj, away_inj, ok = fetch_fixture_injuries(fixture_id)
            if ok:
                inj_note = f"Контузии: {to_cyrillic(home, league)} {home_inj}, {to_cyrillic(away, league)} {away_inj}"
            else:
                inj_note = "Няма данни за контузии за този мач (все още)"

        lam, mu = get_ft_lambdas(ft_model, team_idx, home, away, home_inj, away_inj)
        lam_ht, mu_ht = fl.get_lambdas(ht_model, team_idx, home, away)
        lam_2h, mu_2h = fl.get_lambdas(h2_model, team_idx, home, away)
        ht_ft_probs = predict_ht_ft(lam_ht, mu_ht, lam_2h, mu_2h)
        pick, pct, code = top_pick_with_code(lam, mu, home, away, ht_ft_probs)
        groups_for_log, _ = compute_grouped_markets(league, home, away, home_inj, away_inj)
        if groups_for_log and not st.already_logged(fixture_id):
            real_odds_for_log = fetch_fixture_odds(fixture_id)
            st.log_all_markets(league, fixture_id, match_date, home, away, groups_for_log, real_odds=real_odds_for_log)
            st.log_all_markets(league, fixture_id, match_date, home, away, groups_for_log)

        try:
            kickoff = datetime.fromisoformat(f["fixture"]["date"])
            minutes_to_kickoff = (kickoff - datetime.now(kickoff.tzinfo)).total_seconds() / 60
        except Exception:
            minutes_to_kickoff = 9999

        lineups_confirmed = False
        if 0 <= minutes_to_kickoff <= 60:
            lineups_confirmed = fetch_lineups_available(fixture_id)
        matches.append({
            "date": match_date, "home": home, "away": away,
            "home_cy": to_cyrillic(home, league), "away_cy": to_cyrillic(away, league),
            "home_logo": f["teams"]["home"].get("logo"), "away_logo": f["teams"]["away"].get("logo"),
            "pick": pick, "pct": pct, "code": code, "odds": fair_odds(pct),
            "fixture_id": fixture_id, "inj_note": inj_note,
            "lineups_confirmed": lineups_confirmed,
            "league": league, "league_name": ALL_LEAGUES[league]["name"],
        })
    return matches, api_error


@app.route("/daily")
def daily():
    league = request.args.get("league", "bulgaria")
    from_str = request.args.get("from_date", "")
    to_str = request.args.get("to_date", "")

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

    matches = []
    api_error = None
    if league == "all":
        for lg in get_leagues().keys():
            lg_matches, lg_api_error = _predict_matches_for_league(lg, from_date, to_date)
            matches.extend(lg_matches)
            if lg_api_error and not api_error:
                api_error = lg_api_error
        league_name = "Всички лиги"
    else:
        matches, api_error = _predict_matches_for_league(league, from_date, to_date)
        league_name = get_leagues()[league]

    matches.sort(key=lambda m: m["date"])

    return render_template_string(DAILY_TEMPLATE, leagues=get_leagues(), selected_league=league,
                                    league_name=league_name, matches=matches, days_ahead=DAYS_AHEAD,
                                    api_error=api_error,
                                    from_value=(from_date or default_from).isoformat(),
                                    to_value=(to_date or default_to).isoformat())
'''

new_lines = lines[:860] + [new_block] + lines[939:]

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

ast.parse(open(PATH, encoding="utf-8").read())
print("OK - daily() заменена успешно, синтаксисът е валиден")
