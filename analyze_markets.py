import sqlite3
conn = sqlite3.connect('predictions.db')
rows = conn.execute("""
SELECT market_code,
       SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) as won,
       SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) as lost
FROM predictions_log
WHERE status IN ('won','lost')
GROUP BY market_code
""").fetchall()
data = []
for market, won, lost in rows:
    total = won + lost
    if total >= 3:
        pct = round(100.0*won/total, 1)
        data.append((pct, market, won, lost, total))
data.sort(reverse=True)
print(f'{"Пазар":<25}{"Печ":>5}{"Губ":>5}{"Общо":>6}{"%":>7}')
for pct, market, won, lost, total in data:
    print(f'{market:<25}{won:>5}{lost:>5}{total:>6}{pct:>6.1f}%')
