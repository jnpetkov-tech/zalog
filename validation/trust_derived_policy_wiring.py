"""
validation/trust_derived_policy_wiring.py — Партида 4, Стъпка 4
(21.08.2026, ARCHITECTURE.md, Граница 3).

Преди/след доказателство за промяната в prediction_policy.tier() (виж
CLAUDE.md: промяна в prediction_policy.py не влиза в живия код без
записан преди/след тук). Сравнява СТАРОТО поведение (ръчна TRUST_MATRIX
+ DEFAULT_TIER=WEAK за непозната лига) срещу НОВОТО (trust_derived с
предимство, UNVERIFIED вместо тихо WEAK за непозната лига) за всяка
регистрирана лига x всяка пазарна група.

Употреба: python3 validation/trust_derived_policy_wiring.py
Пише validation/trust_derived_policy_wiring_<YYYYMMDD>.csv
"""
import csv
from datetime import date

import prediction_policy as policy

ALL_LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "champions_league",
               "europa_league", "conference_league", "italy", "portugal", "france2",
               "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
GROUPS = ["1x2", "ou25", "team_total", "htft", "double_chance", "btts", "corners", "cards", "offsides"]

# представител market_code за всяка група - само за да минем през реалния
# market_group() мапинг коректно (виж prediction_policy.market_group())
REP_CODE = {"1x2": "home_win", "ou25": "over25", "team_total": "home_over15",
            "htft": "htft:1/1", "double_chance": "dc_1x", "btts": "btts_yes",
            "corners": "corners_total_over_9.5", "cards": "cards_total_over_3.5",
            "offsides": "offsides_total_over_3.5"}


def old_tier(league, grp):
    """Точно старата (преди Партида 4) tier() логика, възпроизведена тук
    буквално за сравнение - НЕ вика live кода (той вече е новият)."""
    league_row = policy.TRUST_MATRIX.get(league)
    if league_row is None:
        return "weak"  # старият DEFAULT_TIER
    return league_row.get(grp, "weak")


def build():
    rows = []
    for league in ALL_LEAGUES:
        for grp in GROUPS:
            old = old_tier(league, grp)
            new = policy.tier(league, REP_CODE[grp])
            rows.append({"league": league, "market_group": grp, "old_tier": old,
                         "new_tier": new, "changed": old != new})
    return rows


if __name__ == "__main__":
    rows = build()
    out_path = f"validation/trust_derived_policy_wiring_{date.today().strftime('%Y%m%d')}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["league", "market_group", "old_tier", "new_tier", "changed"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    changed = [r for r in rows if r["changed"]]
    print(f"Общо {len(rows)} (лига, група) комбинации, {len(changed)} с промяна:")
    for r in changed:
        print(f"  {r['league']:20s} {r['market_group']:15s} {r['old_tier']} -> {r['new_tier']}")
    print(f"\nCSV: {out_path}")
