import ast

with open("value_view.py") as f:
    content = f.read()

old_import = "from flask import render_template_string\n\nMIN_PCT = 25"
assert content.count(old_import) == 1, f"import anchor count: {content.count(old_import)}"
content = content.replace(old_import, "from flask import render_template_string\nfrom datetime import datetime\n\nMIN_PCT = 25", 1)

old_query = '''    conn = get_conn()
    conn.row_factory = __import__("sqlite3").Row
    rows = conn.execute("""
        SELECT id, league, fixture_id, match_date, home_team, away_team,
               market_code, pick_label, pick_pct, market_odds, our_fair_odds,
               ROUND((market_odds*1.0/our_fair_odds - 1)*100, 1) AS edge_pct
        FROM predictions_log
        WHERE market_odds IS NOT NULL AND our_fair_odds IS NOT NULL AND our_fair_odds > 0
          AND status = 'pending'
          AND pick_pct >= ? AND pick_pct <= ?
          AND (market_odds*1.0/our_fair_odds - 1)*100 >= ?
          AND (market_odds*1.0/our_fair_odds - 1)*100 <= ?
        ORDER BY edge_pct DESC
    """, (MIN_PCT, MAX_PCT, MIN_EDGE, MAX_EDGE)).fetchall()'''

new_query = '''    # match_date >= сега, НЕ само status='pending': check-results.timer върви
    # на 3 часа, затова status може все още да казва "pending" няколко часа
    # СЛЕД реалния начален час - бордът не бива да показва вече започнали
    # мачове като "възможност за залог".
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = get_conn()
    conn.row_factory = __import__("sqlite3").Row
    rows = conn.execute("""
        SELECT id, league, fixture_id, match_date, home_team, away_team,
               market_code, pick_label, pick_pct, market_odds, our_fair_odds,
               ROUND((market_odds*1.0/our_fair_odds - 1)*100, 1) AS edge_pct
        FROM predictions_log
        WHERE market_odds IS NOT NULL AND our_fair_odds IS NOT NULL AND our_fair_odds > 0
          AND status = 'pending'
          AND match_date >= ?
          AND pick_pct >= ? AND pick_pct <= ?
          AND (market_odds*1.0/our_fair_odds - 1)*100 >= ?
          AND (market_odds*1.0/our_fair_odds - 1)*100 <= ?
        ORDER BY edge_pct DESC
    """, (now_str, MIN_PCT, MAX_PCT, MIN_EDGE, MAX_EDGE)).fetchall()'''

assert content.count(old_query) == 1, f"query anchor count: {content.count(old_query)}"
content = content.replace(old_query, new_query, 1)

ast.parse(content)

with open("value_view.py", "w") as f:
    f.write(content)

print("OK - value_view.py: добавен match_date >= сега филтър")
