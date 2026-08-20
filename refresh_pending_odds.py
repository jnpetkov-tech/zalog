"""
Фаза F0: целенасочено обновяване на market_odds за вече логнати прогнози
на мачове, чийто начален час е в близките 48 часа - прозорецът, в който
букмейкърите обичайно вече имат котировки. НЕ пипа pick_pct/pick_label -
прогнозата остава каквато е била при първото логване, само коефициентът
се допълва, когато стане наличен. Идемпотентен: UPDATE-ва само редове,
при които market_odds все още е NULL.

Отделен от nightly_snapshot.py умишлено - nightly_snapshot логва НОВИ
мачове (веднъж на мач), а тук периодично проверяваме дали вече логнати
мачове са влезли в 48-часовия прозорец, в който можем да допълним
коефициента им. Работи само с fixture_id-та, които вече съществуват в
predictions_log - не смята нови прогнози, не вика модела, само мери
odds за вече взето решение.
"""
import time
import system_tracker as st
import match_predictor_app as mpa


def main():
    fixtures = st.get_fixtures_needing_odds_refresh(hours_ahead=48)
    print(f"Мачове, нуждаещи се от обновяване на коефициенти: {len(fixtures)}")
    updated_fixtures = 0
    updated_rows = 0
    errors = 0
    for f in fixtures:
        label = f"{f['fixture_id']} ({f['league']} {f['home_team']}-{f['away_team']}, {f['match_date']})"
        try:
            real_odds = mpa.fetch_fixture_odds(f["fixture_id"])
        except Exception as e:
            print(f"  ГРЕШКА при извличане на коефициенти {label}: {e}")
            errors += 1
            continue
        if not real_odds:
            print(f"  все още няма коефициенти: {label}")
            time.sleep(0.3)
            continue
        n = st.update_odds_for_fixture(f["fixture_id"], real_odds)
        if n:
            updated_fixtures += 1
            updated_rows += n
            print(f"  обновени {n} реда: {label}")
        time.sleep(0.3)
    print(f"РЕЗЮМЕ: {updated_rows} реда обновени в {updated_fixtures} мача, {errors} грешки, "
          f"{len(fixtures)} мача проверени общо")


if __name__ == "__main__":
    main()
