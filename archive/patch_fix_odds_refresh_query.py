import ast

with open("system_tracker.py") as f:
    content = f.read()

old = '''    now = datetime.now()
    cutoff = (now + timedelta(hours=hours_ahead)).strftime("%Y-%m-%d %H:%M")
    now_str = now.strftime("%Y-%m-%d %H:%M")
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT DISTINCT fixture_id, league, match_date, home_team, away_team
        FROM predictions_log
        WHERE market_odds IS NULL
          AND match_date >= ?
          AND match_date <= ?
        ORDER BY match_date ASC
    """, (now_str, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]'''

new = '''    now = datetime.now()
    cutoff = (now + timedelta(hours=hours_ahead)).strftime("%Y-%m-%d %H:%M")
    now_str = now.strftime("%Y-%m-%d %H:%M")
    # ВАЖНО: филтрираме само по пазари, за които изобщо теглим коефициент
    # (MARKET_ODDS_MAP). Иначе corners/cards/offsides/btts редовете (чийто
    # market_odds е NULL завинаги, по дизайн - REJECTED tier) биха държали
    # fixture-а в списъка безкрайно, дори след като всичко проследимо вече
    # е обновено.
    trackable = list(MARKET_ODDS_MAP.keys())
    placeholders = ",".join("?" for _ in trackable)
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"""
        SELECT DISTINCT fixture_id, league, match_date, home_team, away_team
        FROM predictions_log
        WHERE market_odds IS NULL
          AND market_code IN ({placeholders})
          AND match_date >= ?
          AND match_date <= ?
        ORDER BY match_date ASC
    """, (*trackable, now_str, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]'''

assert content.count(old) == 1, f"anchor count: {content.count(old)}"
content = content.replace(old, new, 1)

ast.parse(content)

with open("system_tracker.py", "w") as f:
    f.write(content)

print("OK - get_fixtures_needing_odds_refresh поправена (само trackable пазари)")
