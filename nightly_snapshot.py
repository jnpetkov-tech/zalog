"""
nightly_snapshot.py

Нощен snapshot job (Фаза D1 от архитектурния план, claude/architecture_roadmap_2026-08-10.md)
- гарантира, че predictions_log покрива ВСИЧКИ 15 активни лиги, не само
тези, реално разгледани през /daily (потвърдено 2026-08-10: England/
Germany/France/Italy/Italy2 нямаха НИТО ЕДИН логнат запис).

Преизползва _predict_matches_for_league() от match_predictor_app.py,
което вече логва вътрешно през system_tracker.log_all_markets() ->
log_prediction() - идемпотентно благодарение на UNIQUE индекса
(fixture_id, market_code) + INSERT OR IGNORE (фиксирано 2026-08-10,
виж system_tracker.py). Затова е безопасно да се пуска многократно -
вече логнати мачове просто се прескачат.

Пуска се от systemd timer, веднъж дневно.
"""
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, "/home/inkas/sportbg-predictor")

import match_predictor_app as mpa


def main():
    from_date = date.today()
    to_date = date.today() + timedelta(days=mpa.DAYS_AHEAD)
    print(f"nightly_snapshot: {from_date} -> {to_date}, {len(mpa.ALL_LEAGUES)} лиги")

    total_matches = 0
    errors = []
    started = time.time()

    for league in mpa.ALL_LEAGUES:
        try:
            matches, api_error = mpa._predict_matches_for_league(league, from_date, to_date)
            total_matches += len(matches)
            status = f"{league}: {len(matches)} мача"
            if api_error:
                status += f" (API грешка: {api_error})"
                errors.append(f"{league}: {api_error}")
            print(status)
        except Exception as e:
            errors.append(f"{league}: EXCEPTION {type(e).__name__}: {e}")
            print(f"{league}: ИЗКЛЮЧЕНИЕ - {type(e).__name__}: {e}")

    elapsed = time.time() - started
    print(f"---\nОбщо: {total_matches} мача обработени за {elapsed:.1f}s, {len(errors)} грешки")
    if errors:
        print("Грешки:")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
