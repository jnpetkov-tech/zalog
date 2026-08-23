"""
blend_vs_raw_backtest_20260824.py — Задача 1 (нощна сесия 23-24.08.2026):
проверка дали BLEND_WEIGHT=0.5 смесването (модел + пазарна линия) реално
подобрява точността, срещу твърдението в коментара до константата в
match_predictor_app.py ("доказано с бектест на 6 лиги, ~18 сезон-лиги
комбинации"). Никакъв файл с ТОЗИ оригинален бектест не е намерен в git
history, archive/ или другаде в репото (grep -S BLEND_WEIGHT през целия
git log показва само началния commit - константата е дошла оттам,
преди този проект да минe под CLAUDE.md правилото "число без файл в git
не е доказано").

Вместо да приемем твърдението наготово, тук се мери РЕАЛНИ, вече уредени
(status='won'/'lost') прогнози от predictions_log - за пазарите, за
които /daily реално прилага смесването (home_win/draw/away_win И
over25/under25, вижте _raw_candidates() в match_predictor_app.py - това
са единствените пазари, които изобщо получават market_odds блендинг,
не всички). За всеки fixture+пазарна група (1X2 или O/U), където И
трите/двете страни имат записан market_odds, смятаме:
  - суров модел: pick_pct, вече записан в лога (compute_grouped_markets
    никога не блендва - виж диагнозата от same-session разговора)
  - пазарна имплицирана вероятност: обезвигована от market_odds на
    ВСИЧКИ страни на групата (същата формула като devig_1x2/devig_ou в
    match_predictor_app.py - пренаписана тук самостоятелно, за да не
    тегли целия Flask/модел import при пускане)
  - смесена: BLEND_WEIGHT*пазар + (1-BLEND_WEIGHT)*модел, идентично на
    _raw_candidates()

Brier score (по-ниско = по-добре) и log-loss (по-ниско = по-добре) за
всяка от трите вероятности (модел/пазар/смес) срещу реалния изход
(1 ако status='won', 0 ако 'lost').

Употреба: python3 validation/blend_vs_raw_backtest_20260824.py
Пише validation/blend_vs_raw_backtest_20260824.csv (детайл по ред) и
принтира резюме по пазарна група и по лига.
"""
import csv
import math
import sqlite3
from collections import defaultdict

BLEND_WEIGHT = 0.5  # копие на константата от match_predictor_app.py - НЕ импортираме
                     # модула тук нарочно (import там преизчислява/фитва всичките 17
                     # модела още при import time - скъпо и ненужно за тази проверка).

MARKET_GROUPS = {
    "1x2": ["home_win", "draw", "away_win"],
    "ou25": ["over25", "under25"],
}


def devig(odds_list):
    implied = [1.0 / o for o in odds_list]
    total = sum(implied)
    return [i / total for i in implied]


def brier(p, outcome):
    return (p - outcome) ** 2


def logloss(p, outcome):
    eps = 1e-9
    p = min(max(p, eps), 1 - eps)
    return -math.log(p) if outcome == 1 else -math.log(1 - p)


def main():
    conn = sqlite3.connect("predictions.db")
    conn.row_factory = sqlite3.Row
    all_codes = [c for codes in MARKET_GROUPS.values() for c in codes]
    placeholders = ",".join("?" * len(all_codes))
    rows = conn.execute(f"""
        SELECT league, fixture_id, market_code, pick_pct, market_odds, status
        FROM predictions_log
        WHERE market_code IN ({placeholders})
          AND status IN ('won', 'lost')
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
            continue  # непълна група (липсва коефициент за поне една страна) - прескачаме
        odds_list = [by_code[c]["market_odds"] for c in codes]
        market_probs = devig(odds_list)
        for code, market_p in zip(codes, market_probs):
            row = by_code[code]
            raw_p = (row["pick_pct"] or 0) / 100.0
            outcome = 1 if row["status"] == "won" else 0
            blended_p = BLEND_WEIGHT * market_p + (1 - BLEND_WEIGHT) * raw_p
            detail_rows.append({
                "league": row["league"], "fixture_id": fixture_id, "market_group": group,
                "market_code": code, "outcome": outcome,
                "raw_pct": round(raw_p * 100, 2), "market_pct": round(market_p * 100, 2),
                "blended_pct": round(blended_p * 100, 2),
                "raw_brier": round(brier(raw_p, outcome), 5),
                "market_brier": round(brier(market_p, outcome), 5),
                "blended_brier": round(brier(blended_p, outcome), 5),
                "raw_logloss": round(logloss(raw_p, outcome), 5),
                "market_logloss": round(logloss(market_p, outcome), 5),
                "blended_logloss": round(logloss(blended_p, outcome), 5),
            })

    if not detail_rows:
        print("Няма достатъчно данни (пълни групи с коефициент за всички страни) за backtest.")
        return

    out_path = "validation/blend_vs_raw_backtest_20260824.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
        writer.writeheader()
        writer.writerows(detail_rows)

    def summarize(rows_subset, label):
        n = len(rows_subset)
        if n == 0:
            return
        raw_b = sum(r["raw_brier"] for r in rows_subset) / n
        mkt_b = sum(r["market_brier"] for r in rows_subset) / n
        bln_b = sum(r["blended_brier"] for r in rows_subset) / n
        raw_l = sum(r["raw_logloss"] for r in rows_subset) / n
        mkt_l = sum(r["market_logloss"] for r in rows_subset) / n
        bln_l = sum(r["blended_logloss"] for r in rows_subset) / n
        print(f"{label} (n={n}):")
        print(f"  Brier   - модел: {raw_b:.4f}  пазар: {mkt_b:.4f}  смес: {bln_b:.4f}"
              f"  {'СМЕС ПО-ДОБРА' if bln_b < raw_b else 'МОДЕЛ ПО-ДОБЪР (смесването НЕ помага тук)'}")
        print(f"  LogLoss - модел: {raw_l:.4f}  пазар: {mkt_l:.4f}  смес: {bln_l:.4f}"
              f"  {'СМЕС ПО-ДОБРА' if bln_l < raw_l else 'МОДЕЛ ПО-ДОБЪР (смесването НЕ помага тук)'}")

    print(f"=== Общо {len(detail_rows)} наблюдения (уредени прогнози с пълен пазарен коефициент) ===\n")
    summarize(detail_rows, "ОБЩО (1X2 + O/U)")
    print()
    for group in MARKET_GROUPS:
        summarize([r for r in detail_rows if r["market_group"] == group], f"Група: {group}")
    print()
    leagues = sorted(set(r["league"] for r in detail_rows))
    for lg in leagues:
        summarize([r for r in detail_rows if r["league"] == lg], f"Лига: {lg}")

    print(f"\nЗаписано: {out_path}")


if __name__ == "__main__":
    main()
