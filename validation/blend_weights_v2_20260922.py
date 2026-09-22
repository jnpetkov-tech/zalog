"""
validation/blend_weights_v2_20260922.py - ЧАСТ А на ZADACHA_PAZARI.md:
премерване на BLEND_WEIGHTS върху днешните уредени данни.

НЕ е нов метод. Претърсването (W=0.0..1.0, стъпка 0.1), извън-извадковата
проверка (хронологично разполовяване по match_date, W* от 1-ва половина,
приложено невиждано на 2-ра) и Brier формулата са ВНОСНИ от двата
съществуващи скрипта (blend_weight_sweep.brier_at_weight,
blend_weight_out_of_sample.best_weight/brier_mean) - не са преписани.

Какво е различно: САМО входът (raw_p на всеки ред). brier_vs_market.
build_detail_rows() възстановява чистия модел с предположение, което за
днешните данни вече НЕ важи (виж доклада blend_weights_v2_20260922.md):
  1. приема, че всеки ред след BLEND_CUTOFF е смесен с W=0.5 - а от
     25.08.2026 теглата са по пазар (1.0/0.7/0.7/0.5/0.5);
  2. приема, че всеки ред след BLEND_CUTOFF е смесен ИЗОБЩО - а редовете,
     чийто коефициент е допълнен ПО-КЪСНО (update_odds_for_fixture,
     odds_logged_at много след logged_at), са логнати без коефициент =
     чист модел, pick_pct Е raw_p буквално (проверено: 0 от 316 такива
     фикстури имат home_win pick_pct == пазарната цена, срещу 95 от 95 при
     коефициент в момента на логване - виж check_assumption()).
Тук raw_p се взема само там, където е ТОЧНО известен:
  A) logged_at < BLEND_CUTOFF (преди смесването изобщо) -> raw_p = pick_pct
  B) коефициентът е допълнен по-късно (>15 мин след логването, като се
     отчита, че odds_logged_at е в софийско време, logged_at в UTC)
     -> raw_p = pick_pct (не е смесван)
  C) коефициент в момента на логване, след 25.08 -> обратно смесване с
     РЕАЛНОТО тегло на пазара; home_win (W=1.0) е необратим -> отпада
  D) odds_logged_at NULL и logged_at след BLEND_CUTOFF (колоната
     odds_logged_at не е съществувала преди 01.09) -> не може да се каже
     дали е смесен -> отпада.

Само измерване - не пипа match_predictor_app.py.
Употреба: venv/bin/python3 validation/blend_weights_v2_20260922.py
Пише validation/blend_weights_v2_20260922.csv
"""
import csv
import sys
from datetime import datetime

sys.path.insert(0, ".")
sys.path.insert(0, "validation")
import system_tracker as st
import brier_vs_market as bm
from blend_weight_sweep import WEIGHTS, brier_at_weight
from blend_weight_out_of_sample import best_weight, brier_mean, MIN_HALF_N

CURRENT = {"home_win": 1.0, "draw": 0.7, "away_win": 0.7, "over25": 0.5, "under25": 0.5}
PER_MARKET_FROM = "2026-08-25T16:00"  # commit 8b28d51 (15:50 UTC) + рестарт
SOFIA_OFFSET_MIN = 180


def _parse(ts):
    return datetime.fromisoformat(ts.replace(" ", "T"))


def classify(row):
    la = row.get("logged_at") or ""
    if _parse(la) < _parse(bm.BLEND_CUTOFF):
        return "A_pre_blend"
    ola = row.get("odds_logged_at")
    if not ola:
        return "D_ambiguous"
    delta = (_parse(ola) - _parse(la)).total_seconds() / 60 - SOFIA_OFFSET_MIN
    if delta > 15:
        return "B_odds_later"
    if la < PER_MARKET_FROM:
        return "D_ambiguous"
    return "C_blended_at_log"


def build_clean_detail(rows):
    by_group = {}
    for r in rows:
        code = r.get("market_code")
        if code not in bm.ALL_CODES or r.get("status") not in ("won", "lost") or not r.get("market_odds"):
            continue
        for group, codes in bm.MARKET_GROUPS.items():
            if code in codes:
                by_group.setdefault((r["fixture_id"], group), {})[code] = r
                break
    detail, dropped = [], {}
    for (fixture_id, group), by_code in by_group.items():
        codes = bm.MARKET_GROUPS[group]
        if not all(c in by_code for c in codes):
            continue
        try:
            market_probs = bm.devig([by_code[c]["market_odds"] for c in codes])
        except (ZeroDivisionError, TypeError):
            continue
        for code, market_p in zip(codes, market_probs):
            row = by_code[code]
            if row.get("pick_pct") is None:
                continue
            p = row["pick_pct"] / 100.0
            kind = classify(row)
            if kind in ("A_pre_blend", "B_odds_later"):
                raw_p = p
            elif kind == "C_blended_at_log":
                w = CURRENT[code]
                if w >= 1.0:
                    dropped[(kind, code)] = dropped.get((kind, code), 0) + 1
                    continue
                raw_p = bm._clip01((p - w * market_p) / (1 - w))
            else:
                dropped[(kind, code)] = dropped.get((kind, code), 0) + 1
                continue
            detail.append({"market_code": code, "match_date": row.get("match_date"), "kind": kind,
                           "outcome": 1 if row["status"] == "won" else 0,
                           "raw_p": raw_p, "market_p": market_p})
    return detail, dropped


def check_assumption(rows):
    """Колко фикстури с коефициент ПРИ логване имат home_win pick_pct ==
    пазарната цена (очаквано при W=1.0), срещу тези с коефициент ПО-КЪСНО."""
    by_fx = {}
    for r in rows:
        if r.get("market_code") in ("home_win", "draw", "away_win") and r.get("market_odds") \
                and r.get("odds_logged_at") and (r.get("logged_at") or "") >= PER_MARKET_FROM:
            by_fx.setdefault(r["fixture_id"], {})[r["market_code"]] = r
    out = {}
    for d in by_fx.values():
        if len(d) < 3:
            continue
        m = bm.devig([d[c]["market_odds"] for c in ("home_win", "draw", "away_win")])
        kind = classify(d["home_win"])
        exact = abs(d["home_win"]["pick_pct"] - 100 * m[0]) < 0.06
        out.setdefault(kind, [0, 0])[0 if exact else 1] += 1
    return out


def main():
    rows = st.list_predictions()
    print("Проверка на предположението (home_win pick_pct == пазар?) [равно, различно]:",
          check_assumption(rows))
    detail, dropped = build_clean_detail(rows)
    print("Отпаднали редове (невъзможно точно raw_p):", dropped)
    codes = sorted(set(d["market_code"] for d in detail))
    groups = {c: [d for d in detail if d["market_code"] == c] for c in codes}

    out = []
    print(f"\n{'пазар':<9} {'n':>4} {'сег.W':>6} {'W*пълна':>8} {'n1':>4} {'n2':>4} {'W*1':>4} "
          f"{'B1(сег)':>8} {'B1(W*)':>8} {'B2(сег)':>8} {'B2(W*)':>8} {'B2(W*1)':>8}  извод")
    for c in codes:
        items = groups[c]
        cur = CURRENT[c]
        full_best = min(WEIGHTS, key=lambda w: sum(brier_at_weight(items, w)) / len(items))
        ordered = sorted(items, key=lambda d: d["match_date"] or "")
        mid = len(ordered) // 2
        first, second = ordered[:mid], ordered[mid:]
        w1, _ = best_weight(first)
        b1_cur, b1_new = brier_mean(first, cur), brier_mean(first, full_best)
        b2_cur, b2_new = brier_mean(second, cur), brier_mean(second, full_best)
        b2_w1 = brier_mean(second, w1)
        enough = len(first) >= MIN_HALF_N and len(second) >= MIN_HALF_N
        beats_both = enough and full_best != cur and b1_new < b1_cur and b2_new < b2_cur
        oos_holds = enough and w1 != cur and b2_w1 < b2_cur
        if full_best == cur:
            verdict = "оптимумът = сегашното"
        elif beats_both and oos_holds:
            verdict = "НОВОТО БИЕ на двете половини + извън извадката"
        elif beats_both:
            verdict = "бие на двете половини, но W* от 1-ва пол. не издържа"
        else:
            verdict = "НЕ бие на двете половини"
        print(f"{c:<9} {len(items):>4} {cur:>6.1f} {full_best:>8.1f} {len(first):>4} {len(second):>4} {w1:>4.1f} "
              f"{b1_cur:>8.4f} {b1_new:>8.4f} {b2_cur:>8.4f} {b2_new:>8.4f} {b2_w1:>8.4f}  {verdict}")
        out.append({"market_code": c, "n": len(items), "current_w": cur, "best_w_full": full_best,
                    "n_first": len(first), "n_second": len(second), "best_w_first_half": w1,
                    "brier_first_current": round(b1_cur, 5), "brier_first_best": round(b1_new, 5),
                    "brier_second_current": round(b2_cur, 5), "brier_second_best": round(b2_new, 5),
                    "brier_second_at_w1": round(b2_w1, 5),
                    **{f"brier_full_w{w}": round(sum(brier_at_weight(items, w)) / len(items), 5) for w in WEIGHTS},
                    "beats_current_both_halves": beats_both, "oos_w1_beats_current": oos_holds,
                    "verdict": verdict})
    with open("validation/blend_weights_v2_20260922.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print("\nЗаписано: validation/blend_weights_v2_20260922.csv")


if __name__ == "__main__":
    main()
