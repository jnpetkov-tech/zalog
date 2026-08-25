"""
validation/ev_threshold_backtest.py - Точка 2 от разговора с Дака 24.08.2026
(продължение на POYASNENIE_EV.md / build_pick_card EV фикса):

"Под кой EV предимството не се различава от шума" - измерено с реални уредени
прогнози, не предположено. Точка 1 от същия разговор изрично отхвърли и двата
съществуващи прага (MAX_TRUSTWORTHY_EV=0.40 - едно наблюдение; /value-то MIN_
EDGE=3.0/MAX_EDGE=15.0 - извадка от F1, изрично оценена в кода/документацията
като шум при n=53) - целта тук НЕ е да потвърди някой от двата, а да измери
наново, с кофи + реална ROI + bootstrap значимост (същият метод като
validation/blend_vs_raw_significance_20260824.py - paired bootstrap, за да не
се повтори грешката "точкова оценка от малка извадка = доказателство").

ВАЖНО (виж commit 3d52ef5, "Задача 2+3"): predictions_log.pick_pct вече НЕ е
гарантирано чист модел за пет пазара (home_win/draw/away_win/over25/under25) -
след 2026-08-23 19:43:52 (UTC, момента на commit-а) нови логвания за тези
пазари пишат СМЕСЕНО (модел+пазар) число; логът е append-only, затова по-
старите редове остават чист модел завинаги. Проверено директно тук по
logged_at (не предположено): към 24.08.2026 ВСИЧКИ 430 уредени (won/lost)
реда с коефициент за тези пет пазара са логнати ПРЕДИ момента на commit-а
(basis="raw"). Скриптът маркира basis изрично за всеки ред и го разбива по
кофа, за да не се смесят мълчаливо двете различни величини в бъдеще, когато
и уредени "blended" редове се натрупат.

Не филтрира по prediction_policy.is_proven() (за разлика от /value) - целта
тук е дали самото EV число предсказва нещо, независимо от доверието към
лигата; league eligibility е отделна ос, не се смесва тук.

Употреба: python3 validation/ev_threshold_backtest.py
Пише validation/ev_threshold_backtest_20260825.csv (детайл по ред) и
принтира резюме по кофа с bootstrap 95% CI на ROI.
"""
import csv
import random
import sqlite3

BLEND_CUTOFF = "2026-08-23 19:43:52"
BLENDED_MARKET_CODES = {"home_win", "draw", "away_win", "over25", "under25"}

BUCKET_EDGES = [(0, 2), (2, 5), (5, 10), (10, 20), (20, None)]
BUCKET_ORDER = ["неg (<0%)", "0-2%", "2-5%", "5-10%", "10-20%", "20%+"]

N_BOOT = 5000
SEED = 42


def bucket_for(ev_pct):
    if ev_pct < 0:
        return "неg (<0%)"
    for lo, hi in BUCKET_EDGES:
        if hi is None:
            if ev_pct >= lo:
                return f"{lo}%+"
        elif lo <= ev_pct < hi:
            return f"{lo}-{hi}%"
    return None


def bootstrap_ci(returns, n_boot=N_BOOT, seed=SEED):
    if len(returns) < 5:
        return None
    rng = random.Random(seed)
    n = len(returns)
    means = []
    for _ in range(n_boot):
        sample = [returns[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo_idx = int(0.025 * n_boot)
    hi_idx = int(0.975 * n_boot) - 1
    return means[lo_idx], means[hi_idx]


def main():
    conn = sqlite3.connect("predictions.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT logged_at, league, fixture_id, market_code, pick_pct, market_odds,
               our_fair_odds, status
        FROM predictions_log
        WHERE market_odds IS NOT NULL AND our_fair_odds IS NOT NULL AND our_fair_odds > 0
          AND status IN ('won', 'lost')
    """).fetchall()
    conn.close()

    detail = []
    for r in rows:
        # Същата формула, каквато web/value.py пресмята живо ("edge_pct" в
        # кода му - виж POYASNENIE_EV.md защо реално е EV, не edge).
        ev_pct = (r["market_odds"] / r["our_fair_odds"] - 1) * 100
        basis = "raw"
        if r["market_code"] in BLENDED_MARKET_CODES and r["logged_at"] >= BLEND_CUTOFF:
            basis = "blended"
        outcome = 1 if r["status"] == "won" else 0
        ret = (r["market_odds"] - 1) if outcome else -1.0
        detail.append({
            "logged_at": r["logged_at"], "league": r["league"], "fixture_id": r["fixture_id"],
            "market_code": r["market_code"], "basis": basis,
            "ev_pct": round(ev_pct, 2), "market_odds": r["market_odds"],
            "outcome": outcome, "return": round(ret, 4),
            "bucket": bucket_for(ev_pct),
        })

    if not detail:
        print("Няма уредени редове с коефициент+our_fair_odds за анализ.")
        return

    out_path = "validation/ev_threshold_backtest_20260825.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        w.writeheader()
        w.writerows(detail)

    total_blended = sum(1 for d in detail if d["basis"] == "blended")
    print(f"=== EV кофи срещу реална възвръщаемост ({len(detail)} уредени наблюдения) ===")
    print(f"(basis=blended: {total_blended} от {len(detail)} - виж докстринга защо това число днес е 0 или близо до 0)\n")
    header = f"{'Кофа':<11} {'n':>5} {'суров':>6} {'смесен':>7} {'ср.EV%':>8} {'win%':>7} {'ROI/ед.':>9} {'95% CI (bootstrap)':>22} {'извод':<10}"
    print(header)
    print("-" * len(header))
    for b in BUCKET_ORDER:
        sub = [d for d in detail if d["bucket"] == b]
        if not sub:
            print(f"{b:<11} {'0':>5}  (няма уредени наблюдения в тази кофа)")
            continue
        n = len(sub)
        n_raw = sum(1 for d in sub if d["basis"] == "raw")
        n_blend = n - n_raw
        avg_ev = sum(d["ev_pct"] for d in sub) / n
        win_rate = sum(d["outcome"] for d in sub) / n * 100
        returns = [d["return"] for d in sub]
        roi = sum(returns) / n
        ci = bootstrap_ci(returns)
        if ci is None:
            ci_str = "n<5, без CI"
            verdict = "-"
        else:
            ci_str = f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"
            if ci[0] > 0:
                verdict = "ЗНАЧИМО >0"
            elif ci[1] < 0:
                verdict = "ЗНАЧИМО <0"
            else:
                verdict = "ШУМ"
        print(f"{b:<11} {n:>5} {n_raw:>6} {n_blend:>7} {avg_ev:>7.1f}% {win_rate:>6.1f}% {roi:>+8.3f} {ci_str:>22} {verdict:<10}")

    # Допълнителна таблица - НЕ е поискана изрично като кофи, но мапва точно
    # върху двата съществуващи, конкуриращи се прага (виж POYASNENIE_EV.md/
    # разговора 24.08.2026): /daily-то±match_detail (0% под, 40% таван) срещу
    # /value-то (3% под, 15% таван). Само за прочитане на числата - скриптът
    # не решава и не променя нищо.
    print("\n=== Същите данни, разбити точно по двата съществуващи прага (за прочит, не решение) ===")
    ranges = [("<0% (под и двата)", None, 0), ("0-3% (само /daily приема)", 0, 3),
              ("3-15% (и двата приемат)", 3, 15), ("15-40% (само /daily приема)", 15, 40),
              ("40%+ (нито един не приема)", 40, None)]
    header2 = f"{'Диапазон':<28} {'n':>5} {'ср.EV%':>8} {'win%':>7} {'ROI/ед.':>9} {'95% CI (bootstrap)':>22} {'извод':<10}"
    print(header2)
    print("-" * len(header2))
    for label, lo, hi in ranges:
        sub = [d for d in detail if (lo is None or d["ev_pct"] >= lo) and (hi is None or d["ev_pct"] < hi)]
        if not sub:
            print(f"{label:<28} {'0':>5}  (няма наблюдения)")
            continue
        n = len(sub)
        avg_ev = sum(d["ev_pct"] for d in sub) / n
        win_rate = sum(d["outcome"] for d in sub) / n * 100
        returns = [d["return"] for d in sub]
        roi = sum(returns) / n
        ci = bootstrap_ci(returns)
        if ci is None:
            ci_str, verdict = "n<5, без CI", "-"
        else:
            ci_str = f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"
            verdict = "ЗНАЧИМО >0" if ci[0] > 0 else ("ЗНАЧИМО <0" if ci[1] < 0 else "ШУМ")
        print(f"{label:<28} {n:>5} {avg_ev:>7.1f}% {win_rate:>6.1f}% {roi:>+8.3f} {ci_str:>22} {verdict:<10}")

    print(f"\nЗаписано: {out_path} ({len(detail)} реда)")


if __name__ == "__main__":
    main()
