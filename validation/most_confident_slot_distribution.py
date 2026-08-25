"""
validation/most_confident_slot_distribution.py - 25.08.2026, разговор с Дака:

Хипотеза: слотът "НАЙ-СИГУРЕН" на /daily е доминиран от "отбор под 1.5
гола" - не защото моделът е особено уверен там, а защото този пазар има
структурно най-висока базова вероятност (среден отбор вкарва ~1.3 гола ->
P(0 или 1) ~ 65-70%), докато 1X2 и над/под 2.5 рядко минават 60-65%. Същият
механизъм като находката от 11.08.2026 ("под 9.5 корнера" - 41 от 104 пъти,
виж CLAUDE_HANDOFF.md H.1) - сортирането по СУРОВА вероятност винаги избира
пазара с най-изкривена базова честота, независимо от реална увереност.

Метод: "НАЙ-СИГУРЕН" на живо е picks_raw[0] от top_picks_with_code() ->
pick_selection.rank_candidates() (виж match_predictor_app.py, build_pick_card
docstring) - топ-1 сред policy-eligible кандидати от ТОЧНО фиксиран пул
кодове (_TOP_PICK_SAFE_CODES = home_win/draw/away_win/over25/under25/
home_over15/home_under15, плюс ЕДИН htft: код - най-вероятната htft
комбинация за мача, не всички). predictions_log вече съдържа ТОЧНО тези
изчислени по мач вероятности (log_all_markets() логва суровия pick_pct в
момента на изчислението, преди blend/policy филтриране) - затова тук не се
преизчислява моделът наново, а се преизползва pick_selection.rank_logged_rows()
(същата канонична функция, която /daily реално вика за index_home) върху
логнатите редове на всеки мач, филтрирани до същия код-пул и с htft
сведено до единствения кандидат с най-висок pick_pct за фикстурата (=
argmax(ht_ft_probs), точно логиката в _raw_candidates()).

Само измерване - не пипа никаква прагова стойност/логика.

Употреба: python3 validation/most_confident_slot_distribution.py
Пише: validation/most_confident_slot_distribution_20260825.csv
  (ред на market_code с брой/дял победи на слота "най-сигурен", общо и по
  лига)
"""
import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import system_tracker as st  # noqa: E402
import prediction_policy as policy  # noqa: E402
import pick_selection as ps  # noqa: E402

# Копие на _TOP_PICK_SAFE_CODES/_is_safe_top_market от match_predictor_app.py
# (реда ~1243) - НЕ импортираме целия Flask модул тук (CLAUDE.md: не пипай/
# зареждай match_predictor_app.py небрежно; validation/ скриптовете исторически
# работят само върху football_lib/system_tracker/prediction_policy/
# pick_selection - чисти модули без Flask странични ефекти).
_TOP_PICK_SAFE_CODES = {"home_win", "draw", "away_win", "over25", "under25", "home_over15", "home_under15"}


def _is_safe_top_market(code):
    return code in _TOP_PICK_SAFE_CODES or code.startswith("htft:")


def candidate_rows_for_fixture(rows):
    """rows: всички логнати редове за ЕДНА фикстура. Връща подмножеството,
    което реално е било кандидат за picks_raw (safe codes + единствения
    най-вероятен htft ред) - възпроизвежда _raw_candidates()."""
    safe = [r for r in rows if _is_safe_top_market(r["market_code"])]
    htft_rows = [r for r in safe if r["market_code"].startswith("htft:")]
    non_htft = [r for r in safe if not r["market_code"].startswith("htft:")]
    if htft_rows:
        best_htft = max(htft_rows, key=lambda r: r["pick_pct"] or 0)
        return non_htft + [best_htft]
    return non_htft


def main():
    rows = st.list_predictions()
    by_fixture = defaultdict(list)
    for r in rows:
        by_fixture[(r["fixture_id"], r["league"])].append(r)

    winner_counts = Counter()
    winner_counts_by_league = defaultdict(Counter)
    n_matches_considered = 0
    n_matches_no_winner = 0

    for (fixture_id, league), frows in by_fixture.items():
        candidates = candidate_rows_for_fixture(frows)
        if not candidates:
            continue
        ranked = ps.rank_logged_rows(candidates, league, policy, n=1)
        n_matches_considered += 1
        if not ranked:
            n_matches_no_winner += 1
            continue
        code = ranked[0]["market_code"]
        winner_counts[code] += 1
        winner_counts_by_league[league][code] += 1

    total_wins = sum(winner_counts.values())
    print(f"=== Слотът 'НАЙ-СИГУРЕН' - {n_matches_considered} мача разгледани "
          f"({n_matches_no_winner} без eligible кандидат), {total_wins} с победител ===\n")
    print(f"{'Пазар':<16} {'победи':>7} {'дял':>7}")
    print("-" * 32)
    for code, n in winner_counts.most_common():
        print(f"{code:<16} {n:>7} {n/total_wins*100:>6.1f}%")

    team15 = winner_counts.get("home_over15", 0) + winner_counts.get("home_under15", 0)
    print(f"\nhome_over15 + home_under15 общо: {team15}/{total_wins} = {team15/total_wins*100:.1f}%")
    print("(same_mechanism_as: под 9.5 корнера 11.08.2026, 41/104 = 39.4% - виж CLAUDE_HANDOFF.md H.1)")

    rows_out = []
    for code, n in winner_counts.most_common():
        rows_out.append({"league": "(всички лиги)", "market_code": code, "wins": n,
                          "share_pct": round(n / total_wins * 100, 2)})
    for league in sorted(winner_counts_by_league):
        lc = winner_counts_by_league[league]
        ltotal = sum(lc.values())
        for code, n in lc.most_common():
            rows_out.append({"league": league, "market_code": code, "wins": n,
                              "share_pct": round(n / ltotal * 100, 2)})

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             f"most_confident_slot_distribution_{date.today().strftime('%Y%m%d')}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["league", "market_code", "wins", "share_pct"])
        w.writeheader()
        w.writerows(rows_out)
    print(f"\nЗаписано: {out_path} ({len(rows_out)} реда)")


if __name__ == "__main__":
    main()
