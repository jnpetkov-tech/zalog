import sqlite3
conn = sqlite3.connect('predictions.db')

n_settled_fixtures = conn.execute("""
SELECT COUNT(DISTINCT fixture_id) FROM predictions_log WHERE status IN ('won','lost')
""").fetchone()[0]

n_pending_fixtures = conn.execute("""
SELECT COUNT(DISTINCT fixture_id) FROM predictions_log WHERE status = 'pending'
""").fetchone()[0]

date_range = conn.execute("""
SELECT MIN(match_date), MAX(match_date) FROM predictions_log WHERE status IN ('won','lost')
""").fetchone()

print(f"Уникални мачове с приключили прогнози: {n_settled_fixtures}")
print(f"Уникални мачове с чакащи прогнози: {n_pending_fixtures}")
print(f"Диапазон на дати за приключилите: {date_range[0]} -> {date_range[1]}")

print()
print("По лига (приключили мачове):")
rows = conn.execute("""
SELECT league, COUNT(DISTINCT fixture_id) FROM predictions_log WHERE status IN ('won','lost') GROUP BY league ORDER BY 2 DESC
""").fetchall()
for league, cnt in rows:
    print(f"  {league}: {cnt} мача")
