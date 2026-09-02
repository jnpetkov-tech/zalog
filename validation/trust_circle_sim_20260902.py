"""
validation/trust_circle_sim_20260902.py

СИМУЛАЦИЯ, не приложение (НОЩ 02.09.2026, задача 4, NOSHT2.md). Не пише
никъде в trust_derived - build_trust_derived.compute_bucket() се
преизползва непроменен, само входът е различен.

Въпрос: england2/germany2 никога не получават измерено доверие, защото
build_trust_derived.py брои от evaluation.published_picks() - едно
"публикувано" (top-pick-eligible) избрано на мач, а UNVERIFIED лиги никога
нямат такова (затворен кръг, виж validation/pokritie_i_byudzhet_20260902.md
т.5). Тук: ако вместо published_picks() броим от СУРОВИТЕ логнати редове
(всеки пазар, логнат за мача - log_all_markets логва до ~24/мач), филтрирани
само по market_code -> market_group (не по is_top_pick_eligible), какви
статуси биха получили england2/germany2, и - по-важно - какво би се
променило за останалите 15 лиги (не искаме да счупим работещото).

Употреба: python3 validation/trust_circle_sim_20260902.py
"""
import csv
import sys
sys.path.insert(0, ".")

import system_tracker as st
import prediction_policy as policy
import evaluation as ev
from build_trust_derived import compute_bucket, MIN_N, MARGIN


def simulate_raw():
    """Огледало на build_trust_derived.build(), само с една разлика:
    'picks' идва директно от СУРОВИТЕ settled редове (филтрирани по
    market_code), не от evaluation.published_picks()."""
    conn = st.get_conn()
    import sqlite3
    conn.row_factory = sqlite3.Row
    all_rows = [dict(r) for r in conn.execute("SELECT * FROM predictions_log").fetchall()]
    conn.close()

    by_league = {}
    for r in all_rows:
        by_league.setdefault(r["league"], []).append(r)

    out_rows = []
    for league, lg_rows in sorted(by_league.items()):
        settled = [r for r in lg_rows if r["status"] in ev.SETTLED]
        by_group = {}
        for r in settled:
            grp = policy.market_group(r["market_code"])
            by_group.setdefault(grp, []).append(r)
        for grp, grp_rows in sorted(by_group.items()):
            bucket = compute_bucket(grp_rows)
            if bucket is None:
                continue
            out_rows.append({"league": league, "market_group": grp, **bucket})
    return out_rows


def real_current():
    """Реалната, текущата trust_derived (снощния 06:15 run) - за сравнение,
    четена директно, НЕ преизчислена тук."""
    return [dict(r) for r in
            [row for row in st.get_all_trust_derived().values()]]


if __name__ == "__main__":
    raw_rows = simulate_raw()
    real_rows = real_current()

    real_by_key = {(r["league"], r["market_group"]): r for r in real_rows}
    raw_by_key = {(r["league"], r["market_group"]): r for r in raw_rows}

    out_path = "validation/trust_circle_sim_20260902.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["league", "market_group", "real_status", "real_n",
                      "sim_status", "sim_n", "changed"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        all_keys = sorted(set(real_by_key) | set(raw_by_key))
        for key in all_keys:
            real = real_by_key.get(key)
            sim = raw_by_key.get(key)
            real_status = real["status"] if real else "unverified(no row)"
            real_n = real["n_settled"] if real else 0
            sim_status = sim["status"] if sim else "unverified(no row)"
            sim_n = sim["n_settled"] if sim else 0
            changed = (real_status != sim_status)
            writer.writerow({
                "league": key[0], "market_group": key[1],
                "real_status": real_status, "real_n": real_n,
                "sim_status": sim_status, "sim_n": sim_n, "changed": changed,
            })

    print(f"CSV: {out_path}")
    print(f"\n{'Лига':20s} {'Група':15s} {'Реално':22s} {'Симулирано':22s} {'n реално':9s} {'n симулирано'}")
    changed_count = 0
    for key in sorted(set(real_by_key) | set(raw_by_key)):
        real = real_by_key.get(key)
        sim = raw_by_key.get(key)
        real_status = real["status"] if real else "—"
        real_n = real["n_settled"] if real else 0
        sim_status = sim["status"] if sim else "—"
        sim_n = sim["n_settled"] if sim else 0
        mark = " *** ПРОМЯНА ***" if real_status != sim_status else ""
        if mark:
            changed_count += 1
        print(f"{key[0]:20s} {key[1]:15s} {real_status:22s} {sim_status:22s} {real_n:9d} {sim_n:5d}{mark}")
    print(f"\nОбщо {len(set(real_by_key) | set(raw_by_key))} (лига,група) комбинации, {changed_count} с различен статус.")
