"""
value_bets_before_after_20260824.py — Задача 4 (нощна сесия 23-24.08.2026):
след Задача 2 (compute_grouped_markets вече смесва модел+пазар за
home_win/draw/away_win/over25/under25 вместо чист модел), колко "стойностни"
залога (value_bets в compute_grouped_markets - MIN_VALUE_BET_PROB/
MAX_VALUE_BET_ODDS/MAX_TRUSTWORTHY_EV, виж match_predictor_app.py) е имало
ПРЕДИ смяната и колко остават СЛЕД нея, по лига. Праговете НЕ се пипат тук -
само преизчислява кой ред минава СЪЩИТЕ прагове с чист модел срещу смесено
число.

Данни: predictions_log редове за home_win/draw/away_win/over25/under25 с
записан market_odds (ВСИЧКИ статуси - pending и уредени, защото питаме
"колко възможности за залог се показват", не точност) - pick_pct в тези
редове е ВИНАГИ чист модел (логнати преди Задача 2 да промени логването),
затова "chist" тук идва directно от лога, "смесено" се преизчислява тук по
същата формула като _blend_with_market()/BLEND_WEIGHT в match_predictor_app.py.

Група по (fixture_id, market_group) - същите двойки market_code, каквито
compute_grouped_markets прави кандидати за value_bets (1x2: home_win+draw+
away_win заедно за devig, ou25: over25+under25 заедно), само пълни групи
(всички страни с коефициент).

Употреба: python3 validation/value_bets_before_after_20260824.py
Пише validation/value_bets_before_after_20260824.csv (детайл по кандидат) и
принтира резюме по лига.
"""
import csv
import sqlite3
from collections import defaultdict

BLEND_WEIGHT = 0.5  # копие, вижте bележката в blend_vs_raw_backtest_20260824.py защо не импортираме модула

MIN_VALUE_BET_PROB = 0.35
MAX_VALUE_BET_ODDS = 5.0
MAX_TRUSTWORTHY_EV = 0.40

MARKET_GROUPS = {
    "1x2": ["home_win", "draw", "away_win"],
    "ou25": ["over25", "under25"],
}


def devig(odds_list):
    implied = [1.0 / o for o in odds_list]
    total = sum(implied)
    return [i / total for i in implied]


def classify(our_p, market_p, odd):
    """Връща 'value', 'distrusted' (EV>прага) или None (не минава филтъра) -
    точно логиката от value_bets цикъла в compute_grouped_markets()."""
    edge = our_p - market_p
    if edge <= 0:
        return None
    if our_p < MIN_VALUE_BET_PROB:
        return None
    if odd > MAX_VALUE_BET_ODDS:
        return None
    ev = (our_p * odd) - 1
    if ev > MAX_TRUSTWORTHY_EV:
        return "distrusted"
    return "value"


def main():
    conn = sqlite3.connect("predictions.db")
    conn.row_factory = sqlite3.Row
    all_codes = [c for codes in MARKET_GROUPS.values() for c in codes]
    placeholders = ",".join("?" * len(all_codes))
    rows = conn.execute(f"""
        SELECT league, fixture_id, market_code, pick_pct, market_odds, status
        FROM predictions_log
        WHERE market_code IN ({placeholders})
          AND market_odds IS NOT NULL
    """, all_codes).fetchall()
    conn.close()

    by_fixture_group = defaultdict(dict)
    for r in rows:
        for group, codes in MARKET_GROUPS.items():
            if r["market_code"] in codes:
                by_fixture_group[(r["fixture_id"], group)][r["market_code"]] = r
                break

    detail_rows = []
    for (fixture_id, group), by_code in by_fixture_group.items():
        codes = MARKET_GROUPS[group]
        if not all(c in by_code for c in codes):
            continue
        odds_list = [by_code[c]["market_odds"] for c in codes]
        market_probs = devig(odds_list)
        for code, market_p in zip(codes, market_probs):
            row = by_code[code]
            raw_p = (row["pick_pct"] or 0) / 100.0
            blended_p = BLEND_WEIGHT * market_p + (1 - BLEND_WEIGHT) * raw_p
            odd = row["market_odds"]
            before = classify(raw_p, market_p, odd)
            after = classify(blended_p, market_p, odd)
            detail_rows.append({
                "league": row["league"], "fixture_id": fixture_id, "market_group": group,
                "market_code": code, "status": row["status"],
                "raw_pct": round(raw_p * 100, 2), "blended_pct": round(blended_p * 100, 2),
                "market_pct": round(market_p * 100, 2), "odd": odd,
                "before": before or "none", "after": after or "none",
            })

    if not detail_rows:
        print("Няма достатъчно данни (пълни групи с коефициент) за преброяване.")
        return

    out_path = "validation/value_bets_before_after_20260824.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
        writer.writeheader()
        writer.writerows(detail_rows)

    leagues = sorted(set(r["league"] for r in detail_rows))
    print(f"{'Лига':<20} {'преди(value)':>13} {'преди(distrust)':>17} {'след(value)':>13} {'след(distrust)':>16}")
    tot_before_v = tot_before_d = tot_after_v = tot_after_d = 0
    for lg in leagues:
        sub = [r for r in detail_rows if r["league"] == lg]
        bv = sum(1 for r in sub if r["before"] == "value")
        bd = sum(1 for r in sub if r["before"] == "distrusted")
        av = sum(1 for r in sub if r["after"] == "value")
        ad = sum(1 for r in sub if r["after"] == "distrusted")
        tot_before_v += bv; tot_before_d += bd; tot_after_v += av; tot_after_d += ad
        print(f"{lg:<20} {bv:>13} {bd:>17} {av:>13} {ad:>16}")
    print(f"{'ОБЩО':<20} {tot_before_v:>13} {tot_before_d:>17} {tot_after_v:>13} {tot_after_d:>16}")
    print(f"\nЗаписано: {out_path} ({len(detail_rows)} кандидата)")


if __name__ == "__main__":
    main()
