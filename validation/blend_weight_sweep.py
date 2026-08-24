"""
validation/blend_weight_sweep.py - продължение на т.1 (24.08.2026, "Бием ли
пазара"): BLEND_WEIGHT=0.5 е избрано число, никога не е претърсено. Тук
смятаме Brier за W=0.0 (чист модел) до W=1.0 (чист пазар) на стъпки от 0.1,
върху едни и същи уредени кандидати, за да видим дали 0.5 изобщо е близо до
оптимума - или оптимумът е близо до 1.0 (моделът не добавя нищо отгоре на
пазара) или другаде.

Използва brier_vs_market.build_detail_rows() (същите редове, същия
raw_p/market_p извод от basis raw/blended - виж докстринга там) - за ВСЕКИ
ред вече имаме и raw_p, и market_p поотделно, независимо от basis, затова
произволно тегло W се construира директно:
    blended_p(W) = W*market_p + (1-W)*raw_p
без да пипаме BLEND_WEIGHT константата в match_predictor_app.py и без да
презалитаме модела - чисто аритметично претърсване на вече изчислените
вероятности.

Само измерване - не сменя нищо в живия код.

Употреба: python3 validation/blend_weight_sweep.py
Пише validation/blend_weight_sweep_20260824.csv (ред на тегло x пазар) и
принтира таблица тегло x пазар + обща (всички пазари агрегирано).
"""
import csv
import sys

sys.path.insert(0, ".")
import system_tracker as st
import brier_vs_market as bm

WEIGHTS = [round(i / 10, 1) for i in range(0, 11)]  # 0.0, 0.1, ..., 1.0


def brier_at_weight(detail, w):
    return [(w * d["market_p"] + (1 - w) * d["raw_p"] - d["outcome"]) ** 2 for d in detail]


def main():
    rows = st.list_predictions()
    detail = bm.build_detail_rows(rows)
    if not detail:
        print("Няма уредени кандидати с пълна пазарна група за анализ.")
        return

    codes = sorted(set(d["market_code"] for d in detail))
    by_code = {c: [d for d in detail if d["market_code"] == c] for c in codes}
    n_by_code = {c: len(by_code[c]) for c in codes}

    csv_rows = []
    per_code_brier = {c: {} for c in codes}
    overall_brier = {}
    for w in WEIGHTS:
        all_sq = brier_at_weight(detail, w)
        overall_brier[w] = sum(all_sq) / len(all_sq)
        for c in codes:
            sq = brier_at_weight(by_code[c], w)
            mean_b = sum(sq) / len(sq)
            per_code_brier[c][w] = mean_b
            csv_rows.append({"weight": w, "market_code": c, "n": n_by_code[c], "brier": round(mean_b, 5)})
        csv_rows.append({"weight": w, "market_code": "ALL", "n": len(detail), "brier": round(overall_brier[w], 5)})

    out_path = "validation/blend_weight_sweep_20260824.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w_csv = csv.DictWriter(f, fieldnames=["weight", "market_code", "n", "brier"])
        w_csv.writeheader()
        w_csv.writerows(csv_rows)

    print(f"=== BLEND_WEIGHT претърсване, W=0.0 (чист модел) .. 1.0 (чист пазар), стъпка 0.1 ===")
    print(f"({len(detail)} уредени кандидата общо, по пазар n: {n_by_code})\n")

    header = f"{'W':>5} " + " ".join(f"{c:>10}" for c in codes) + f" {'ALL':>10}"
    print(header)
    print("-" * len(header))
    for w in WEIGHTS:
        line = f"{w:>5.1f} " + " ".join(f"{per_code_brier[c][w]:>10.4f}" for c in codes) + f" {overall_brier[w]:>10.4f}"
        print(line)

    print("\n=== Минимум по колона (кое тегло дава най-нисък Brier) ===")
    best_overall_w = min(WEIGHTS, key=lambda w: overall_brier[w])
    print(f"ALL:  W={best_overall_w:.1f}  (Brier={overall_brier[best_overall_w]:.4f}, срещу W=0.0: {overall_brier[0.0]:.4f}, W=0.5: {overall_brier[0.5]:.4f}, W=1.0: {overall_brier[1.0]:.4f})")
    for c in codes:
        best_w = min(WEIGHTS, key=lambda w: per_code_brier[c][w])
        print(f"{c:<10} n={n_by_code[c]:<4} W={best_w:.1f}  (Brier={per_code_brier[c][best_w]:.4f}, срещу W=0.0: {per_code_brier[c][0.0]:.4f}, W=0.5: {per_code_brier[c][0.5]:.4f}, W=1.0: {per_code_brier[c][1.0]:.4f})")

    print(f"\nЗаписано: {out_path} ({len(csv_rows)} реда)")


if __name__ == "__main__":
    main()
