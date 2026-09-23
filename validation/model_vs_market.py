"""
validation/model_vs_market.py - ZADACHA_MODEL1.md, ЧАСТ В (23.09.2026).

ВЪПРОС: по-точен ли е нашият ЧИСТ модел от пазара (обезвигованите
коефициенти)? Пуска се наново след всяко бъдещо подобрение на модела -
методът по-долу е ФИКСИРАН. Ако се промени, промени и датата в името на
изходните файлове и опиши промяната тук, за да остане сравнимо.

Употреба:  venv/bin/python3 validation/model_vs_market.py
Пише:      validation/model_vs_market_baseline_<ГГГГММДД>.csv  (всяка клетка)
           validation/model_vs_market_baseline_<ГГГГММДД>.md   (отчет)
           (при повторно пускане след подобрение - по-добре с --tag, напр.
           `--tag after_xyz`, за да не се презапише базовата линия)

=== МЕТОД (фиксиран) ===

1. РЕДОВЕ: всеки ред от predictions_log със status 'won'/'lost' (уредени;
   'no_data'/'pending' не влизат). Изход = 1 ако 'won', иначе 0. Всички
   логнати пазари, не само публикуваните - въпросът е за модела, не за
   избора на прогноза.

2. НАШЕТО ЧИСЛО (чистият модел, преди смесване с пазара), по ред на
   предимство:
   M) колоната model_pct, ако е попълнена (записва се от 23.09.2026, ЧАСТ А)
      -> точно.
   Иначе - възстановяване по validation/blend_weights_v2_20260922.md,
   раздел 3 (функцията classify() е ВНЕСЕНА от blend_weights_v2_20260922.py,
   не преписана):
   - Пазари, които никога не са смесвани с пазара (btts, голове по отбор,
     чиста мрежа, полувреме/край, корнери): pick_pct Е чистият модел.
     (_blend_with_market() пипа само 1X2 и над/под 2.5.)
   - home_win/draw/away_win/over25/under25:
     A) записан преди 23.08.2026 19:43:52 (преди смесване изобщо) -> pick_pct
     B) коефициентът е допълнен по-късно (>15 мин след записа) -> pick_pct
     C) коефициент при записа -> обратно смесване с теглото, действало в
        момента на записа: p_модел = (p - W*пазар)/(1 - W), отрязано в [0,1].
        W=1.0 е необратимо -> отпада. Прозорецът 22.09.2026 00:00 -
        23.09.2026 03:45 UTC е двусмислен за draw/over25/under25 (новите
        тегла 1.0 от 22.09 влизат в самостоятелните процеси веднага, в
        Flask - при рестарт) -> тези отпадат; home_win (1.0 и преди, и
        след) и away_win (0.7 и преди, и след) не са засегнати.
     D) записан след 23.08 19:43, без odds_logged_at (колоната не
        съществуваше до 01.09) или C преди 25.08.2026 16:00 -> отпада.
   - dc_1x/dc_x2/dc_12 се смятат от СМЕСЕНИТЕ 1X2 -> A/B като по-горе,
     C и D отпадат (раздел 3 няма формула за обръщане на сбор).

3. ПАЗАРНОТО ЧИСЛО, по ред на предимство:
   - колоната market_pct, ако е попълнена (от 23.09.2026, ЧАСТ А);
   - иначе същата сметка match_predictor_app._market_info_for_pick()
     (не нова), върху коефициентите (market_odds), записани в
     predictions_log за ВСИЧКИ редове на същия мач. 1X2 - обезвигована
     тройка; двойки с допълващ пазар (над/под 2.5, отбор над/под 1.5,
     btts) - обезвигована двойка; ред без пълна тройка/двойка -> отпада.
   - dc_* и htft:* нямат допълващ пазар -> _market_info_for_pick() дава
     СУРОВ implied (1/коефициент, с надценката вътре). Показват се
     отделно, отбелязани, и НЕ влизат в основната обща равносметка.
   - Ред без пазарно число (няма коефициент - напр. корнери) -> отпада.

4. МЕТРИКИ за всяка клетка (пазарна група от
   prediction_policy.market_group() x лига, после по група, по лига и общо):
   n; Brier наш = средно (p_наш - изход)^2; Brier пазар - същото;
   разлика = Brier наш - Brier пазар (ОТРИЦАТЕЛНА = моделът е по-точен);
   обещано срещу познато за ВСЯКА страна поотделно: на всеки пазар в
   мача (1X2, над/под 2.5, btts, домакин над/под 1.5, гост над/под 1.5,
   двоен шанс, полувреме/край) страната "избира" изхода, който сама смята
   за най-вероятен (само пазари, при които ВСИЧКИ изходи на мача са влезли -
   OUTCOMES_PER_INSTANCE; иначе изборът е между непълен списък); обещано = средната вероятност на избраните изходи,
   познато = колко от тях реално са се случили. Близо = честна
   вероятност; обещано > познато = самоувереност. За групите и общото: 95% интервал на
   разликата с bootstrap ПО МАЧ (изходите на един мач не са независими),
   2000 повторения, seed=42. "моделът по-добър"/"пазарът по-добър" само
   ако интервалът не съдържа 0, иначе "не се различават".
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import date, datetime

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

import system_tracker as st  # noqa: E402
import prediction_policy as policy  # noqa: E402
import match_predictor_app as mpa  # noqa: E402
from blend_weights_v2_20260922 import classify, _parse  # noqa: E402

# Теглата по време (UTC на записа). Преди PER_MARKET_FROM classify() вече
# връща A или D, затова тук е нужен само периодът след 25.08.
WEIGHTS_25_08 = {"home_win": 1.0, "draw": 0.7, "away_win": 0.7, "over25": 0.5, "under25": 0.5}
AMBIG_FROM = datetime(2026, 9, 22, 0, 0)     # ZADACHA_PAZARI.md, ЧАСТ А (commit 813eb4e)
AMBIG_TO = datetime(2026, 9, 23, 3, 45)      # ZADACHA_MODEL1.md, ЧАСТ А - model_pct съществува
AMBIG_CODES = {"draw", "over25", "under25"}  # тези смениха теглото на 22.09
BLENDED = {"home_win", "draw", "away_win", "over25", "under25"}
DERIVED_FROM_BLENDED = {"dc_1x", "dc_x2", "dc_12"}
RAW_IMPLIED_GROUPS = {"double_chance", "htft"}
# брой изходи на един пазар в един мач (по подразбиране 2 - двойка)
OUTCOMES_PER_INSTANCE = {"1x2": 3, "double_chance": 3, "htft": 9}
N_BOOT = 2000
SEED = 42


def model_p(row, market_p):
    """(p_наш 0-1 или None, причина)."""
    if row.get("model_pct") is not None:
        return row["model_pct"] / 100.0, "M_model_pct"
    code = row["market_code"]
    p = row["pick_pct"] / 100.0
    if code not in BLENDED and code not in DERIVED_FROM_BLENDED:
        return p, "never_blended"
    kind = classify(row)
    if kind in ("A_pre_blend", "B_odds_later"):
        return p, kind
    if code in DERIVED_FROM_BLENDED:
        return None, f"drop_dc_{kind}"
    if kind == "D_ambiguous":
        return None, f"drop_{kind}"
    logged = _parse(row["logged_at"])
    if AMBIG_FROM <= logged < AMBIG_TO and code in AMBIG_CODES:
        return None, "drop_C_22_09_window"
    w = WEIGHTS_25_08[code]
    if w >= 1.0:
        return None, "drop_C_weight_1.0"
    return min(1.0, max(0.0, (p - w * market_p) / (1 - w))), kind


def build_rows():
    all_rows = st.list_predictions()
    odds_by_fx = defaultdict(dict)
    for r in all_rows:
        if r.get("market_odds"):
            odds_by_fx[r["fixture_id"]][r["market_code"]] = r["market_odds"]
    detail, counts = [], defaultdict(int)
    for r in all_rows:
        if r.get("status") not in ("won", "lost") or r.get("pick_pct") is None:
            continue
        counts["settled"] += 1
        if r.get("market_pct") is not None:
            mkt = r["market_pct"] / 100.0
        else:
            info = mpa._market_info_for_pick(r["market_code"], odds_by_fx.get(r["fixture_id"]))
            mkt = info[0] if info else None
        if mkt is None:
            counts["drop_no_market"] += 1
            continue
        ours, why = model_p(r, mkt)
        counts[why] += 1
        if ours is None:
            continue
        group = policy.market_group(r["market_code"])
        instance = (r["market_code"].split("_")[0] + "_" + group) if group == "team_total" else group
        detail.append({"fixture_id": r["fixture_id"], "league": r["league"], "group": group,
                       "instance": (r["fixture_id"], instance),
                       "code": r["market_code"], "y": 1 if r["status"] == "won" else 0,
                       "ours": ours, "market": mkt, "raw_implied": group in RAW_IMPLIED_GROUPS})
    return detail, counts


def stats(items, boot=False):
    y = np.array([d["y"] for d in items], float)
    o = np.array([d["ours"] for d in items], float)
    m = np.array([d["market"] for d in items], float)
    bo, bm_ = (o - y) ** 2, (m - y) ** 2
    out = {"n": len(items), "matches": len({d["fixture_id"] for d in items}),
           "brier_ours": bo.mean(), "brier_market": bm_.mean(), "diff": bo.mean() - bm_.mean(),
           "ci_low": None, "ci_high": None, "verdict": ""}
    # обещано срещу познато: избраният (най-вероятен за страната) изход на пазар
    by_inst = defaultdict(list)
    for d in items:
        by_inst[d["instance"]].append(d)
    full = [g for (_fx, inst), g in by_inst.items()
            if len(g) == OUTCOMES_PER_INSTANCE.get(inst, 2)]
    for side in ("ours", "market"):
        picks = [max(g, key=lambda d: d[side]) for g in full]
        out[f"picks_{side}"] = len(picks)
        out[f"promised_{side}"] = float(np.mean([d[side] for d in picks])) if picks else float("nan")
        out[f"hit_{side}"] = float(np.mean([d["y"] for d in picks])) if picks else float("nan")
    if boot:
        # bootstrap по мач: сумите по мач, после преизбор на мачове
        fx = defaultdict(lambda: [0.0, 0])
        for d, a, b in zip(items, bo, bm_):
            fx[d["fixture_id"]][0] += a - b
            fx[d["fixture_id"]][1] += 1
        sums = np.array([v[0] for v in fx.values()])
        cnt = np.array([v[1] for v in fx.values()])
        rng = np.random.default_rng(SEED)
        idx = rng.integers(0, len(sums), size=(N_BOOT, len(sums)))
        diffs = sums[idx].sum(1) / cnt[idx].sum(1)
        lo, hi = np.percentile(diffs, [2.5, 97.5])
        out["ci_low"], out["ci_high"] = lo, hi
        out["verdict"] = ("моделът по-добър" if hi < 0 else
                          "пазарът по-добър" if lo > 0 else "не се различават")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="baseline")
    args = ap.parse_args()
    stamp = date.today().strftime("%Y%m%d")
    base = os.path.join(ROOT, "validation", f"model_vs_market_{args.tag}_{stamp}")

    detail, counts = build_rows()
    main_rows = [d for d in detail if not d["raw_implied"]]
    cells = []

    def add(level, group, league, items, boot):
        if items:
            cells.append({"level": level, "group": group, "league": league, **stats(items, boot)})

    add("overall", "ВСИЧКО (без суров implied)", "всички", main_rows, True)
    add("overall", "ВСИЧКО (с dc/htft)", "всички", detail, True)
    groups = sorted({d["group"] for d in detail})
    leagues = sorted({d["league"] for d in detail})
    for g in groups:
        add("group", g, "всички", [d for d in detail if d["group"] == g], True)
    for lg in leagues:
        add("league", "всички (без суров implied)", lg, [d for d in main_rows if d["league"] == lg], True)
    for g in groups:
        for lg in leagues:
            add("group_league", g, lg, [d for d in detail if d["group"] == g and d["league"] == lg], False)

    fields = ["level", "group", "league", "n", "matches", "brier_ours", "brier_market", "diff",
              "ci_low", "ci_high", "verdict", "picks_ours", "promised_ours", "hit_ours",
              "picks_market", "promised_market", "hit_market"]
    with open(base + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for c in cells:
            w.writerow({k: (round(v, 5) if isinstance(v, float) else v) for k, v in c.items()})

    kept = sum(v for k, v in counts.items() if not k.startswith("drop") and k != "settled")
    dropped = {k: v for k, v in counts.items() if k.startswith("drop")}

    def pct(x):
        return f"{100 * x:.1f}%"

    def fmt(c, ci=True):
        s = (f"| {c['group'] if c['level'] != 'league' else c['league']} | {c['n']} | {c['matches']} | "
             f"{c['brier_ours']:.4f} | {c['brier_market']:.4f} | {c['diff']:+.4f} | ")
        if ci:
            s += (f"[{c['ci_low']:+.4f}, {c['ci_high']:+.4f}] | {c['verdict']} | " if c["ci_low"] is not None
                  else "— | — | ")
        if c["picks_ours"] == 0:
            return s + "— | — |"
        return s + (f"{pct(c['promised_ours'])} → {pct(c['hit_ours'])} | "
                    f"{pct(c['promised_market'])} → {pct(c['hit_market'])} |")

    head = ("| {} | n | мачове | Brier наш | Brier пазар | разлика | 95% интервал | извод | "
            "наш: обещано → познато | пазар: обещано → познато |\n|---|---|---|---|---|---|---|---|---|---|")
    L = [f"# Модел срещу пазар - {args.tag}, {date.today().isoformat()}",
         "",
         "Скрипт: `validation/model_vs_market.py` (методът е описан вътре и е фиксиран). "
         "Разлика = Brier наш − Brier пазар: **отрицателна = моделът е по-точен**. "
         "Brier е средната квадратна грешка на вероятността (по-малко = по-добре). "
         "„Обещано → познато“: на всеки пазар всяка страна избира изхода, който смята за най-вероятен; "
         "обещано = средната ѝ вероятност за него, познато = колко пъти реално се е случил.",
         "",
         "## Колко редове влизат",
         "",
         f"- Уредени редове (won/lost): **{counts['settled']}**",
         f"- Влизат: **{kept}** — от тях с model_pct: {counts.get('M_model_pct', 0)}, "
         f"никога не смесвани пазари: {counts.get('never_blended', 0)}, "
         f"A (преди смесването): {counts.get('A_pre_blend', 0)}, "
         f"B (коефициент допълнен по-късно): {counts.get('B_odds_later', 0)}, "
         f"C (обратно смесване): {counts.get('C_blended_at_log', 0)}",
         f"- Отпадат: **{sum(dropped.values())}** — "
         + ", ".join(f"{k}: {v}" for k, v in sorted(dropped.items())),
         "  (drop_no_market = няма пазарно число, напр. корнери/чиста мрежа или липсва "
         "допълващият коефициент; останалите - невъзстановим чист модел, виж метода т.2)",
         "",
         "## Обща равносметка",
         "",
         head.format("обхват")]
    L += [fmt(c) for c in cells if c["level"] == "overall"]
    ov = cells[0]
    n_worse = sum(1 for c in cells if c["level"] == "league" and c["verdict"] == "пазарът по-добър")
    n_better = sum(1 for c in cells if c["level"] == "league" and c["verdict"] == "моделът по-добър")
    L += ["", f"**Накратко:** общо {ov['verdict']} (разлика {ov['diff']:+.4f}, интервал "
          f"[{ov['ci_low']:+.4f}, {ov['ci_high']:+.4f}]). По лиги: пазарът значимо по-добър в "
          f"{n_worse}, моделът значимо по-добър в {n_better}, останалите не се различават."]
    L += ["", "Двойният шанс и полувреме/край се сравняват със СУРОВ implied "
          "(1/коефициент, без обезвиждане) — пазарът там е леко завишен, затова са извън "
          "основната равносметка. За полувреме/край никога не са логнати и деветте изхода на "
          "мач, затова „обещано → познато“ там е „—“.", "", "## По пазарна група", "", head.format("група")]
    L += [fmt(c) for c in cells if c["level"] == "group"]
    L += ["", "## По лига (без суров implied)", "", head.format("лига")]
    L += [fmt(c) for c in cells if c["level"] == "league"]
    L += ["", "## Група × лига (само n ≥ 30; всички клетки са в CSV-то)", "",
          "| група / лига | n | мачове | Brier наш | Brier пазар | разлика | наш: обещано → познато | "
          "пазар: обещано → познато |\n|---|---|---|---|---|---|---|---|"]
    L += [fmt({**c, "group": f"{c['group']} / {c['league']}"}, ci=False)
          for c in cells if c["level"] == "group_league" and c["n"] >= 30]
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nЗаписано: {base}.csv / .md")


if __name__ == "__main__":
    main()
