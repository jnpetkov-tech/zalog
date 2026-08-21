"""
Фаза F1: read-only диагностика на реалното разпределение на edge -
определя праговете (probability band, edge threshold) за стойностния
борд (Фаза F2) от РЕАЛНИ данни, не от предположения. Нищо не пише в
базата, нищо не пипа модела.

Edge = (market_odds / our_fair_odds - 1) * 100. our_fair_odds вече е
записан в predictions_log в момента на логването (100/pick_pct), затова
не се преизчислява тук.
"""
import sqlite3

conn = sqlite3.connect("predictions.db")
conn.row_factory = sqlite3.Row

GRP = """CASE
    WHEN market_code IN ('home_win','draw','away_win') THEN '1_1X2'
    WHEN market_code IN ('over25','under25') THEN '2_OU25'
    WHEN market_code LIKE 'home_over%' OR market_code LIKE 'home_under%'
      OR market_code LIKE 'away_over%' OR market_code LIKE 'away_under%' THEN '3_TeamTotal'
    WHEN market_code LIKE 'htft%' THEN '4_HTFT'
    WHEN market_code LIKE 'dc_%' THEN '5_DoubleChance'
    WHEN market_code LIKE 'corners%' OR market_code LIKE 'cards%'
      OR market_code LIKE 'offsides%' OR market_code LIKE 'btts%' THEN '6_JUNK'
    ELSE '7_Other' END"""

PBAND = """CASE
    WHEN pick_pct < 25 THEN '1_под25'
    WHEN pick_pct < 40 THEN '2_25-40'
    WHEN pick_pct < 55 THEN '3_40-55'
    WHEN pick_pct < 70 THEN '4_55-70'
    WHEN pick_pct < 85 THEN '5_70-85'
    ELSE '6_85-100' END"""

print("=" * 78)
print("Q0. ОБЩО ПОКРИТИЕ С КОЕФИЦИЕНТИ (СЛЕД Фаза F0)")
print("=" * 78)
total = conn.execute("SELECT COUNT(*) c FROM predictions_log").fetchone()["c"]
with_odds = conn.execute("SELECT COUNT(*) c FROM predictions_log WHERE market_odds IS NOT NULL").fetchone()["c"]
print(f"общо записи: {total}, с коефициент: {with_odds} ({round(100*with_odds/total,1) if total else 0}%)")

print()
print("=" * 78)
print("Q1. РАЗПРЕДЕЛЕНИЕ НА EDGE ПО PROBABILITY BAND (само записи с odds)")
print("=" * 78)
q1 = conn.execute(f"""
    SELECT {PBAND} band, COUNT(*) n,
           ROUND(AVG((market_odds*1.0/our_fair_odds - 1)*100), 1) avg_edge,
           ROUND(MIN((market_odds*1.0/our_fair_odds - 1)*100), 1) min_edge,
           ROUND(MAX((market_odds*1.0/our_fair_odds - 1)*100), 1) max_edge
    FROM predictions_log
    WHERE market_odds IS NOT NULL AND our_fair_odds IS NOT NULL AND our_fair_odds > 0
    GROUP BY band ORDER BY band
""").fetchall()
print(f"{'band':<12}{'n':>6}{'avg_edge':>10}{'min':>8}{'max':>8}")
for r in q1:
    print(f"{r['band']:<12}{r['n']:>6}{r['avg_edge']:>10}{r['min_edge']:>8}{r['max_edge']:>8}")

print()
print("=" * 78)
print("Q2. РАЗПРЕДЕЛЕНИЕ НА EDGE ПО ГРУПА ПАЗАРИ (само записи с odds)")
print("=" * 78)
q2 = conn.execute(f"""
    SELECT {GRP} grp, COUNT(*) n,
           ROUND(AVG((market_odds*1.0/our_fair_odds - 1)*100), 1) avg_edge,
           ROUND(AVG(pick_pct), 1) avg_pct
    FROM predictions_log
    WHERE market_odds IS NOT NULL AND our_fair_odds IS NOT NULL AND our_fair_odds > 0
    GROUP BY grp ORDER BY grp
""").fetchall()
print(f"{'група':<16}{'n':>6}{'avg_edge':>10}{'avg_pct':>9}")
for r in q2:
    print(f"{r['grp']:<16}{r['n']:>6}{r['avg_edge']:>10}{r['avg_pct']:>9}")

print()
print("=" * 78)
print("Q3. КАЛИБРАЦИЯ СРЕЩУ ПАЗАРА - ПРИКЛЮЧИЛИ ПРОГНОЗИ С EDGE (проверима хипотеза)")
print("=" * 78)
print("(малка извадка - Фаза D2/F0 разшириха покритието едва днес - това е")
print(" ориентир за посоката, НЕ статистически значим резултат все още)")
q3 = conn.execute(f"""
    SELECT
        CASE
            WHEN (market_odds*1.0/our_fair_odds - 1)*100 < 0 THEN '1_отрицателен_edge'
            WHEN (market_odds*1.0/our_fair_odds - 1)*100 < 5 THEN '2_0-5%'
            WHEN (market_odds*1.0/our_fair_odds - 1)*100 < 15 THEN '3_5-15%'
            ELSE '4_15%+'
        END edge_bucket,
        COUNT(*) n,
        ROUND(100.0*SUM(CASE WHEN status='won' THEN 1 ELSE 0 END)/COUNT(*), 1) actual_winrate,
        ROUND(AVG(pick_pct), 1) avg_promised
    FROM predictions_log
    WHERE market_odds IS NOT NULL AND our_fair_odds IS NOT NULL AND our_fair_odds > 0
      AND status IN ('won','lost')
    GROUP BY edge_bucket ORDER BY edge_bucket
""").fetchall()
print(f"{'edge bucket':<22}{'n':>6}{'реален win%':>13}{'обещано%':>11}")
for r in q3:
    print(f"{r['edge_bucket']:<22}{r['n']:>6}{r['actual_winrate']:>13}{r['avg_promised']:>11}")

print()
print("=" * 78)
print("Q4. ПОКРИТИЕ С КОЕФИЦИЕНТИ ПО ЛИГА (само PROVEN-тип лиги значими за борда)")
print("=" * 78)
q4 = conn.execute("""
    SELECT league, COUNT(*) total,
           SUM(CASE WHEN market_odds IS NOT NULL THEN 1 ELSE 0 END) with_odds
    FROM predictions_log GROUP BY league ORDER BY total DESC
""").fetchall()
print(f"{'лига':<20}{'общо':>8}{'с odds':>9}{'%':>7}")
for r in q4:
    pct = round(100*r["with_odds"]/r["total"], 1) if r["total"] else 0
    print(f"{r['league']:<20}{r['total']:>8}{r['with_odds']:>9}{pct:>7}")

print()
print("=" * 78)
print("Q5. КОЛКО ВЪЗМОЖНОСТИ БИ ПОКАЗАЛ БОРДЪТ ПРИ РАЗЛИЧНИ ПРАГОВЕ (само PROVEN)")
print("=" * 78)
print("(симулация - НЕ пише никъде, само брои какво би минало филтъра)")
for lo, hi, min_edge in [(0, 100, 0), (25, 85, 3), (25, 85, 5), (20, 90, 3)]:
    n = conn.execute(f"""
        SELECT COUNT(*) c FROM predictions_log
        WHERE market_odds IS NOT NULL AND our_fair_odds IS NOT NULL AND our_fair_odds > 0
          AND pick_pct >= ? AND pick_pct <= ?
          AND (market_odds*1.0/our_fair_odds - 1)*100 >= ?
    """, (lo, hi, min_edge)).fetchone()["c"]
    print(f"  band [{lo}-{hi}]%, min_edge={min_edge}%  ->  {n} записа биха минали (общо, всички статуси)")

conn.close()
