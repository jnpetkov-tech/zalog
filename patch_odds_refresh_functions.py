import ast

with open("system_tracker.py") as f:
    content = f.read()

old_import = "from datetime import datetime\n"
assert content.count(old_import) == 1, f"import anchor count: {content.count(old_import)}"
content = content.replace(old_import, "from datetime import datetime, timedelta\n", 1)

old_anchor = '''def already_logged(fixture_id):
    conn = get_conn()
    existing = conn.execute("SELECT id FROM predictions_log WHERE fixture_id=? LIMIT 1", (fixture_id,)).fetchone()
    conn.close()
    return existing is not None


def log_all_markets(league, fixture_id, match_date, home, away, groups, real_odds=None):'''

new_functions = '''def already_logged(fixture_id):
    conn = get_conn()
    existing = conn.execute("SELECT id FROM predictions_log WHERE fixture_id=? LIMIT 1", (fixture_id,)).fetchone()
    conn.close()
    return existing is not None
def get_fixtures_needing_odds_refresh(hours_ahead=48):
    """НОВО (Фаза F0): намира fixture_id-та, логнати преди коефициентите
    да са били налични (market_odds IS NULL), чийто начален час е в
    близките hours_ahead часа - прозорецът, в който букмейкърите обичайно
    вече имат котировки. Използва се от refresh_pending_odds.py, НЕ от
    nightly_snapshot.py - целенасочено, за да не умножава API заявките за
    целия 7-дневен прозорец всяка нощ."""
    now = datetime.now()
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
    return [dict(r) for r in rows]
def update_odds_for_fixture(fixture_id, real_odds):
    """НОВО (Фаза F0): обновява market_odds за вече логнати редове на
    fixture_id, при които все още е NULL. НИКОГА не презаписва
    съществуваща стойност и НИКОГА не пипа pick_pct/pick_label -
    прогнозата остава заключена към момента на първото логване, само
    коефициентът се допълва, когато стане наличен."""
    if not real_odds:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    updated = 0
    rows = conn.execute(
        "SELECT id, market_code FROM predictions_log WHERE fixture_id=? AND market_odds IS NULL",
        (fixture_id,)
    ).fetchall()
    for row_id, market_code in rows:
        odds_key = MARKET_ODDS_MAP.get(market_code)
        odds_val = real_odds.get(odds_key) if odds_key else None
        if odds_val is None:
            continue
        cur.execute(
            "UPDATE predictions_log SET market_odds=? WHERE id=? AND market_odds IS NULL",
            (odds_val, row_id)
        )
        updated += cur.rowcount
    conn.commit()
    conn.close()
    return updated


def log_all_markets(league, fixture_id, match_date, home, away, groups, real_odds=None):'''

assert content.count(old_anchor) == 1, f"function anchor count: {content.count(old_anchor)}"
content = content.replace(old_anchor, new_functions, 1)

ast.parse(content)

with open("system_tracker.py", "w") as f:
    f.write(content)

print("OK - system_tracker.py патчнат успешно")
