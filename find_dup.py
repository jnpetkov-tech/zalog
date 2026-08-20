import sqlite3

conn = sqlite3.connect("predictions.db")
conn.row_factory = sqlite3.Row

dups = conn.execute("""
    SELECT fixture_id, market_code, COUNT(*) k
    FROM predictions_log GROUP BY fixture_id, market_code HAVING k > 1
""").fetchall()

print(f"Намерени {len(dups)} дублирани комбинации:")
for d in dups:
    print(f"  fixture_id={d['fixture_id']} market_code={d['market_code']} count={d['k']}")
    rows = conn.execute("""
        SELECT id, logged_at, league, home_team, away_team, pick_pct, status, market_odds
        FROM predictions_log WHERE fixture_id=? AND market_code=?
        ORDER BY id
    """, (d['fixture_id'], d['market_code'])).fetchall()
    for r in rows:
        print(f"    id={r['id']} logged_at={r['logged_at']} league={r['league']} "
              f"{r['home_team']}-{r['away_team']} pick_pct={r['pick_pct']} "
              f"status={r['status']} market_odds={r['market_odds']}")

conn.close()
