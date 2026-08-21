import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old = '''        if groups_for_log and not st.already_logged(fixture_id):
            real_odds_for_log = fetch_fixture_odds(fixture_id)
            st.log_all_markets(league, fixture_id, match_date, home, away, groups_for_log, real_odds=real_odds_for_log)
            st.log_all_markets(league, fixture_id, match_date, home, away, groups_for_log)'''

new = '''        if groups_for_log and not st.already_logged(fixture_id):
            real_odds_for_log = fetch_fixture_odds(fixture_id)
            st.log_all_markets(league, fixture_id, match_date, home, away, groups_for_log, real_odds=real_odds_for_log)'''

assert content.count(old) == 1, f"anchor count: {content.count(old)}"
content = content.replace(old, new, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - match_predictor_app.py патчнат успешно (премахнат дублиращ log_all_markets извикване)")
