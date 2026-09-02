"""Диагноза (НЕ прилага промяна): защо 39 от 349-те уредени публикувани
топ-прогнози (виж evaluation.published_picks()+_settled()) нямат
market_odds, макар ROI-то (evaluation.roi()) да ги филтрира с n=310.
Поискано в NOSHT3.md, задача 1. Само четене - не пипа кода/данните.

Резултат committed в odds_gap_diagnosis_20260902.csv (39 реда, детайл по
мач) + odds_gap_diagnosis_20260902.md (обобщение)."""
import csv
import sqlite3
from datetime import datetime

import evaluation
import prediction_policy as policy
import system_tracker as st

# refresh-pending-odds.service/.timer файловете на диска (виж
# `stat -c '%y' /etc/systemd/system/refresh-pending-odds.*`): създадени
# 2026-08-10 20:37/20:38 UTC. journalctl потвърждава първото РЕАЛНО
# изпълнение: 2026-08-11 02:00:22 UTC (следващият 02/08/14/20 UTC слот).
# Преди този момент механизмът просто не е съществувал - никой fixture,
# чийто мач е приключил преди тази времева точка, не е имал ДОРИ ЕДИН
# шанс да получи допълнен коефициент.
MECH_FIRST_RUN = datetime(2026, 8, 11, 2, 0, 0)

# Лиги с документирано по-тънко букмейкърско покритие (виж
# validation/coverage_diagnosis_20260825.md) - дори с достатъчно време,
# някои пазари там системно нямат коефициент.
THIN_LEAGUES = {"conference_league", "europa_league", "portugal", "portugal2",
                 "bulgaria2", "england2", "germany2"}


def classify(p):
    mdt = datetime.fromisoformat(p["match_date"])
    ldt = datetime.fromisoformat(p["logged_at"])
    lead_h = (mdt - ldt).total_seconds() / 3600.0
    pre_mech = mdt < MECH_FIRST_RUN
    if pre_mech:
        bucket = "pre_mechanism"
    elif p["league"] in THIN_LEAGUES or lead_h < 6:
        bucket = "probable_bookmaker_gap"
    else:
        bucket = "time_gap"
    return lead_h, pre_mech, bucket


def main():
    conn = st.get_conn()
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM predictions_log").fetchall()]
    conn.close()

    picks = evaluation.published_picks(rows, policy)
    settled = evaluation._settled(picks)
    missing = [p for p in settled if not p["market_odds"]]

    print(f"Уредени публикувани топ-прогнози: {len(settled)}")
    print(f"От тях без market_odds: {len(missing)}")

    out_rows = []
    for p in missing:
        lead_h, pre_mech, bucket = classify(p)
        out_rows.append({
            "league": p["league"], "fixture_id": p["fixture_id"],
            "market_code": p["market_code"], "match_date": p["match_date"],
            "logged_at": p["logged_at"], "lead_time_hours": round(lead_h, 1),
            "pre_mechanism": pre_mech, "bucket": bucket,
        })

    out_rows.sort(key=lambda r: (r["bucket"], r["league"], r["match_date"]))
    with open("validation/odds_gap_diagnosis_20260902.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    from collections import Counter
    print("\nПо bucket:")
    print(Counter(r["bucket"] for r in out_rows))
    print("\nПо (bucket, лига):")
    print(Counter((r["bucket"], r["league"]) for r in out_rows))


if __name__ == "__main__":
    main()
