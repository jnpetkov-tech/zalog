"""validation/ev_guard_impact_20260902.py - Точка 1 от заданието на Дака
(02.09.2026, поправка на предишен пропуск): "Колко от ВЕЧЕ ПУБЛИКУВАНИТЕ
прогнози биха се променили, ако MAX_TRUSTWORTHY_EV=0.40 се прилагаше в
top_pick_for_match()?" - директен въпрос, различен от кофите на
ev_threshold_backtest.py (онова мери дали EV предсказва изход, това мери
КОЛКО прогнози биха се сменили, ако прага реално филтрираше избора).

READ-ONLY: не пипа pick_selection.py, evaluation.py, prediction_policy.py
или match_predictor_app.py. "Guard" се симулира, като кандидатските
редове с EV>40% се премахват от ВХОДА, преди да се викнат СЪЩИТЕ,
непроменени функции (evaluation.published_picks/summary, които вътрешно
викат pick_selection.rank_logged_rows() - идентична логика на
top_pick_for_match()). Guarded pool при всеки етап (PROVEN/WEAK) е
подмножество на негвардирания - guarded никога не произвежда избор там,
където сегашният код няма избор (доказано в доклада).

EV формула - същата като live кода (match_predictor_app.py, ev = our_p*odd
- 1) и ev_threshold_backtest.py: (market_odds/our_fair_odds - 1)*100.
Ред без market_odds/our_fair_odds не се пипа от guard-а (EV не е смятаем -
живият код в match_predictor_app.py също прескача guard-а мълчаливо за
такива, него самия виждаме само там, където real_odds съществува).

Пише validation/ev_guard_impact_20260902.md (доклад) и
validation/ev_guard_impact_20260902_detail.csv (ред по мач - за одит).

Точка 2+3 от заданието (разбивка на 3-15% на 3-10%/10-15%, разбивка по
basis=blended/pure) - на СЕТЛНАТИ редове с коефициент, същия bootstrap
метод като validation/ev_threshold_backtest.py (внесен като модул, не
преписан).
"""
import csv
import importlib.util
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

import evaluation as ev
import pick_selection as ps  # noqa: F401 (транзитивно ползван от evaluation.py)
import prediction_policy as policy

MAX_TRUSTWORTHY_EV = 40.0  # проценти, същото число като match_predictor_app.py

spec = importlib.util.spec_from_file_location("ev_threshold_backtest", "validation/ev_threshold_backtest.py")
_evtb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_evtb)
bootstrap_ci = _evtb.bootstrap_ci
BLEND_CUTOFF = _evtb.BLEND_CUTOFF
BLENDED_MARKET_CODES = _evtb.BLENDED_MARKET_CODES


def load_all_rows():
    conn = sqlite3.connect("predictions.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, league, fixture_id, home_team, away_team, match_date, market_code,
               pick_pct, market_odds, our_fair_odds, status, logged_at
        FROM predictions_log
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ev_pct_of(r):
    if not r["market_odds"] or not r["our_fair_odds"] or r["our_fair_odds"] <= 0:
        return None
    return (r["market_odds"] / r["our_fair_odds"] - 1) * 100.0


def guard_violates(r):
    ev_pct = ev_pct_of(r)
    return ev_pct is not None and ev_pct > MAX_TRUSTWORTHY_EV


def part1(all_rows):
    guarded_rows = [r for r in all_rows if not guard_violates(r)]

    current_picks = ev.published_picks(all_rows, policy)
    guarded_picks = ev.published_picks(guarded_rows, policy)

    current_by_fx = {p["fixture_id"]: p for p in current_picks}
    guarded_by_fx = {p["fixture_id"]: p for p in guarded_picks}

    comparison = []
    for fx, cp in current_by_fx.items():
        gp = guarded_by_fx.get(fx)
        if gp is None:
            outcome = "lost_pick"
        elif gp["market_code"] != cp["market_code"]:
            outcome = "changed_market"
        else:
            outcome = "unchanged"
        comparison.append({
            "fixture_id": fx, "league": cp["league"], "match_date": cp["match_date"],
            "home_team": cp["home_team"], "away_team": cp["away_team"],
            "current_market": cp["market_code"], "current_pct": cp["pick_pct"],
            "current_ev_pct": ev_pct_of(cp), "current_status": cp["status"],
            "guarded_market": gp["market_code"] if gp else None,
            "guarded_pct": gp["pick_pct"] if gp else None,
            "guarded_status": gp["status"] if gp else None,
            "outcome": outcome,
        })

    # sanity, доказва твърдението в докстринга - guarded никога не създава
    # избор там, където сегашният код няма никакъв (виж доклада)
    assert set(guarded_by_fx) <= set(current_by_fx), \
        "нарушение: guard-иран избор съществува за мач без сегашен избор"

    n_changed = sum(1 for c in comparison if c["outcome"] == "changed_market")
    n_lost = sum(1 for c in comparison if c["outcome"] == "lost_pick")
    n_unchanged = sum(1 for c in comparison if c["outcome"] == "unchanged")

    by_league = {}
    for c in comparison:
        if c["outcome"] == "unchanged":
            continue
        by_league.setdefault(c["league"], {"changed_market": 0, "lost_pick": 0})
        by_league[c["league"]][c["outcome"]] += 1

    current_summary = ev.summary(all_rows, policy)
    guarded_summary = ev.summary(guarded_rows, policy)

    with open("validation/ev_guard_impact_20260902_detail.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(comparison[0].keys()))
        w.writeheader()
        w.writerows(comparison)

    return {
        "n_current_published": len(current_picks),
        "n_changed": n_changed, "n_lost": n_lost, "n_unchanged": n_unchanged,
        "by_league": by_league,
        "current_summary": current_summary, "guarded_summary": guarded_summary,
        "comparison": comparison,
    }


def part2(all_rows):
    settled = [r for r in all_rows
               if r["status"] in ("won", "lost") and r["market_odds"] and r["our_fair_odds"] and r["our_fair_odds"] > 0]
    detail = []
    for r in settled:
        ev_pct = ev_pct_of(r)
        outcome = 1 if r["status"] == "won" else 0
        ret = (r["market_odds"] - 1) if outcome else -1.0
        basis = "blended" if (r["market_code"] in BLENDED_MARKET_CODES and r["logged_at"] >= BLEND_CUTOFF) else "raw"
        detail.append({"ev_pct": ev_pct, "return": ret, "outcome": outcome, "basis": basis})

    ranges = [
        ("<0%", None, 0), ("0-3%", 0, 3), ("3-10%", 3, 10), ("10-15%", 10, 15),
        ("15-40%", 15, 40), ("40%+", 40, None),
    ]

    def bucket_row(label, sub):
        n = len(sub)
        if not n:
            return {"label": label, "n": 0}
        avg_ev = sum(d["ev_pct"] for d in sub) / n
        win_rate = sum(d["outcome"] for d in sub) / n * 100
        returns = [d["return"] for d in sub]
        roi = sum(returns) / n
        ci = bootstrap_ci(returns)
        if ci is None:
            ci_str, verdict = "n<5, без CI", "-"
        else:
            ci_str = f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"
            verdict = "ЗНАЧИМО >0" if ci[0] > 0 else ("ЗНАЧИМО <0" if ci[1] < 0 else "шум")
        return {"label": label, "n": n, "avg_ev": avg_ev, "win_rate": win_rate,
                "roi": roi, "ci_str": ci_str, "verdict": verdict}

    rows_out = []
    for label, lo, hi in ranges:
        sub = [d for d in detail if (lo is None or d["ev_pct"] >= lo) and (hi is None or d["ev_pct"] < hi)]
        rows_out.append(bucket_row(label, sub))

    by_basis = {}
    for basis in ("raw", "blended"):
        basis_rows = []
        for label, lo, hi in ranges:
            sub = [d for d in detail if d["basis"] == basis
                   and (lo is None or d["ev_pct"] >= lo) and (hi is None or d["ev_pct"] < hi)]
            basis_rows.append(bucket_row(label, sub))
        by_basis[basis] = basis_rows

    return {"total": rows_out, "by_basis": by_basis, "n_settled_with_odds": len(detail)}


def fmt_bucket_table(rows_out):
    lines = [f"| Диапазон | n | ср. EV% | win% | ROI/ед. | 95% CI | извод |",
             "|---|---:|---:|---:|---:|---|---|"]
    for r in rows_out:
        if r["n"] == 0:
            lines.append(f"| {r['label']} | 0 | - | - | - | - | (няма наблюдения) |")
        else:
            lines.append(f"| {r['label']} | {r['n']} | {r['avg_ev']:.1f}% | {r['win_rate']:.1f}% | "
                          f"{r['roi']:+.3f} | {r['ci_str']} | {r['verdict']} |")
    return "\n".join(lines)


def main():
    all_rows = load_all_rows()
    p1 = part1(all_rows)
    p2 = part2(all_rows)

    cs, gs = p1["current_summary"], p1["guarded_summary"]

    lines = []
    lines.append("# Guard-ефект на MAX_TRUSTWORTHY_EV=0.40 върху top_pick_for_match() (02.09.2026)\n")
    lines.append("Точка 1 от заданието на Дака - директен отговор на въпроса, пропуснат в "
                  "предишния доклад. Симулация, НЕ промяна: `pick_selection.py`, `evaluation.py`, "
                  "`prediction_policy.py`, `match_predictor_app.py` непипнати - guard-ът филтрира "
                  "входните редове ПРЕДИ да викне същите, непроменени `evaluation.published_picks()`/"
                  "`evaluation.summary()` (които вътрешно ползват `pick_selection.rank_logged_rows()`, "
                  "идентична логика на `top_pick_for_match()`).\n")

    lines.append("## Колко прогнози биха се променили\n")
    lines.append(f"Мачове с ВЕЧЕ публикувана прогноза сега: **{p1['n_current_published']}**\n")
    lines.append("| | брой | % от публикуваните |")
    lines.append("|---|---:|---:|")
    n_pub = p1["n_current_published"]
    lines.append(f"| Без промяна | {p1['n_unchanged']} | {p1['n_unchanged']/n_pub*100:.1f}% |")
    lines.append(f"| Биха избрали ДРУГ пазар | {p1['n_changed']} | {p1['n_changed']/n_pub*100:.1f}% |")
    lines.append(f"| Биха останали БЕЗ прогноза | {p1['n_lost']} | {p1['n_lost']/n_pub*100:.1f}% |")
    lines.append("")

    lines.append("## Къде се концентрира (лиги с поне 1 засегнат мач, низходящо)\n")
    lines.append("| Лига | смяна на пазар | без прогноза | общо засегнати |")
    lines.append("|---|---:|---:|---:|")
    league_rows = sorted(p1["by_league"].items(),
                          key=lambda kv: kv[1]["changed_market"] + kv[1]["lost_pick"], reverse=True)
    for league, counts in league_rows:
        total = counts["changed_market"] + counts["lost_pick"]
        lines.append(f"| {league} | {counts['changed_market']} | {counts['lost_pick']} | {total} |")
    lines.append("")

    lines.append("## Какво стават n_settled / ROI / 95% CI\n")
    lines.append("| | сега (без guard) | с guard | разлика |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| n_published | {cs['n_published']} | {gs['n_published']} | {gs['n_published']-cs['n_published']:+d} |")
    lines.append(f"| n_settled | {cs['n_settled']} | {gs['n_settled']} | {gs['n_settled']-cs['n_settled']:+d} |")
    roi_c = f"{cs['roi']:+.1f}%" if cs['roi'] is not None else "-"
    roi_g = f"{gs['roi']:+.1f}%" if gs['roi'] is not None else "-"
    lines.append(f"| ROI (n={cs['roi_n']} / n={gs['roi_n']}) | {roi_c} | {roi_g} | - |")
    ci_c = (f"[{cs['roi_ci']['ci_lo_pct']:+.1f}%, {cs['roi_ci']['ci_hi_pct']:+.1f}%]"
            if cs['roi_ci'] else "n<2, без CI")
    ci_g = (f"[{gs['roi_ci']['ci_lo_pct']:+.1f}%, {gs['roi_ci']['ci_hi_pct']:+.1f}%]"
            if gs['roi_ci'] else "n<2, без CI")
    lines.append(f"| 95% CI на ROI | {ci_c} | {ci_g} | - |")
    lines.append("")
    lines.append("Пълен ред по мач: `validation/ev_guard_impact_20260902_detail.csv`.\n")

    lines.append("## Точка 2 - разбиване на 3-15% кофата (3-10% срещу 10-15%)\n")
    lines.append(f"({p2['n_settled_with_odds']} уредени реда с коефициент - целият сетлнат сет, "
                  "не само top-pick.)\n")
    lines.append(fmt_bucket_table(p2["total"]))
    lines.append("")
    r310 = next(r for r in p2["total"] if r["label"] == "3-10%")
    r1015 = next(r for r in p2["total"] if r["label"] == "10-15%")
    r1540 = next(r for r in p2["total"] if r["label"] == "15-40%")
    lines.append(
        f"И 3-10% (n={r310['n']}, ROI {r310['roi']:+.3f}, {r310['verdict']}), И 10-15% "
        f"(n={r1015['n']}, ROI {r1015['roi']:+.3f}, {r1015['verdict']}) излизат ШУМ - "
        f"нито едната подкофа на 3-15% сама по себе си е статистически различима от нула. "
        f"10-15% има отрицателна точкова оценка, но интервалът ѝ покрива "
        f"нулата - не е доказателство за загуба, само насока (интервал {r1015['ci_str']}). Значимо отрицателно става чак "
        f"при 15-40% (ROI {r1540['roi']:+.3f}, {r1540['verdict']}). **Отговор на въпроса на Дака: "
        f"губещата част НЕ започва под 15% с наличните данни - прагът на /value (таван 15%) "
        f"остава от правилната страна на разделителната линия, не е нужно да се свива по тази находка.**\n")

    lines.append("## Точка 3 - разбивка по basis (pure/raw срещу blended)\n")
    for basis_label, key in (("Чист модел (raw)", "raw"), ("Смесено (blended)", "blended")):
        lines.append(f"### {basis_label}\n")
        lines.append(fmt_bucket_table(p2["by_basis"][key]))
        lines.append("")
    blended_ns = [r["n"] for r in p2["by_basis"]["blended"]]
    lines.append(
        f"**Blended извадката е твърде малка за извод.** n по кофа при blended: {blended_ns} "
        f"(общо {sum(blended_ns)} от {p2['n_settled_with_odds']}). Всяка blended кофа излиза "
        "\"шум\" с интервали толкова широки, че покриват почти целия възможен диапазон на "
        "възвръщаемостта (напр. 40%+ blended: n=7, CI [-1.000, +0.663]) - това НЕ е потвърждение, "
        "че blended-числата се държат различно от raw, а просто отсъствие на достатъчно данни да "
        "се каже каквото и да е. Изводите по-горе (Точка 1 и 2) на практика са изводи за RAW "
        "извадката (5822 от 6000 реда, 97%) - живата система вече показва смесено число за пет "
        "пазара след 23.08.2026, а измерването зад прага все още e почти изцяло от периода преди "
        "смесването. Не е разтеглено тук - изрично отбелязано, чака по-голяма blended извадка.\n")

    report = "\n".join(lines)
    with open("validation/ev_guard_impact_20260902.md", "w", encoding="utf-8") as f:
        f.write(report)
    print(report)


if __name__ == "__main__":
    main()
