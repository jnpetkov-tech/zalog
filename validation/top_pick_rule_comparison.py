"""
validation/top_pick_rule_comparison.py - 25.08.2026, Задача 1 от разговора с
Дака: "новата дефиниция на единствената прогноза на картата".

Сегашно "НАЙ-СИГУРЕН" на /daily = най-висока СУРОВА вероятност сред
policy-eligible кандидати (виж validation/most_confident_slot_distribution.py
same-day). Дака посочи проблема: висока вероятност не значи нищо за реалната
стойност, ако цената вече я отразява. Предложение: сред кандидатите с EV>=0,
избери най-вероятния; ако никой няма EV>=0, покажи изрично "нищо не си
струва" вместо да вадиш най-вероятния на всяка цена.

САМО измерване - не пипа сортирането/прага в match_predictor_app.py. Три
правила, сравнени върху уредените (won/lost) мачове, върху ТОЧНО същия
кандидат-пул като живата карта (_TOP_PICK_SAFE_CODES + единствения
най-вероятен htft ред за фикстурата - копие на логиката от
most_confident_slot_distribution.py същия ден, виж бележката там защо не се
импортира match_predictor_app.py директно):

  (а) "сегашно"     - policy-eligible пул, сортиран по СУРОВА вероятност,
                       топ-1 (= точно живата логика, pick_selection.
                       rank_logged_rows()).
  (б) "най-висок EV" - същият пул, ограничен до редове с логнат market_odds
                       (EV изисква цена), сортиран по EV = our_p*odds-1,
                       топ-1.
  (в) "предложено"   - същият пул с EV>=0, сортиран по СУРОВА вероятност,
                       топ-1; ако никой ред няма EV>=0 (или изобщо няма
                       market_odds за пула) - изрично "нищо не струва",
                       БЕЗ pick (не се брои като загуба).

pick_pct в predictions_log вече Е числото, което картата реално би показала
в момента на логването (включително blend за home_win/draw/away_win/
over25/under25, логван СЛЕД blend commit-а - виж brier_vs_market.py
докстринг за BLEND_CUTOFF детайлите) - затова тук не се преизчислява
моделът, директно се ползва логнатото pick_pct/market_odds, точно както
production би ги ползвал в същия момент.

Метрики за всяко правило: n избрани залога, win rate, Brier
((pick_pct/100 - outcome)^2), реализирано ROI (само върху залозите с
известен market_odds - profit = odds-1 при печалба, -1 при загуба).
Отделно: "същия подпул" сравнение - трите правила пресметнати САМО върху
мачовете, където (в) реално направи залог (изключва "нищо не струва"
случаите от всички трите правила, за честно сравнение ябълки-с-ябълки), +
paired bootstrap CI на разликата (в)-(а) в ROI и Brier върху този подпул
(bm.bootstrap_ci - същият инструмент като vs_market_brier.py).

Употреба: python3 validation/top_pick_rule_comparison.py
Пише: validation/top_pick_rule_comparison_20260825.csv
"""
import csv
import os
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import system_tracker as st  # noqa: E402
import prediction_policy as policy  # noqa: E402
import pick_selection as ps  # noqa: E402
import brier_vs_market as bm  # noqa: E402

# match_predictor_app.py, ред ~250: "над това не вярваме на модела си" (виж
# validation/ev_threshold_backtest_20260824.csv) - извън живата value_bets
# логика ТОЧНО тези крайни EV стойности се показват отделно като
# "Пренебрегнати оценки", не като препоръка. Копирано тук (не импортирано -
# виж бележката горе защо validation/ не тегли match_predictor_app.py) за
# капираната версия на правило (в) по-долу - виж находката при първото
# пускане без капак: некапирано "EV>=0" вадеше залози с EV до 152%.
MAX_TRUSTWORTHY_EV = 0.40

_TOP_PICK_SAFE_CODES = {"home_win", "draw", "away_win", "over25", "under25", "home_over15", "home_under15"}


def _is_safe_top_market(code):
    return code in _TOP_PICK_SAFE_CODES or code.startswith("htft:")


def candidate_rows_for_fixture(rows):
    """Само уредени (won/lost) редове от safe пула, htft сведено до
    единствения най-вероятен ред за фикстурата - виж докстринга по-горе."""
    safe = [r for r in rows if _is_safe_top_market(r["market_code"]) and r["status"] in ("won", "lost")]
    htft_rows = [r for r in safe if r["market_code"].startswith("htft:")]
    non_htft = [r for r in safe if not r["market_code"].startswith("htft:")]
    if htft_rows:
        best_htft = max(htft_rows, key=lambda r: r["pick_pct"] or 0)
        return non_htft + [best_htft]
    return non_htft


def with_ev(rows):
    out = []
    for r in rows:
        r = dict(r)
        if r.get("market_odds"):
            r["_ev"] = (r["pick_pct"] / 100.0) * r["market_odds"] - 1
        else:
            r["_ev"] = None
        out.append(r)
    return out


def pick_a(pool):
    """Сегашно: policy-eligible, сортиран по сурова вероятност - топ-1.
    pool вече е eligible_pool (sorted desc by pick_pct), директно [0]."""
    return pool[0] if pool else None


def pick_b(pool):
    """Най-висок EV сред редовете с известна цена."""
    with_odds = [r for r in pool if r["_ev"] is not None]
    if not with_odds:
        return None
    return max(with_odds, key=lambda r: r["_ev"])


def pick_c(pool, cap=None):
    """Най-висока вероятност сред редовете с EV>=0 (cap=None, буквалното
    предложение на Дака) или 0<=EV<=cap (капирана версия - виж
    MAX_TRUSTWORTHY_EV бележката горе). None = 'нищо не струва'."""
    nonneg = [r for r in pool if r["_ev"] is not None and r["_ev"] >= 0
              and (cap is None or r["_ev"] <= cap)]
    if not nonneg:
        return None
    return max(nonneg, key=lambda r: r["pick_pct"] or 0)


def outcome_of(row):
    return 1 if row["status"] == "won" else 0


def profit_of(row):
    if not row.get("market_odds"):
        return None
    return (row["market_odds"] - 1) if row["status"] == "won" else -1.0


def summarize(picks):
    """picks: списък от избрани редове (не None). Връща n/win_rate/brier/
    roi(n_roi)/avg_ev."""
    n = len(picks)
    if n == 0:
        return {"n": 0, "win_rate": None, "brier": None, "roi": None, "n_roi": 0, "avg_ev": None}
    wins = sum(outcome_of(r) for r in picks)
    brier = sum((r["pick_pct"] / 100.0 - outcome_of(r)) ** 2 for r in picks) / n
    profits = [profit_of(r) for r in picks if profit_of(r) is not None]
    roi = sum(profits) / len(profits) if profits else None
    evs = [r["_ev"] for r in picks if r["_ev"] is not None]
    avg_ev = sum(evs) / len(evs) if evs else None
    return {"n": n, "win_rate": round(wins / n * 100, 2), "brier": round(brier, 4),
            "roi": round(roi * 100, 2) if roi is not None else None, "n_roi": len(profits),
            "avg_ev": round(avg_ev * 100, 2) if avg_ev is not None else None}


def main():
    rows = st.list_predictions()
    by_fixture = defaultdict(list)
    for r in rows:
        by_fixture[(r["fixture_id"], r["league"])].append(r)

    a_picks, b_picks, c_picks, cc_picks = [], [], [], []
    c_no_value = 0
    cc_no_value = 0
    n_no_settled_candidates = 0
    n_no_eligible = 0
    matched_a, matched_b, matched_c = [], [], []  # подпул, само мачове където (в) направи залог
    matched_a_cc, matched_cc = [], []  # подпул, само мачове където (в') направи залог
    agree_ac = 0
    disagree_ac = []
    agree_acc = 0

    for (fixture_id, league), frows in by_fixture.items():
        candidates = candidate_rows_for_fixture(frows)
        if not candidates:
            n_no_settled_candidates += 1
            continue
        pool = ps.rank_logged_rows(candidates, league, policy, n=99)
        if not pool:
            n_no_eligible += 1
            continue
        pool = with_ev(pool)

        pa, pb, pc, pcc = pick_a(pool), pick_b(pool), pick_c(pool), pick_c(pool, cap=MAX_TRUSTWORTHY_EV)
        if pa is not None:
            a_picks.append(pa)
        if pb is not None:
            b_picks.append(pb)
        if pc is not None:
            c_picks.append(pc)
        else:
            c_no_value += 1
        if pcc is not None:
            cc_picks.append(pcc)
        else:
            cc_no_value += 1

        if pc is not None and pa is not None and pb is not None:
            matched_a.append(pa)
            matched_b.append(pb)
            matched_c.append(pc)
            if pa["market_code"] == pc["market_code"]:
                agree_ac += 1
            else:
                disagree_ac.append((pa, pc))

        if pcc is not None and pa is not None:
            matched_a_cc.append(pa)
            matched_cc.append(pcc)
            if pa["market_code"] == pcc["market_code"]:
                agree_acc += 1

    print(f"=== Задача 1: три правила за 'единствената прогноза' ===")
    print(f"{len(by_fixture)} мача общо в predictions_log -> {n_no_settled_candidates} без нито един уреден "
          f"(won/lost) кандидат от safe пула -> {len(by_fixture) - n_no_settled_candidates - n_no_eligible} "
          f"мача с уредени кандидати ({n_no_eligible} от тях без policy-eligible кандидат след филтрите)\n")

    print(f"{'Правило':<28} {'n':>5} {'win %':>7} {'Brier':>7} {'ROI %':>8} {'n(ROI)':>7} {'avg EV %':>9}")
    print("-" * 75)
    rows_out = []
    for label, picks, extra in (
        ("(а) сегашно (max prob)", a_picks, {}),
        ("(б) най-висок EV", b_picks, {}),
        ("(в) предложено (prob|EV>=0)", c_picks, {"n_no_value": c_no_value}),
        ("(в') предл.+капирано EV<=40%", cc_picks, {"n_no_value": cc_no_value}),
    ):
        s = summarize(picks)
        print(f"{label:<28} {s['n']:>5} {s['win_rate']!s:>7} {s['brier']!s:>7} {s['roi']!s:>8} "
              f"{s['n_roi']:>7} {s['avg_ev']!s:>9}")
        rows_out.append({"scope": "пълен пул", "rule": label, **s, **extra})
    print(f"\n(в) 'нищо не струва' (EV<0 за всички/без данни за цена): {c_no_value} мача - "
          "НЕ се брои като загуба, изрично без залог.")

    print(f"\n=== Същия подпул (само мачовете, където (в) реално заложи, n={len(matched_a)}) ===")
    print(f"{'Правило':<28} {'n':>5} {'win %':>7} {'Brier':>7} {'ROI %':>8} {'n(ROI)':>7} {'avg EV %':>9}")
    print("-" * 75)
    matched_summaries = {}
    for label, picks in (("(а) сегашно", matched_a), ("(б) най-висок EV", matched_b), ("(в) предложено", matched_c)):
        s = summarize(picks)
        matched_summaries[label] = (s, picks)
        print(f"{label:<28} {s['n']:>5} {s['win_rate']!s:>7} {s['brier']!s:>7} {s['roi']!s:>8} "
              f"{s['n_roi']:>7} {s['avg_ev']!s:>9}")
        rows_out.append({"scope": "подпул (в) заложи", "rule": label, **s})

    n_matched = len(matched_a)
    print(f"\n(а) и (в) избраха ЕДИН И СЪЩ пазар в {agree_ac}/{n_matched} мача "
          f"({agree_ac/n_matched*100:.1f}%)" if n_matched else "")
    print(f"Различават се в {len(disagree_ac)} мача.")

    if n_matched >= 5:
        paired_profits = [(profit_of(a), profit_of(c)) for a, c in zip(matched_a, matched_c)]
        paired_profits = [(pa_, pc_) for pa_, pc_ in paired_profits if pa_ is not None and pc_ is not None]
        if len(paired_profits) >= 5:
            diffs_roi = [pc_ - pa_ for pa_, pc_ in paired_profits]
            ci_roi = bm.bootstrap_ci(diffs_roi)
            print(f"\nPaired bootstrap CI на ROI разлика (в)-(а), n={len(diffs_roi)}: {ci_roi} "
                  f"(съдържа 0 -> шум; >0 -> (в) реално по-добро)")
        diffs_brier = [(a["pick_pct"] / 100.0 - outcome_of(a)) ** 2 - (c["pick_pct"] / 100.0 - outcome_of(c)) ** 2
                       for a, c in zip(matched_a, matched_c)]
        ci_brier = bm.bootstrap_ci(diffs_brier)
        print(f"Paired bootstrap CI на Brier подобрение (а)-(в) (положително = (в) по-точно), "
              f"n={len(diffs_brier)}: {ci_brier}")

    print(f"\n=== Капирана версия (в'): подпул където (в') реално заложи, n={len(matched_a_cc)} ===")
    print(f"{'Правило':<28} {'n':>5} {'win %':>7} {'Brier':>7} {'ROI %':>8} {'n(ROI)':>7} {'avg EV %':>9}")
    print("-" * 75)
    for label, picks in (("(а) сегашно", matched_a_cc), ("(в') капирано", matched_cc)):
        s = summarize(picks)
        print(f"{label:<28} {s['n']:>5} {s['win_rate']!s:>7} {s['brier']!s:>7} {s['roi']!s:>8} "
              f"{s['n_roi']:>7} {s['avg_ev']!s:>9}")
        rows_out.append({"scope": "подпул (в') заложи", "rule": label, **s})
    n_matched_cc = len(matched_a_cc)
    if n_matched_cc:
        print(f"(а) и (в') избраха ЕДИН И СЪЩ пазар в {agree_acc}/{n_matched_cc} мача "
              f"({agree_acc/n_matched_cc*100:.1f}%)")
        paired_cc = [(profit_of(a), profit_of(c)) for a, c in zip(matched_a_cc, matched_cc)]
        paired_cc = [(pa_, pc_) for pa_, pc_ in paired_cc if pa_ is not None and pc_ is not None]
        if len(paired_cc) >= 5:
            diffs_roi_cc = [pc_ - pa_ for pa_, pc_ in paired_cc]
            ci_roi_cc = bm.bootstrap_ci(diffs_roi_cc)
            print(f"Paired bootstrap CI на ROI разлика (в')-(а), n={len(diffs_roi_cc)}: {ci_roi_cc}")

    print("\n=== Мачове, където (а) и (в) избират различен пазар (примери, до 10) ===")
    for pa, pc in disagree_ac[:10]:
        print(f"  fixture {pa['fixture_id']} ({pa['league']}): (а)={pa['market_code']} "
              f"(p={pa['pick_pct']:.0f}%, {pa['status']}) vs (в)={pc['market_code']} "
              f"(p={pc['pick_pct']:.0f}%, EV={pc['_ev']*100:.1f}%, {pc['status']})")

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             f"top_pick_rule_comparison_{date.today().strftime('%Y%m%d')}.csv")
    fieldnames = ["scope", "rule", "n", "win_rate", "brier", "roi", "n_roi", "avg_ev", "n_no_value"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows_out:
            w.writerow({k: r.get(k) for k in fieldnames})
    print(f"\nЗаписано: {out_path} ({len(rows_out)} реда)")


if __name__ == "__main__":
    main()
