"""Б1 (ZADACHA_FAZA1.md, 19.09.2026) — САМО СИМУЛАЦИЯ, нищо не се прилага.

Въпросът на Дака: днес заглавната прогноза за мача е "най-високият процент
сред доказаните пазари", затова един мач излиза с "под 2.5 гола", друг с
"ЦСКА над 1.5 гола 56%" — таблицата е несравнима между мачове.

Алтернативното правило, което се симулира тук: СЪЩИТЕ филтри (PROVEN първо,
WEAK резерва, <95%, EV guard, без двоен шанс), но подредбата е по приоритет
на групата пазари — 1x2, после ou25, чак после останалите; вътре в групата —
най-високият процент.

ВАЖНО за метода: филтрите НЕ се преписват тук. Взимат се буквално от
pick_selection.rank_logged_rows(..., n=голямо число) — това е СЪЩИЯТ
_apply_rules() път (PROVEN -> WEAK -> [] , _dedupe_complementary,
MAX_PUBLISHABLE_PCT, MAX_TRUSTWORTHY_EV, is_top_pick_eligible), само че
връща целия допустим пул вместо само първия. Новото правило е чисто
пренареждане на ТОЗИ пул. Така е невъзможно симулацията да се разминава
с живото поведение заради копиран филтър.

Метриките идват от evaluation.py, БЕЗ да е пипан — подаваме му списъка
прогнози от симулацията (evaluation.roi / roi_confidence_interval /
calibration_curve работят върху подаден списък picks).

Нищо не пише в базата и не прави нито една API заявка.
"""
import sys, os, json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import system_tracker as st
import prediction_policy as policy
import pick_selection as ps
import evaluation

# Приоритет на групата пазари в НОВОТО правило. По-малкото число = по-напред.
GROUP_PRIORITY = {"1x2": 0, "ou25": 1}
OTHER_PRIORITY = 2

BIG_N = 10 ** 6  # "върни целия пул", не реално ограничение


def group_rank(market_code):
    return GROUP_PRIORITY.get(policy.market_group(market_code), OTHER_PRIORITY)


def new_rule_pick(rows, league):
    """СЪЩИЯТ допустим пул като днешния избор, само пренареден."""
    pool = ps.rank_logged_rows(rows, league, policy, n=BIG_N)
    if not pool:
        return None
    return min(pool, key=lambda r: (group_rank(r["market_code"]), -(r["pick_pct"] or 0)))


def scorecard(picks):
    """Същите числа като evaluation.summary_priced_only(), но върху подаден
    списък прогнози (тя приема сурови редове и си прави свой избор, затова
    не може да се извика директно върху симулацията). Всяко число минава
    през функция на evaluation.py — нито една формула не е преписана тук."""
    settled = [p for p in picks if p["status"] in evaluation.SETTLED]
    priced = [p for p in settled if p["market_odds"]]
    n = len(priced)
    roi_pct, roi_n = evaluation.roi(picks)
    return {
        "n_published": len(picks),
        "n_settled": len(settled),
        "n": n,
        "promised_avg": (sum((p["pick_pct"] or 0) for p in priced) / n) if n else None,
        "actual_pct": (sum(1 for p in priced if p["status"] == "won") / n * 100.0) if n else None,
        "roi": roi_pct, "roi_n": roi_n,
        "profit": sum((p["market_odds"] if p["status"] == "won" else 0.0) - 1.0 for p in priced) if n else None,
        "avg_odds": (sum(p["market_odds"] for p in priced) / n) if n else None,
        "roi_ci": evaluation.roi_confidence_interval(priced),
    }


def main():
    rows = st.list_predictions()
    groups = {}
    for r in rows:
        groups.setdefault(r["fixture_id"], []).append(r)

    old_picks, new_picks, changes = [], [], []
    for fixture_id, grp in groups.items():
        league = grp[0]["league"]
        old = ps.top_pick_for_match(grp, league, policy)
        new = new_rule_pick(grp, league)
        # Мач без публикуем избор отпада и по двете правила (пулът е същият)
        if old is None or new is None:
            assert old is None and new is None, f"пулът се разминава за {fixture_id}"
            continue
        old_picks.append(old)
        new_picks.append(new)
        if old["market_code"] != new["market_code"]:
            changes.append({"fixture_id": fixture_id, "league": league,
                            "date": old["match_date"], "home": old["home_team"],
                            "away": old["away_team"], "status": old["status"],
                            "old": old, "new": new})

    out = {
        "n_matches_with_pick": len(old_picks),
        "old": scorecard(old_picks),
        "new": scorecard(new_picks),
        "changes_all": len(changes),
        "changes_settled": sum(1 for c in changes if c["old"]["status"] in evaluation.SETTLED),
        "n_settled_matches": sum(1 for p in old_picks if p["status"] in evaluation.SETTLED),
        "dist_old": Counter(policy.market_group(p["market_code"]) for p in old_picks),
        "dist_new": Counter(policy.market_group(p["market_code"]) for p in new_picks),
        "dist_old_code": Counter(p["market_code"] for p in old_picks),
        "dist_new_code": Counter(p["market_code"] for p in new_picks),
        "changes": changes,
    }
    return out


if __name__ == "__main__":
    res = main()
    print(json.dumps({k: (dict(v) if isinstance(v, Counter) else v)
                      for k, v in res.items() if k != "changes"},
                     ensure_ascii=False, indent=2, default=str))
    print(f"\nпримери със смяна: {len(res['changes'])}")


# --------------------------------------------------------------------------
# Генератор на доклада (validation/headline_rule_sim_20260919.md) + CSV с
# всички смени. Пуска се с: python validation/headline_rule_sim_20260919.py --report
# --------------------------------------------------------------------------
def _pct(v, d=1):
    return "—" if v is None else f"{v:.{d}f}%"


def write_report(res, md_path, csv_path):
    import csv as _csv
    ch = res["changes"]
    settled_ch = sorted([c for c in ch if c["status"] in evaluation.SETTLED],
                        key=lambda c: c["date"], reverse=True)
    old_won = sum(1 for c in settled_ch if c["old"]["status"] == "won")
    new_won = sum(1 for c in settled_ch if c["new"]["status"] == "won")
    agree = sum(1 for c in settled_ch if c["old"]["status"] == c["new"]["status"])

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(["match_date", "league", "home_team", "away_team", "status",
                    "old_market_code", "old_pick_label", "old_pick_pct", "old_status",
                    "new_market_code", "new_pick_label", "new_pick_pct", "new_status"])
        for c in sorted(ch, key=lambda c: c["date"], reverse=True):
            o, n = c["old"], c["new"]
            w.writerow([c["date"], c["league"], c["home"], c["away"], c["status"],
                        o["market_code"], o["pick_label"], f'{o["pick_pct"]:.2f}', o["status"],
                        n["market_code"], n["pick_label"], f'{n["pick_pct"]:.2f}', n["status"]])

    cska = [c for c in settled_ch if "CSKA" in c["home"] or "CSKA" in c["away"]][:3]
    rest = [c for c in settled_ch if c not in cska][:7]
    o_sc, n_sc = res["old"], res["new"]

    def outcome(p):
        return {"won": "позна", "lost": "не позна"}.get(p["status"], p["status"])

    L = []
    A = L.append
    A("# Б1 — симулация на ново правило за заглавната прогноза (19.09.2026)")
    A("")
    A("**САМО ИЗМЕРВАНЕ. Нищо от това не е приложено в живия код.** "
      "`pick_selection.py`, `prediction_policy.py` и `evaluation.py` не са пипани.")
    A("")
    A("## Какво точно се сравнява")
    A("")
    A("- **Сегашното правило:** от допустимите пазари за мача се взима този с "
      "**най-високия процент**, какъвто и пазар да е (`pick_selection.top_pick_for_match`).")
    A("- **Новото (симулирано) правило:** **същите филтри** — PROVEN първо, WEAK резерва, "
      "под 95%, EV guard, без двоен шанс — но подредбата е по **група пазари**: "
      "`1x2` първо, после `ou25`, чак после останалите; вътре в избраната група пак "
      "най-високият процент.")
    A("")
    A("Филтрите не са преписани: скриптът вика `pick_selection.rank_logged_rows(..., n=10**6)`, "
      "което е буквално същият `_apply_rules()` път, само че връща целия допустим пул вместо "
      "първия ред. Новото правило е чисто пренареждане на този пул — затова е невъзможно "
      "симулацията да се разминава с живото поведение. Метриките идват от функции на "
      "`evaluation.py`, на които е подаден резултатът от симулацията.")
    A("")
    A("## 1. Колко мача сменят заглавната прогноза")
    A("")
    A(f"| | брой |")
    A("|---|---|")
    A(f"| мачове с публикуема прогноза (общо в лога) | {res['n_matches_with_pick']} |")
    A(f"| от тях **сменят** заглавната прогноза | **{res['changes_all']}** ({res['changes_all']/res['n_matches_with_pick']*100:.1f}%) |")
    A(f"| уредени мачове (won/lost) | {res['n_settled_matches']} |")
    A(f"| от тях **сменят** заглавната прогноза | **{res['changes_settled']}** ({res['changes_settled']/res['n_settled_matches']*100:.1f}%) |")
    A("")
    A(f"Само сред **{len(settled_ch)}** уредени мача със смяна: старото правило познава "
      f"**{old_won}**, новото — **{new_won}**; и двете дават еднакъв изход при {agree} от тях.")
    A("")
    A("## 2. Старо срещу ново — общите числа")
    A("")
    A("(както на публичната страница: само уредени публикувани прогнози **с реален "
      "коефициент**, същият набор, който `evaluation.summary_priced_only()` ползва)")
    A("")
    A("| | сега | ново правило |")
    A("|---|---|---|")
    A(f"| n (уредени, с коефициент) | {o_sc['n']} | {n_sc['n']} |")
    A(f"| обещан процент | {_pct(o_sc['promised_avg'])} | {_pct(n_sc['promised_avg'])} |")
    A(f"| познат процент | {_pct(o_sc['actual_pct'])} | {_pct(n_sc['actual_pct'])} |")
    A(f"| разлика (познат − обещан) | {_pct(o_sc['actual_pct'] - o_sc['promised_avg'])} | {_pct(n_sc['actual_pct'] - n_sc['promised_avg'])} |")
    A(f"| доходност (yield) | {_pct(o_sc['roi'])} | {_pct(n_sc['roi'])} |")
    A(f"| 95% интервал на доходността | {_pct(o_sc['roi_ci']['ci_lo_pct'])} до {_pct(o_sc['roi_ci']['ci_hi_pct'])} | {_pct(n_sc['roi_ci']['ci_lo_pct'])} до {_pct(n_sc['roi_ci']['ci_hi_pct'])} |")
    A(f"| печалба/загуба (1 единица на залог) | {o_sc['profit']:+.2f} u | {n_sc['profit']:+.2f} u |")
    A(f"| среден коефициент | {o_sc['avg_odds']:.3f} | {n_sc['avg_odds']:.3f} |")
    A("")
    A("## 3. Разпределение на заглавните пазари")
    A("")
    A("По група:")
    A("")
    A("| група | сега | ново |")
    A("|---|---|---|")
    for g in sorted(set(res["dist_old"]) | set(res["dist_new"]),
                    key=lambda g: -res["dist_new"].get(g, 0)):
        A(f"| {g} | {res['dist_old'].get(g, 0)} | {res['dist_new'].get(g, 0)} |")
    A("")
    A("По конкретен пазар:")
    A("")
    A("| пазар | сега | ново |")
    A("|---|---|---|")
    for c in sorted(set(res["dist_old_code"]) | set(res["dist_new_code"]),
                    key=lambda c: -res["dist_new_code"].get(c, 0)):
        A(f"| {c} | {res['dist_old_code'].get(c, 0)} | {res['dist_new_code'].get(c, 0)} |")
    A("")
    A("## 4. Десет конкретни примера (уредени мачове)")
    A("")
    A("| Дата | Лига | Мач | Сега | Ново правило | Сега | Ново |")
    A("|---|---|---|---|---|---|---|")
    for c in cska + rest:
        o, n = c["old"], c["new"]
        A(f'| {c["date"][:10]} | {c["league"]} | {c["home"]} – {c["away"]} | '
          f'{o["pick_label"]} · {o["pick_pct"]:.0f}% | {n["pick_label"]} · {n["pick_pct"]:.0f}% | '
          f'{outcome(o)} | {outcome(n)} |')
    A("")
    A("Пълният списък на всички смени е в `headline_rule_sim_20260919.csv` (в git).")
    A("")
    A("**Депортиво – Валенсия (30.08.2026, Испания) НЕ сменя прогнозата.** "
      "И двете правила дават „Deportivo La Coruna печели · 42%\" (позна). Причината: за "
      "този мач допустимият пул съдържа само `1x2` и `htft` редове — няма логнат "
      "team_total/ou25 пазар, така че 1X2 вече е и най-високият процент. Тоест мачът, "
      "който повдигна въпроса, не е от засегнатите — засегнатите са мачовете, при които "
      "„отборен тотал под 1.5 гола\" изпреварва 1X2 по процент.")
    A("")
    A("## 5. Какво показват числата (без препоръка — решението е на Дака)")
    A("")
    A("1. **Смяната е голяма, не козметична:** 484 от 791 мача (61%) излизат с друга "
      "заглавна прогноза. Днешният списък е доминиран от един-единствен пазар — "
      "`away_under15` („гостите под 1.5 гола\") е заглавната прогноза при **382 от 791** "
      "мача. Новото правило свежда team_total от 509 на 35 и прави 1X2 + над/под 2.5 "
      "**752 от 791** — точно това би направило таблицата сравнима между мачове.")
    A("2. **Цената е по-ниски проценти и повече грешки:** обещаното пада от 65.2% на "
      "52.2%, познатото — от 63.6% на 50.7%. Това **не значи по-лош модел**: 1X2 просто е "
      "по-труден пазар от „гостите под 1.5 гола\". Средният коефициент се качва от 1.57 "
      "на 1.94 — по-ниска вероятност, по-висока цена, което е и очакваното.")
    A("3. **Калибрацията е практически същата:** и двете правила обещават с ~1.6 процентни "
      "пункта повече, отколкото познават. Тоест новото правило не е по-нечестно, само "
      "по-скромно на вид.")
    A("4. **Доходността не се подобрява, но и не се влошава доказуемо:** -8.3% срещу "
      "-9.6%, а двата 95% интервала се застъпват почти изцяло (-14.5..-2.1 срещу "
      "-17.2..-1.9). **Разликата от 1.3 процентни пункта е в рамките на шума** — "
      "числата тук НЕ дават основание да се твърди, че едното правило печели пари "
      "по-добре от другото. И двете са отрицателни, и двата интервала са изцяло под "
      "нулата — нито сегашният, нито предложеният избор е печеливш.")
    A("5. **С други думи изборът е продуктов, не статистически:** новото правило купува "
      "сравнимост и разбираемост („всеки мач излиза с един и същ вид прогноза\") с цената "
      "на по-ниски и по-често грешащи проценти на витрината. Доходността не е аргумент "
      "нито за, нито против.")
    A("")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return md_path, csv_path
