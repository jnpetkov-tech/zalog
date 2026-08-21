import sqlite3

conn = sqlite3.connect("predictions.db")
conn.row_factory = sqlite3.Row

GRP = """CASE
    WHEN market_code IN ('home_win','draw','away_win') THEN '1_1X2'
    WHEN market_code IN ('over25','under25') THEN '2_OU25'
    WHEN market_code LIKE 'home_over%' OR market_code LIKE 'home_under%'
      OR market_code LIKE 'away_over%' OR market_code LIKE 'away_under%' THEN '3_TeamTotal'
    WHEN market_code LIKE 'htft%' THEN '4_HTFT'
    WHEN market_code LIKE 'corners%' OR market_code LIKE 'cards%'
      OR market_code LIKE 'offsides%' THEN '5_JUNK'
    ELSE '6_Other' END"""

BIN = """CASE WHEN pick_pct < 60 THEN '50-60' WHEN pick_pct < 70 THEN '60-70'
    WHEN pick_pct < 80 THEN '70-80' WHEN pick_pct < 90 THEN '80-90'
    ELSE '90-100' END"""

print("=" * 70)
print("Q1. КАЛИБРАЦИЯ ПО ГРУПА ПАЗАРИ  (обещано vs реално)")
print("=" * 70)
q1 = conn.execute(f"""
    SELECT {GRP} grp, {BIN} bin, COUNT(*) n,
           ROUND(AVG(pick_pct),1) promised,
           ROUND(100.0*SUM(CASE WHEN status='won' THEN 1 ELSE 0 END)/COUNT(*),1) actual
    FROM predictions_log WHERE status IN ('won','lost')
    GROUP BY grp, bin ORDER BY grp, bin""").fetchall()
print(f"{'група':<14}{'бин':<9}{'n':>5}{'обещано':>10}{'реално':>9}{'разлика':>9}")
for r in q1:
    print(f"{r['grp']:<14}{r['bin']:<9}{r['n']:>5}{r['promised']:>10}"
          f"{r['actual']:>9}{round(r['actual']-r['promised'],1):>9}")

print()
print("=" * 70)
print("Q2. КОЙ ПЪЛНИ БИНОВЕТЕ 80%+ (по пазар)")
print("=" * 70)
for r in conn.execute("""
    SELECT market_code, COUNT(*) n, ROUND(AVG(pick_pct),1) promised,
           ROUND(100.0*SUM(CASE WHEN status='won' THEN 1 ELSE 0 END)/COUNT(*),1) actual
    FROM predictions_log WHERE status IN ('won','lost') AND pick_pct >= 80
    GROUP BY market_code ORDER BY n DESC"""):
    print(f"{r['market_code']:<34}{r['n']:>5}{r['promised']:>9}{r['actual']:>9}")

print()
print("=" * 70)
print("Q3. ПОКРИТИЕ ПО ЛИГА (търсим изкривяване от разглеждане)")
print("=" * 70)
for r in conn.execute("""
    SELECT league, COUNT(*) total,
      SUM(CASE WHEN status IN ('won','lost') THEN 1 ELSE 0 END) settled,
      SUM(CASE WHEN status='no_data' THEN 1 ELSE 0 END) nodata,
      COUNT(DISTINCT fixture_id) fixtures
    FROM predictions_log GROUP BY league ORDER BY total DESC"""):
    print(f"{r['league']:<22}{r['total']:>7}{r['settled']:>9}{r['nodata']:>8}{r['fixtures']:>9}")

print()
print("=" * 70)
print("Q4. СТАТУСИ + ДУБЛИКАТИ + СХЕМА")
print("=" * 70)
for r in conn.execute("SELECT status, COUNT(*) n FROM predictions_log GROUP BY status"):
    print(f"  {r['status']:<14}{r['n']:>7}")
d = conn.execute("""SELECT COUNT(*) c FROM (SELECT fixture_id, market_code, COUNT(*) k
    FROM predictions_log GROUP BY 1,2 HAVING k > 1)""").fetchone()["c"]
print(f"  дублирани (fixture_id, market_code) двойки: {d}")
print("  индекси:", [r[1] for r in conn.execute("PRAGMA index_list(predictions_log)")])
print("  схема:")
print("   ", conn.execute(
    "SELECT sql FROM sqlite_master WHERE name='predictions_log'").fetchone()[0])

print()
print("=" * 70)
print("Q5. ПОКРИТИЕ С КОЕФИЦИЕНТИ ПО ПАЗАР")
print("=" * 70)
for r in conn.execute("""
    SELECT market_code, COUNT(*) n,
           SUM(CASE WHEN market_odds IS NOT NULL THEN 1 ELSE 0 END) with_odds
    FROM predictions_log GROUP BY market_code ORDER BY n DESC"""):
    print(f"{r['market_code']:<34}{r['n']:>7}{r['with_odds']:>10}")

conn.close()
