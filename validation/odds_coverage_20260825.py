"""
validation/odds_coverage_20260825.py - Фаза 0.1 (J.2, PLAN.md, чака от 11.08.2026):
покритие с коефициенти. Дака, 25.08.2026: "От 2327 уредени прогнози само 915 имат
записан пазарен коефициент. Значи не броят мачове е ограничението, а коефициентите.
Измери: какъв процент от прогнозите получават коефициент, разбито по лига и по
пазар, и къде липсват най-много."

Измерва какъв процент от УРЕДЕНИТЕ (status won/lost) прогнози в predictions_log
имат market_odds IS NOT NULL, разбито по (лига, market_code) и по (лига, пазарна
група - prediction_policy.market_group()). Само уредени, не pending - за pending
мачове покритието все още може да се промени (refresh_pending_odds.py backfill-ва
в 48-часовия прозорец преди началото на мача), докато за уредени мачове целият
жизнен цикъл вече е минал - числото е финално, не моментна снимка по средата.

Забележка: "915-те кандидат-изхода" в validation/vs_market_brier*.py е ПО-ТЕСНО
число от това тук - изисква ЦЯЛАТА devig група (home_win+draw+away_win заедно,
или over25+under25 заедно) да има коефициент, само за петте пазара, участващи в
_blend_with_market(). Това измерване е по-широко: всеки логнат market_code
поотделно, за да покаже точно КЪДЕ структурно липсва коефициент (напр. BTTS/чиста
мрежа/картони никога не са имали кеширан коефициент - виж резюмето по-долу),
независимо дали пазарът изобщо участва в смесването.

Употреба: python3 validation/odds_coverage_20260825.py
Пише:
  - validation/odds_coverage_by_market_20260825.csv (лига x market_code)
  - validation/odds_coverage_by_group_20260825.csv (лига x пазарна група)
и принтира резюме: общо покритие, по пазарна група, по лига, най-лошо покритите
комбинации (n>=MIN_N).
"""
import csv
import sqlite3
import sys

sys.path.insert(0, ".")
import prediction_policy as policy

MIN_N = 20


def main():
    conn = sqlite3.connect("predictions.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT league, market_code, market_odds
        FROM predictions_log
        WHERE status IN ('won', 'lost')
    """).fetchall()
    conn.close()

    total = len(rows)
    total_with_odds = sum(1 for r in rows if r["market_odds"] is not None)

    by_market = {}
    by_group = {}
    for r in rows:
        has_odds = r["market_odds"] is not None
        grp = policy.market_group(r["market_code"])

        d = by_market.setdefault((r["league"], r["market_code"]), {"n": 0, "with_odds": 0})
        d["n"] += 1
        d["with_odds"] += int(has_odds)

        dg = by_group.setdefault((r["league"], grp), {"n": 0, "with_odds": 0})
        dg["n"] += 1
        dg["with_odds"] += int(has_odds)

    market_path = "validation/odds_coverage_by_market_20260825.csv"
    with open(market_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["league", "market_code", "n", "n_with_odds", "pct"])
        for (league, code), d in sorted(by_market.items()):
            pct = round(d["with_odds"] / d["n"] * 100, 1) if d["n"] else 0.0
            w.writerow([league, code, d["n"], d["with_odds"], pct])

    group_path = "validation/odds_coverage_by_group_20260825.csv"
    with open(group_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["league", "market_group", "n", "n_with_odds", "pct"])
        for (league, grp), d in sorted(by_group.items()):
            pct = round(d["with_odds"] / d["n"] * 100, 1) if d["n"] else 0.0
            w.writerow([league, grp, d["n"], d["with_odds"], pct])

    print(f"=== Покритие с коефициенти - {total} уредени (won/lost) прогнози общо ===")
    print(f"Общо с market_odds: {total_with_odds} ({total_with_odds / total * 100:.1f}%)\n")

    print("=== По пазарна група (сумирано по всички лиги) ===")
    grp_totals = {}
    for (league, grp), d in by_group.items():
        gt = grp_totals.setdefault(grp, {"n": 0, "with_odds": 0})
        gt["n"] += d["n"]
        gt["with_odds"] += d["with_odds"]
    for grp, d in sorted(grp_totals.items(), key=lambda x: -x[1]["n"]):
        pct = d["with_odds"] / d["n"] * 100 if d["n"] else 0.0
        print(f"  {grp:<15} n={d['n']:<6} with_odds={d['with_odds']:<6} {pct:5.1f}%")

    print("\n=== По лига (сумирано по всички пазари) ===")
    league_totals = {}
    for (league, grp), d in by_group.items():
        lt = league_totals.setdefault(league, {"n": 0, "with_odds": 0})
        lt["n"] += d["n"]
        lt["with_odds"] += d["with_odds"]
    for league, d in sorted(league_totals.items(), key=lambda x: -x[1]["n"]):
        pct = d["with_odds"] / d["n"] * 100 if d["n"] else 0.0
        print(f"  {league:<20} n={d['n']:<6} with_odds={d['with_odds']:<6} {pct:5.1f}%")

    print(f"\n=== Най-лошо покрити (лига x пазарна група), n>={MIN_N}, подредени по % покритие ===")
    combos = [(league, grp, d) for (league, grp), d in by_group.items() if d["n"] >= MIN_N]
    combos.sort(key=lambda x: x[2]["with_odds"] / x[2]["n"])
    for league, grp, d in combos[:20]:
        pct = d["with_odds"] / d["n"] * 100
        print(f"  {league:<20} {grp:<15} n={d['n']:<6} with_odds={d['with_odds']:<6} {pct:5.1f}%")

    print(f"\nЗаписано: {market_path} ({len(by_market)} реда), {group_path} ({len(by_group)} реда)")


if __name__ == "__main__":
    main()
