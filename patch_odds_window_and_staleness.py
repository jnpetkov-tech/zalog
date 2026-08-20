import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old_block = '''def run_refresh_odds_cache():
    from_date = date.today()
    to_date = date.today() + timedelta(days=2)
    updated = 0
    checked = 0
    for key in ALL_LEAGUES.keys():
        try:
            fixtures, _ = fetch_upcoming_fixtures(key, from_date, to_date)
        except Exception:
            continue
        for f in fixtures:
            fixture_id = f["fixture"]["id"]
            checked += 1
            try:
                odds = fetch_fixture_odds(fixture_id)
                if odds and (odds.get("home_win") or odds.get("over25")):
                    st.set_cached_odds(fixture_id, odds)
                    updated += 1
            except Exception:
                pass
    with open("odds_refresh_log.txt", "a", encoding="utf-8") as log_f:
        log_f.write(f"{datetime.now().isoformat()} - проверени {checked}, обновени {updated}\\n")'''

new_block = '''def _odds_needs_refresh(fixture_id, fixture_date_str, now):
    """Фаза J.1 (11.08.2026): преди тази промяна run_refresh_odds_cache()
    питаше API-то наново за ВСЕКИ мач в прозореца на ВСЕКИ run (на 30 мин),
    без значение колко скоро вече е проверен - fetched_at полето
    съществуваше в odds_cache, но не се четеше никъде. Тук се ползва:
    <24ч до началото -> опресни ако кешът е >25мин стар (почти всеки run);
    24ч-3дни -> >3ч стар; 3-7 дни -> >12ч стар. Пести квота при разширения
    прозорец (виж ACTION_PLAN.md Фаза J.1), без да жертва свежест близо до
    началото на мача, когато линията реално мърда."""
    cached = st.get_cached_odds(fixture_id)
    if not cached or not cached.get("fetched_at"):
        return True
    try:
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        age_minutes = (now - fetched_at).total_seconds() / 60
    except (ValueError, TypeError):
        return True
    try:
        kickoff = datetime.fromisoformat(fixture_date_str)
        hours_to_kickoff = (kickoff - datetime.now(kickoff.tzinfo)).total_seconds() / 3600
    except Exception:
        hours_to_kickoff = 0
    if hours_to_kickoff < 24:
        max_age = 25
    elif hours_to_kickoff < 72:
        max_age = 180
    else:
        max_age = 720
    return age_minutes >= max_age


def run_refresh_odds_cache():
    from_date = date.today()
    # Фаза J.1: прозорецът беше today+2, а /daily показва до DAYS_AHEAD=7 -
    # мачове на 3-7 дни напред никога не получаваха коефициент, независимо
    # колко добре работеше самото опресняване (виж ACTION_PLAN.md Фаза J.1).
    to_date = date.today() + timedelta(days=DAYS_AHEAD)
    now = datetime.now()
    updated = 0
    checked = 0
    skipped_fresh = 0
    for key in ALL_LEAGUES.keys():
        try:
            fixtures, _ = fetch_upcoming_fixtures(key, from_date, to_date)
        except Exception:
            continue
        for f in fixtures:
            fixture_id = f["fixture"]["id"]
            if not _odds_needs_refresh(fixture_id, f["fixture"]["date"], now):
                skipped_fresh += 1
                continue
            checked += 1
            try:
                odds = fetch_fixture_odds(fixture_id)
                if odds and (odds.get("home_win") or odds.get("over25")):
                    st.set_cached_odds(fixture_id, odds)
                    updated += 1
            except Exception:
                pass
    with open("odds_refresh_log.txt", "a", encoding="utf-8") as log_f:
        log_f.write(f"{datetime.now().isoformat()} - проверени {checked}, обновени {updated}, "
                     f"пропуснати(пресни) {skipped_fresh}\\n")'''

count = content.count(old_block)
assert count == 1, f"anchor count: {count} (очаквано 1)"
content = content.replace(old_block, new_block, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - run_refresh_odds_cache() вече гледа 7 дни напред (вместо 2) "
      "и не пита API-то за мачове с достатъчно пресен кеширан коефициент "
      "(Фаза J.1)")
