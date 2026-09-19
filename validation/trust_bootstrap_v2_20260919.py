"""ZADACHA_CHAMPIONSHIP.md (19.09.2026) — второ, поправено отпушване на
доверието за england2/germany2.

Разлика спрямо провалилия се A3 опит (validation/trust_bootstrap_20260919.py,
описан в validation/trust_bootstrap_20260919.md): тук всеки мач дава ТОЧНО
ЕДНО наблюдение на (лига, пазарна група), не цялото допълващо се множество
изходи. За всеки fixture_id, вътре във всяка група, избираме реда с
най-висок pick_pct — аналог на pick_selection/brier_vs_market подхода, само
без сравнение с пазара. Точно предложението от "Препоръка за следваща
сесия" в trust_bootstrap_20260919.md.

compute_bucket() (build_trust_derived.py) НЕ е пипната/преизмислена — вика
се буквално, със същите MIN_N=20/MARGIN=0.02.

Само четене. Нищо не се пише в trust_derived/TRUST_MATRIX от този скрипт.

Употреба: python3 validation/trust_bootstrap_v2_20260919.py
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import system_tracker as st
import prediction_policy as policy
import evaluation as ev
import build_trust_derived as btd

GROUPS = ["1x2", "ou25", "team_total", "htft"]
TARGET_LEAGUES = ["england2", "germany2"]
CONTROL_LEAGUES = ["england", "spain", "italy"]


def dedupe_one_per_match(rows):
    """rows: settled логнати редове за ЕДНА (лига, група). Връща най-много
    един ред на fixture_id — този с най-висок pick_pct в тази група за
    този мач."""
    best = {}
    for r in rows:
        fid = r["fixture_id"]
        if fid not in best or (r["pick_pct"] or 0) > (best[fid]["pick_pct"] or 0):
            best[fid] = r
    return list(best.values())


def measure_league(league, all_rows):
    rows = [r for r in all_rows if r["league"] == league]
    settled = [r for r in rows if r["status"] in ev.SETTLED]
    by_group = {}
    for r in settled:
        grp = policy.market_group(r["market_code"])
        if grp in GROUPS:
            by_group.setdefault(grp, []).append(r)

    out = {}
    for grp in GROUPS:
        raw_rows = by_group.get(grp, [])
        picks = dedupe_one_per_match(raw_rows)  # n=1 на мач, изисквано от compute_bucket()
        n_raw = len(raw_rows)
        n_matches = len(picks)
        bucket = btd.compute_bucket(picks)  # None ако n_matches == 0
        out[grp] = {"n_raw": n_raw, "n_matches": n_matches, "bucket": bucket}
    return out


def main():
    all_rows = st.list_predictions()

    results = {}
    for league in TARGET_LEAGUES + CONTROL_LEAGUES:
        results[league] = measure_league(league, all_rows)

    return results


if __name__ == "__main__":
    results = main()

    def _fmt(b):
        if b["bucket"] is None:
            return f"n_raw={b['n_raw']:5d}  n_matches={b['n_matches']:4d}  (няма settled)"
        bk = b["bucket"]
        return (f"n_raw={b['n_raw']:5d}  n_matches={b['n_matches']:4d}  "
                f"Brier={bk['model_brier']:.4f}  baseline={bk['baseline_brier']:.4f}  "
                f"обещано={bk['promised_avg']:5.1f}%  познато={bk['actual_pct']:5.1f}%  "
                f"[{bk['status']}]")

    print("=== ЦЕЛЕВИ ЛИГИ ===")
    for league in TARGET_LEAGUES:
        print(f"\n=== {league} ===")
        for grp in GROUPS:
            print(f"  {grp:12s} {_fmt(results[league][grp])}")

    print("\n=== КОНТРОЛНИ ЛИГИ (очакват proven/weak за 1x2 и ou25) ===")
    control_ok = True
    for league in CONTROL_LEAGUES:
        print(f"\n=== {league} ===")
        for grp in GROUPS:
            print(f"  {grp:12s} {_fmt(results[league][grp])}")
            if grp in ("1x2", "ou25"):
                b = results[league][grp]["bucket"]
                status = b["status"] if b else "unverified"
                if status not in ("proven", "weak"):
                    control_ok = False

    print(f"\n=== КОНТРОЛА: {'МИНА' if control_ok else 'ПРОВАЛЕНА'} ===")

    out_path = f"validation/trust_bootstrap_v2_{date.today().strftime('%Y%m%d')}_raw.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"results": results, "control_ok": control_ok}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nСуров резултат: {out_path}")
