"""
validation/vs_market_brier_team_goals.py - 25.08.2026, разговор с Дака:
"Разшири vs_market_brier с пазарите за отборни голове (отбор над/под 1.5),
които досега липсват от всички измервания - а Дака залага основно тях."

Същият метод като validation/vs_market_brier.py (24.08.2026), приложен
върху TEAM_GOALS_GROUPS в brier_vs_market.py вместо MARKET_GROUPS - Brier
score на нашата вероятност срещу обезвигованата пазарна, по (лига, пазар),
с bootstrap CI и split-half проверка при "добра" находка. Разликата с
оригиналния скрипт: тези пазари никога не са минавали през
_blend_with_market() (виж бележката при TEAM_GOALS_GROUPS в
brier_vs_market.py) - "суров" и "смесен" тук са буквално идентични числа,
затова таблицата по-долу печата само една колона вместо две.

Употреба: python3 validation/vs_market_brier_team_goals.py
Пише:
  - validation/vs_market_brier_team_goals_detail_20260825.csv
  - validation/vs_market_brier_team_goals_combos_20260825.csv
"""
import csv
import sys

sys.path.insert(0, ".")
import system_tracker as st
import brier_vs_market as bm


def main():
    rows = st.list_predictions()
    detail = bm.build_detail_rows_team_goals(rows)
    if not detail:
        print("Няма уредени кандидати с пълна пазарна група (home_over15/under15, away_over15/under15) за анализ.")
        return

    detail_path = "validation/vs_market_brier_team_goals_detail_20260825.csv"
    with open(detail_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        w.writeheader()
        w.writerows(detail)

    combos = bm.summarize_by_league_market(detail)

    # 25.08.2026: всяка отделна лига е под MIN_N (виж таблицата по-долу -
    # най-много 26 наблюдения). Пазар x ВСИЧКИ лиги обединени добавя
    # статистическа мощ отделно от разбивката по лига (поискано "по лига",
    # но пуловете по пазар не противоречат на това - допълнителен разрез,
    # не замяна) - копие на detail с league="(всички лиги)" за отделно
    # обобщение, обединено в изхода след разбивката по лига.
    pooled_detail = [dict(d, league="(всички лиги)") for d in detail]
    pooled_combos = bm.summarize_by_league_market(pooled_detail)
    combos = combos + pooled_combos

    combos_path = "validation/vs_market_brier_team_goals_combos_20260825.csv"
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

    print(f"=== Бием ли пазара (отборни голове над/под 1.5) - {len(detail)} кандидат-изхода, "
          f"{len(combos)} комбинации лига x пазар ===\n")
    print(f"Тествани комбинации (n>={bm.MIN_N}): {mc['tested']}")
    print(f"Очаквани 'значими' по чиста случайност при alpha=0.05: ~{mc['expected_false_positives']}")
    print(f"Реално флагнати (доказано/кандидат): {mc['actual_flagged']}\n")

    header = f"{'Лига':<20} {'Пазар':<14} {'n':>4} {'Brier(нас)':>11} {'Brier(пазар)':>13} {'разлика':>9} {'статус':<18}"
    print(header)
    print("-" * len(header))
    for c in combos:
        print(f"{c['league']:<20} {c['market_code']:<14} {c['n']:>4} {c['raw_brier']:>11.4f} "
              f"{c['market_brier']:>13.4f} {c['diff_raw']:>+9.4f} {c['status']:<18}")

    print("\n=== Детайл за комбинации с n>=%d (CI + split-half при 'добра' находка) ===" % bm.MIN_N)
    any_tested = False
    for c in combos:
        if c["n"] < bm.MIN_N:
            continue
        any_tested = True
        print(f"\n{c['league']} / {c['market_code']} (n={c['n']}):")
        print(f"  CI(пазар-нас) = {c['ci_raw']} -> {c['verdict_raw']}")
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
