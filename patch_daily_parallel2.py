import ast

PATH = "match_predictor_app.py"

with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

assert lines[916].strip() == '@app.route("/daily")', f"Line 917 mismatch: {lines[916]!r}"
assert "to_value=(to_date or default_to).isoformat())" in lines[952], f"Line 953 mismatch: {lines[952]!r}"

new_block = '''@app.route("/daily")
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
        league_keys = list(get_leagues().keys())
        with ThreadPoolExecutor(max_workers=min(8, len(league_keys) or 1)) as executor:
            futures = [executor.submit(_predict_matches_for_league, lg, from_date, to_date) for lg in league_keys]
            for fut in futures:
                lg_matches, lg_api_error = fut.result()
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

new_lines = lines[:916] + [new_block] + lines[953:]

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

ast.parse(open(PATH, encoding="utf-8").read())
print("OK - паралелизацията е добавена, синтаксисът е валиден")
