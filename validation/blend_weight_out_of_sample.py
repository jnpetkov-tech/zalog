"""
validation/blend_weight_out_of_sample.py - продължение на т.1 (24.08.2026):
validation/blend_weight_sweep_20260825.csv показа кое тегло минимизира Brier
на ЦЯЛАТА извадка - но не казва дали това е реален ефект, или нагаждане към
95-те налични наблюдения на пазар (overfitting). Тук: хронологично
разполовяване по match_date (същия метод като brier_vs_market.
split_half_check) - намираме оптималното W на ПЪРВАТА (по-стара) половина,
прилагаме го БЕЗ ПРЕИЗБОР върху ВТОРАТА (по-нова, невиждана) половина, и
сравняваме Brier(W*) срещу Brier(0.5) там. Издържа ли, теглото е реално;
не издържа ли, било е нагаждане - оставаме на 0.5.

Използва brier_vs_market.build_detail_rows() - same raw_p/market_p извод
(basis raw/blended) като blend_weight_sweep.py. Само измерване - BLEND_WEIGHT
в match_predictor_app.py не се пипа.

Употреба: python3 validation/blend_weight_out_of_sample.py
Пише validation/blend_weight_out_of_sample_20260825.csv и принтира таблица.
"""
import csv
import sys

sys.path.insert(0, ".")
import system_tracker as st
import brier_vs_market as bm

WEIGHTS = [round(i / 10, 1) for i in range(0, 11)]
MIN_HALF_N = 20  # под това - показваме числото, но не се доверяваме на извода


def brier_mean(rows, w):
    if not rows:
        return None
    return sum((w * d["market_p"] + (1 - w) * d["raw_p"] - d["outcome"]) ** 2 for d in rows) / len(rows)


def best_weight(rows):
    if not rows:
        return None, None
    scored = [(w, brier_mean(rows, w)) for w in WEIGHTS]
    return min(scored, key=lambda x: x[1])


def main():
    rows = st.list_predictions()
    detail = bm.build_detail_rows(rows)
    if not detail:
        print("Няма уредени кандидати с пълна пазарна група за анализ.")
        return

    codes = sorted(set(d["market_code"] for d in detail))
    groups = {c: [d for d in detail if d["market_code"] == c] for c in codes}
    groups["ALL"] = detail

    results = []
    for name, items in groups.items():
        ordered = sorted(items, key=lambda d: d["match_date"] or "")
        mid = len(ordered) // 2
        first, second = ordered[:mid], ordered[mid:]

        w1, b1_at_w1 = best_weight(first)
        b1_at_05 = brier_mean(first, 0.5)
        b2_at_w1 = brier_mean(second, w1) if w1 is not None else None
        b2_at_05 = brier_mean(second, 0.5)
        b2_at_00 = brier_mean(second, 0.0)
        b2_at_10 = brier_mean(second, 1.0)

        enough = len(first) >= MIN_HALF_N and len(second) >= MIN_HALF_N
        holds = bool(enough and b2_at_w1 is not None and b2_at_05 is not None and b2_at_w1 < b2_at_05)

        results.append({
            "market_code": name, "n_first": len(first), "n_second": len(second),
            "best_w_first_half": w1,
            "brier_first_at_bestw": round(b1_at_w1, 5) if b1_at_w1 is not None else None,
            "brier_first_at_05": round(b1_at_05, 5) if b1_at_05 is not None else None,
            "brier_second_at_bestw": round(b2_at_w1, 5) if b2_at_w1 is not None else None,
            "brier_second_at_05": round(b2_at_05, 5) if b2_at_05 is not None else None,
            "brier_second_at_00": round(b2_at_00, 5) if b2_at_00 is not None else None,
            "brier_second_at_10": round(b2_at_10, 5) if b2_at_10 is not None else None,
            "enough_data": enough,
            "holds_out_of_sample": holds,
        })

    out_path = "validation/blend_weight_out_of_sample_20260825.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w_csv = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w_csv.writeheader()
        w_csv.writerows(results)

    print("=== Извън-извадков тест на оптималното W (първа половина -> прилагане на втора) ===\n")
    header = (f"{'Пазар':<10} {'n1':>4} {'n2':>4} {'W* (1-ва пол.)':>15} "
              f"{'Brier2(W*)':>11} {'Brier2(0.5)':>12} {'Brier2(0.0)':>12} {'Brier2(1.0)':>12} {'извод':<20}")
    print(header)
    print("-" * len(header))
    for r in results:
        if not r["enough_data"]:
            verdict = "недостатъчно данни"
        elif r["holds_out_of_sample"]:
            verdict = "ИЗДЪРЖА - реално"
        else:
            verdict = "НЕ издържа - нагаждане"
        print(f"{r['market_code']:<10} {r['n_first']:>4} {r['n_second']:>4} {r['best_w_first_half']:>15.1f} "
              f"{r['brier_second_at_bestw']:>11.4f} {r['brier_second_at_05']:>12.4f} "
              f"{r['brier_second_at_00']:>12.4f} {r['brier_second_at_10']:>12.4f} {verdict:<20}")

    print(f"\nЗаписано: {out_path} ({len(results)} реда)")


if __name__ == "__main__":
    main()
