"""A3 (ZADACHA_FAZA2.md, 19.09.2026) — "затвореният кръг" за england2/germany2.

Диагнозата (coverage_14d_20260919.md): england2/germany2 нямат НИТО ЕДИН ред в
TRUST_MATRIX и никога не могат да натрупат статус през build_trust_derived.py,
защото то смята само от evaluation.published_picks() — а published_picks()
самата вика pick_selection.rank_logged_rows(), което изисква PROVEN/WEAK
(is_top_pick_eligible), никога UNVERIFIED. Кръгът: лигата няма статус, защото
няма публикувани прогнози, и няма публикувани прогнози, защото няма статус
(validation/trust_circle_sim_20260902.md, НОЩ2 т.4).

Тази задача СЪЗНАТЕЛНО заобикаля published_picks() за измерването - смята
директно от СУРОВИТЕ логнати редове в predictions_log (всеки пазар, всеки
изход, за всеки мач - system_tracker.list_predictions()), групирани по
(лига, market_group). Методът/baseline-ът НЕ е преизмислен: за всяка
(лига, група) клетка се вика буквално build_trust_derived.compute_bucket()
(MIN_N=20, MARGIN=0.02 Brier разлика, Бернули baseline).

Разлика спрямо build_trust_derived.py, важна за четенето на числата: там n е
БРОЙ МАЧОВЕ (един канoничен избран ред на мач, след published_picks()); тук n
е БРОЙ СУРОВИ РЕДОВЕ (всеки логнат изход на пазара за мача - напр. 1x2 логва
home_win+draw+away_win, 3 реда на мач). Затова "брой различни мачове" се
отчита отделно до всяко "n_settled" число - да не се бъркат двете.

Само четене. Нищо не се пише в trust_derived/TRUST_MATRIX от този скрипт -
решението (Стъпка 2 от ZADACHA_FAZA2.md) се прилага ръчно, в prediction_policy.py,
СЛЕД като този доклад е committed (правило 7+8 от CLAUDE.md).

Употреба: python3 validation/trust_bootstrap_20260919.py
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import system_tracker as st
import prediction_policy as policy
import evaluation as ev
import build_trust_derived as btd

GROUPS = ["1x2", "ou25", "team_total", "htft"]
TARGET_LEAGUES = ["england2", "germany2"]
CONTROL_LEAGUE = "england"

# Решаващо правило (Стъпка 2, буквално от задачата - без собствена преценка)
MIN_ROWS = 100
MIN_MATCHES = 30
MAX_CALIB_GAP_PP = 6.0


def measure_league(league, all_rows):
    rows = [r for r in all_rows if r["league"] == league]
    settled = [r for r in rows if r["status"] in ev.SETTLED]
    by_group = {}
    for r in settled:
        grp = policy.market_group(r["market_code"])
        if grp in GROUPS:
            by_group.setdefault(grp, []).append(r)

    out = {}
    for grp in GROUPS:
        picks = by_group.get(grp, [])
        n_settled = len(picks)
        n_matches = len(set(p["fixture_id"] for p in picks))
        bucket = btd.compute_bucket(picks)  # None ако n_settled == 0
        out[grp] = {"n_settled": n_settled, "n_matches": n_matches, "bucket": bucket}
    return out


def decide(bucket_info):
    """Правилото от Стъпка 2, буквално. Връща (decision, why)."""
    n_settled = bucket_info["n_settled"]
    n_matches = bucket_info["n_matches"]
    bucket = bucket_info["bucket"]
    if n_settled < MIN_ROWS:
        return None, f"n_settled={n_settled} < {MIN_ROWS}"
    if n_matches < MIN_MATCHES:
        return None, f"различни мачове={n_matches} < {MIN_MATCHES}"
    if bucket is None:
        return None, "няма нито един уреден ред"
    diff_brier = bucket["baseline_brier"] - bucket["model_brier"]
    if diff_brier <= 0:
        return None, (f"Brier {bucket['model_brier']:.4f} НЕ е по-добър от baseline "
                       f"{bucket['baseline_brier']:.4f} (разлика {diff_brier:+.4f})")
    calib_gap = abs(bucket["promised_avg"] - bucket["actual_pct"])
    if calib_gap > MAX_CALIB_GAP_PP:
        return None, (f"|обещано-познато|={calib_gap:.1f}пр.п. > {MAX_CALIB_GAP_PP}пр.п. "
                       f"(обещано {bucket['promised_avg']:.1f}%, познато {bucket['actual_pct']:.1f}%)")
    return "weak", (f"n_settled={n_settled}, мачове={n_matches}, Brier {bucket['model_brier']:.4f} "
                     f"срещу baseline {bucket['baseline_brier']:.4f} ({diff_brier:+.4f}), "
                     f"калибрация {calib_gap:.1f}пр.п. <= {MAX_CALIB_GAP_PP}пр.п.")


def main():
    all_rows = st.list_predictions()

    results = {}
    for league in TARGET_LEAGUES + [CONTROL_LEAGUE]:
        results[league] = measure_league(league, all_rows)

    decisions = {}
    for league in TARGET_LEAGUES:
        decisions[league] = {}
        for grp in GROUPS:
            decisions[league][grp] = decide(results[league][grp])

    return results, decisions


if __name__ == "__main__":
    results, decisions = main()

    def _fmt_bucket(b):
        if b["bucket"] is None:
            return f"n_settled={b['n_settled']:5d}  n_matches={b['n_matches']:4d}  (няма settled)"
        bk = b["bucket"]
        return (f"n_settled={b['n_settled']:5d}  n_matches={b['n_matches']:4d}  "
                f"Brier={bk['model_brier']:.4f}  baseline={bk['baseline_brier']:.4f}  "
                f"обещано={bk['promised_avg']:5.1f}%  познато={bk['actual_pct']:5.1f}%  "
                f"[{bk['status']}]")

    for league in TARGET_LEAGUES + [CONTROL_LEAGUE]:
        print(f"\n=== {league} ===")
        for grp in GROUPS:
            print(f"  {grp:12s} {_fmt_bucket(results[league][grp])}")

    print("\n=== РЕШЕНИЯ (Стъпка 2, буквално) ===")
    for league in TARGET_LEAGUES:
        for grp in GROUPS:
            d, why = decisions[league][grp]
            print(f"  {league}/{grp}: {d or 'НЕ пипай'} - {why}")

    out_path = f"validation/trust_bootstrap_{date.today().strftime('%Y%m%d')}_raw.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"results": results, "decisions": decisions}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nСуров резултат: {out_path}")
