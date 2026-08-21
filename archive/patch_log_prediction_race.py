import ast

with open("system_tracker.py", "r") as f:
    content = f.read()

old = '''def log_prediction(league, fixture_id, match_date, home, away, market_code, pick_label, pick_pct,
                    market_odds=None, our_fair_odds=None):
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM predictions_log WHERE fixture_id=? AND market_code=?",
        (fixture_id, market_code)
    ).fetchone()
    if existing:
        conn.close()
        return existing[0]
    cur = conn.execute(
        """INSERT INTO predictions_log (logged_at, league, fixture_id, match_date, home_team, away_team,
           market_code, pick_label, pick_pct, market_odds, our_fair_odds)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(), league, fixture_id, match_date, home, away,
         market_code, pick_label, pick_pct, market_odds, our_fair_odds)
    )
    conn.commit()
    log_id = cur.lastrowid
    conn.close()
    return log_id'''

new = '''def log_prediction(league, fixture_id, match_date, home, away, market_code, pick_label, pick_pct,
                    market_odds=None, our_fair_odds=None):
    # 2026-08-10: INSERT OR IGNORE вместо SELECT-then-INSERT - старият модел
    # имаше TOCTOU race при паралелни заявки (два thread-а минават SELECT
    # проверката преди първият да успее да INSERT-не), причинил реален
    # дубликат на живо (fixture_id=1551072, dc_1x). Сега, с UNIQUE индекс
    # idx_predictions_fixture_market, race-ът е безопасен - вторият опит
    # просто се игнорира на ниво SQLite, атомарно.
    conn = get_conn()
    cur = conn.execute(
        """INSERT OR IGNORE INTO predictions_log (logged_at, league, fixture_id, match_date, home_team, away_team,
           market_code, pick_label, pick_pct, market_odds, our_fair_odds)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(), league, fixture_id, match_date, home, away,
         market_code, pick_label, pick_pct, market_odds, our_fair_odds)
    )
    conn.commit()
    if cur.rowcount == 0:
        existing = conn.execute(
            "SELECT id FROM predictions_log WHERE fixture_id=? AND market_code=?",
            (fixture_id, market_code)
        ).fetchone()
        conn.close()
        return existing[0] if existing else None
    log_id = cur.lastrowid
    conn.close()
    return log_id'''

assert content.count(old) == 1, f"anchor count={content.count(old)}"
content = content.replace(old, new)

ast.parse(content)

with open("system_tracker.py", "w") as f:
    f.write(content)

print("OK - log_prediction race condition fixed (INSERT OR IGNORE).")
