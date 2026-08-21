import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old_block = '''        cached_odds = st.get_cached_odds(fixture_id)
        pick, pct, code, used_market = top_pick_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=cached_odds)
        groups_for_log, _ = compute_grouped_markets(league, home, away, home_inj, away_inj)'''

new_block = '''        cached_odds = st.get_cached_odds(fixture_id)
        # Фаза F3: една заявка към top_picks_with_code() вместо отделни
        # извиквания на top_pick_with_code() + top_picks_with_code() -
        # picks_raw[0] е ГАРАНТИРАНО идентичен на старото top_pick_with_code()
        # (доказано локално с 300 случайни случая преди деплой), затова
        # комбинираната колонка/залог логиката по-долу (която разчита на
        # единичните pick/pct/code) остава непроменена.
        picks_raw, used_market = top_picks_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=cached_odds, n=3)
        pick, pct, code = picks_raw[0]
        picks_list = [
            {"label": p_label, "pct": p_pct, "code": p_code, "odds": fair_odds(p_pct)}
            for p_label, p_pct, p_code in picks_raw
        ]
        groups_for_log, _ = compute_grouped_markets(league, home, away, home_inj, away_inj)'''

assert content.count(old_block) == 1, f"wiring anchor count: {content.count(old_block)}"
content = content.replace(old_block, new_block, 1)

old_append = '''            "pick": pick, "pct": pct, "code": code, "odds": fair_odds(pct),
            "fixture_id": fixture_id, "inj_note": inj_note,'''
new_append = '''            "pick": pick, "pct": pct, "code": code, "odds": fair_odds(pct), "picks": picks_list,
            "fixture_id": fixture_id, "inj_note": inj_note,'''
assert content.count(old_append) == 1, f"append anchor count: {content.count(old_append)}"
content = content.replace(old_append, new_append, 1)

old_noteam = '''                "pick": "Няма прогноза (нов отбор)", "pct": None, "code": None, "odds": None,
                "fixture_id": fixture_id, "inj_note": None,'''
new_noteam = '''                "pick": "Няма прогноза (нов отбор)", "pct": None, "code": None, "odds": None, "picks": [],
                "fixture_id": fixture_id, "inj_note": None,'''
assert content.count(old_noteam) == 1, f"no-team anchor count: {content.count(old_noteam)}"
content = content.replace(old_noteam, new_noteam, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - _predict_matches_for_league() закачен за top_picks_with_code(n=3), picks добавени към match dict")
