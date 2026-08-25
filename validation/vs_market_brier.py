"""
validation/vs_market_brier.py - Точка 1 от разговора с Дака 24.08.2026:
"Бием ли пазара, изобщо." Записан бектест на brier_vs_market.py (виж
докстринга там за пълната методология: три версии на нашето число - чист
модел/смесено 50/50/пазар като контрола, - basis raw/blended, split-half
проверка за всяка "добра" находка, бройка на тествани комбинации срещу
очаквани фалшиви положителни при alpha=0.05).

Употреба: python3 validation/vs_market_brier.py
Пише:
  - validation/vs_market_brier_detail_20260825.csv (ред на кандидат-изход)
  - validation/vs_market_brier_combos_20260825.csv (ред на лига x пазар)
и принтира пълния доклад в конзолата (никакво общо число без разбивката по-
долу - виж правилото на Дака).
"""
import csv
import sys

sys.path.insert(0, ".")
import system_tracker as st
import brier_vs_market as bm


def main():
    rows = st.list_predictions()
    detail = bm.build_detail_rows(rows)
    if not detail:
        print("Няма уредени кандидати с пълна пазарна група за анализ.")
        return

    detail_path = "validation/vs_market_brier_detail_20260825.csv"
    with open(detail_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        w.writeheader()
        w.writerows(detail)

    combos = bm.summarize_by_league_market(detail)
    combos_path = "validation/vs_market_brier_combos_20260825.csv"
    combo_fields = ["league", "market_code", "n", "n_basis_raw", "n_basis_blended",
                     "raw_brier", "blend_brier", "market_brier", "diff_raw", "diff_blend",
                     "diff_control", "status", "ci_raw", "ci_blend", "verdict_raw", "verdict_blend"]
    with open(combos_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=combo_fields)
        w.writeheader()
        for c in combos:
            row = {k: c.get(k) for k in combo_fields}
            w.writerow(row)

    mc = bm.multiple_comparisons_summary(combos)

    print(f"=== Бием ли пазара - {len(detail)} кандидат-изхода, {len(combos)} комбинации лига x пазар ===\n")
    print(f"Тествани комбинации (n>={bm.MIN_N}): {mc['tested']}")
    print(f"Очаквани 'значими' по чиста случайност при alpha=0.05: ~{mc['expected_false_positives']}")
    print(f"Реално флагнати (доказано/кандидат): {mc['actual_flagged']}")
    print("(контрола: пазар срещу пазар - разликата е точно 0.000 по дефиниция за всяка комбинация,")
    print(" не се печата отделно - проверка, че методологията не лъже сама себе си, вградена в кода)\n")

    header = (f"{'Лига':<20} {'Пазар':<10} {'n':>4} {'суров':>6} {'смесен':>7} "
              f"{'Brier(нас,суров)':>16} {'Brier(нас,смес)':>16} {'Brier(пазар)':>13} "
              f"{'разл.суров':>11} {'разл.смес':>10} {'статус':<18}")
    print(header)
    print("-" * len(header))
    for c in combos:
        print(f"{c['league']:<20} {c['market_code']:<10} {c['n']:>4} {c['n_basis_raw']:>6} {c['n_basis_blended']:>7} "
              f"{c['raw_brier']:>16.4f} {c['blend_brier']:>16.4f} {c['market_brier']:>13.4f} "
              f"{c['diff_raw']:>+11.4f} {c['diff_blend']:>+10.4f} {c['status']:<18}")

    print("\n=== Детайл за комбинации с n>=%d (CI + split-half при 'добра' находка) ===" % bm.MIN_N)
    any_tested = False
    for c in combos:
        if c["n"] < bm.MIN_N:
            continue
        any_tested = True
        print(f"\n{c['league']} / {c['market_code']} (n={c['n']}, от тях {c['n_basis_blended']} смесени):")
        print(f"  CI(пазар-суров)  = {c['ci_raw']}  -> {c['verdict_raw']}")
        print(f"  CI(пазар-смесен) = {c['ci_blend']} -> {c['verdict_blend']}")
        if c["split_half"]:
            sh = c["split_half"]
            print(f"  split-half: първа половина n={sh['first']['n']} -> {sh['first']['verdict']}, "
                  f"втора половина n={sh['second']['n']} -> {sh['second']['verdict']} "
                  f"=> {'ПОВТАРЯ СЕ' if sh['replicates'] else 'НЕ се повтаря в двете половини'}")
    if not any_tested:
        print("(няма комбинация с n>=%d - вижте таблицата по-горе, всичко е 'недостатъчно данни')" % bm.MIN_N)

    print(f"\nЗаписано: {detail_path} ({len(detail)} реда), {combos_path} ({len(combos)} реда)")


if __name__ == "__main__":
    main()
