"""
build_trust_derived.py — Партида 4, Стъпка 2 (21.08.2026, ARCHITECTURE.md,
Граница 3: „измерване срещу правило").

Смята реалното измерено доверие по (лига, пазарна група) от реални
settled публикувани прогнози в predictions_log (СЪЩИТЕ, които потребителят
реално е видял - минава през evaluation.published_picks(), не суровия лог -
виж evaluation.py защо суровият лог е безсмислен: 1X2 винаги дава точно
33.3% и т.н., независимо от качеството на модела). Пише резултата в
trust_derived (виж system_tracker.save_trust_derived(), Стъпка 1).

Засега РЪЧЕН скрипт - НЕ е закачен към systemd timer (Стъпка 3) и
prediction_policy.py все още НЕ го чете (Стъпка 4). Пуска се и не променя
никакво поведение на живата страница.

Методология (проста, документирана евристика - НЕ формален тест за
значимост, по образец на вече съществуващите прагове в кода като
MAX_TRUSTWORTHY_EV=0.40):

- MIN_N = 20 съответствия преди да се доверим на извода изобщо. Под това -
  статус "unverified", независимо от числата (недостатъчно данни за да се
  различи сигнал от шум). Комбинации с n_settled=0 изобщо не се записват
  (равносилно на "unverified" за prediction_policy.py в Стъпка 4 - липсващ
  ред = непроверено, същата семантика като NULL).
- baseline_brier = Бернули дисперсия на РЕАЛНО наблюдавания win rate
  (actual_rate * (1 - actual_rate)) - "какво би дал constant guess, познал
  ТОЧНО историческия резултат със задна дата". По-строг от произволно
  число - моделът трябва да бие дори перфектно познание с хиндсайт, не
  просто "по-добър от монетка".
- MARGIN = 0.02 Brier разлика - под това "в рамките на шум" (WEAK), над
  това в полза на модела - PROVEN, над това в полза на baseline - REJECTED.
  Фиксиран праг, не мащабиран по n - осъзнато опростяване (виж K.1
  бележката за реалните шумови величини при n=124-200: 0.0008-0.0035;
  за по-малки n тук шумът е по-голям, но MIN_N=20 вече филтрира най-малките
  извадки, а по-фина статистика би усложнила докстринга без ясна полза при
  сегашния малък общ обем данни - виж CLAUDE_HANDOFF.md Партида 4 за
  реалните числа при първото пускане).

Употреба: python3 build_trust_derived.py [--out validation/<име>.csv]
"""
import argparse
import csv
import sys
from datetime import date

import system_tracker as st
import prediction_policy as policy
import evaluation as ev

MIN_N = 20
MARGIN = 0.02


def compute_bucket(picks):
    """picks: settled публикувани прогнози (вече n=1 на мач) за една
    (лига, пазарна група) комбинация. Връща dict, готов за
    st.save_trust_derived(), или None ако n_settled=0 (нищо за запис)."""
    n = len(picks)
    if n == 0:
        return None
    won = sum(1 for p in picks if p["status"] == "won")
    actual_rate = won / n
    promised_avg = sum((p["pick_pct"] or 0) for p in picks) / n
    model_brier, _ = ev.brier_score(picks)
    baseline_brier = actual_rate * (1 - actual_rate)

    if n < MIN_N:
        status = "unverified"
        reason = f"n={n} - под минимума от {MIN_N} за самостоятелна преценка"
    else:
        diff = baseline_brier - model_brier  # положително = моделът по-добър
        if diff >= MARGIN:
            status = "proven"
            reason = (f"n={n}, Brier {model_brier:.3f} срещу baseline {baseline_brier:.3f} "
                       f"({diff:+.3f}) - бие baseline")
        elif diff <= -MARGIN:
            status = "rejected"
            reason = (f"n={n}, Brier {model_brier:.3f} срещу baseline {baseline_brier:.3f} "
                       f"({diff:+.3f}) - по-зле от baseline")
        else:
            status = "weak"
            reason = (f"n={n}, Brier {model_brier:.3f} срещу baseline {baseline_brier:.3f} "
                       f"({diff:+.3f}) - в рамките на шум")

    return {
        "n_settled": n, "model_brier": model_brier, "baseline_brier": baseline_brier,
        "promised_avg": promised_avg, "actual_pct": actual_rate * 100,
        "status": status, "reason": reason,
    }


def build():
    conn = st.get_conn()
    import sqlite3
    conn.row_factory = sqlite3.Row
    all_rows = [dict(r) for r in conn.execute("SELECT * FROM predictions_log").fetchall()]
    conn.close()

    by_league = {}
    for r in all_rows:
        by_league.setdefault(r["league"], []).append(r)

    out_rows = []
    for league, lg_rows in sorted(by_league.items()):
        picks = ev.published_picks(lg_rows, policy)
        settled = [p for p in picks if p["status"] in ev.SETTLED]
        by_group = {}
        for p in settled:
            grp = policy.market_group(p["market_code"])
            by_group.setdefault(grp, []).append(p)
        for grp, grp_picks in sorted(by_group.items()):
            bucket = compute_bucket(grp_picks)
            if bucket is None:
                continue
            out_rows.append({"league": league, "market_group": grp, **bucket})

    st.save_trust_derived(out_rows)
    return out_rows


def write_csv(rows, path):
    fieldnames = ["league", "market_group", "n_settled", "model_brier", "baseline_brier",
                  "promised_avg", "actual_pct", "status", "reason"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None, help="Път за CSV резултат (по подразбиране: validation/trust_derived_<дата>.csv)")
    args = parser.parse_args()
    out_path = args.out or f"validation/trust_derived_{date.today().strftime('%Y%m%d')}.csv"

    rows = build()
    write_csv(rows, out_path)

    print(f"{'Лига':20s} {'Група':15s} {'n':4s} {'Brier':7s} {'Baseline':9s} {'Обещано':8s} {'Реално':7s} Статус")
    for r in rows:
        print(f"{r['league']:20s} {r['market_group']:15s} {r['n_settled']:4d} "
              f"{r['model_brier']:.3f}   {r['baseline_brier']:.3f}     "
              f"{r['promised_avg']:5.1f}%  {r['actual_pct']:5.1f}%  {r['status']} - {r['reason']}")
    print(f"\nОбщо {len(rows)} (лига, пазар) комбинации с поне 1 settled прогноза, записани в trust_derived.")
    print(f"CSV: {out_path}")
