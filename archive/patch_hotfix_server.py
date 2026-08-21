# -*- coding: utf-8 -*-
import ast

# ============ ПАТЧ 1: system_tracker.py - нова таблица injuries_cache ============
with open("system_tracker.py", encoding="utf-8") as f:
    st_content = f.read()

old_table = '''    conn.execute("""
        CREATE TABLE IF NOT EXISTS odds_cache (
            fixture_id INTEGER PRIMARY KEY,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            over25_odds REAL,
            under25_odds REAL,
            fetched_at TEXT
        )
    """)
    conn.commit()
    conn.close()'''

new_table = '''    conn.execute("""
        CREATE TABLE IF NOT EXISTS odds_cache (
            fixture_id INTEGER PRIMARY KEY,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            over25_odds REAL,
            under25_odds REAL,
            fetched_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS injuries_cache (
            fixture_id INTEGER PRIMARY KEY,
            home_injuries INTEGER,
            away_injuries INTEGER,
            ok INTEGER,
            fetched_at TEXT
        )
    """)
    conn.commit()
    conn.close()'''

n1 = st_content.count(old_table)
assert n1 == 1, f"anchor 1 (injuries_cache таблица) count: {n1}"
st_content = st_content.replace(old_table, new_table, 1)

old_funcs_end = '''def get_cached_odds(fixture_id):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM odds_cache WHERE fixture_id=?", (fixture_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "home_win": row["home_odds"], "draw": row["draw_odds"], "away_win": row["away_odds"],
        "over25": row["over25_odds"], "under25": row["under25_odds"], "fetched_at": row["fetched_at"],
    }


init_db()'''

new_funcs_end = '''def get_cached_odds(fixture_id):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM odds_cache WHERE fixture_id=?", (fixture_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "home_win": row["home_odds"], "draw": row["draw_odds"], "away_win": row["away_odds"],
        "over25": row["over25_odds"], "under25": row["under25_odds"], "fetched_at": row["fetched_at"],
    }
def set_cached_injuries(fixture_id, home_inj, away_inj, ok):
    # Хотфикс 12.08.2026: /daily?league=all правеше живо API извикване за
    # контузии на ВСЕКИ мач при ВСЯКО зареждане (нула кеш) - с до 8 успоредни
    # лиги наведнъж това пробиваше rate limit-а на API-Football (потвърдено
    # на живо, вж. PROJECT_STATE/ACTION_PLAN_v2 N.3 бележка). Кеш с TTL,
    # по образец на odds_cache.
    conn = get_conn()
    conn.execute("""
        INSERT INTO injuries_cache (fixture_id, home_injuries, away_injuries, ok, fetched_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(fixture_id) DO UPDATE SET
            home_injuries=excluded.home_injuries, away_injuries=excluded.away_injuries,
            ok=excluded.ok, fetched_at=excluded.fetched_at
    """, (fixture_id, home_inj, away_inj, int(ok), datetime.now().isoformat()))
    conn.commit()
    conn.close()
def get_cached_injuries(fixture_id, max_age_hours=6):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM injuries_cache WHERE fixture_id=?", (fixture_id,)).fetchone()
    conn.close()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except (ValueError, TypeError):
        return None
    if datetime.now() - fetched > timedelta(hours=max_age_hours):
        return None
    return row["home_injuries"], row["away_injuries"], bool(row["ok"])


init_db()'''

n2 = st_content.count(old_funcs_end)
assert n2 == 1, f"anchor 2 (нови кеш функции) count: {n2}"
st_content = st_content.replace(old_funcs_end, new_funcs_end, 1)

ast.parse(st_content)

with open("system_tracker.py", "w", encoding="utf-8") as f:
    f.write(st_content)

print("system_tracker.py: OK")

# ============ ПАТЧ 2: match_predictor_app.py - ползвай кеша, махни живите извиквания ============
with open("match_predictor_app.py", encoding="utf-8") as f:
    app_content = f.read()

old_inj = '''        home_inj, away_inj = 0, 0
        inj_note = None
        if has_injuries:
            home_inj, away_inj, ok = fetch_fixture_injuries(fixture_id)
            if ok:
                inj_note = f"Контузии: {to_cyrillic(home, league)} {home_inj}, {to_cyrillic(away, league)} {away_inj}"
            else:
                inj_note = "Няма данни за контузии за този мач (все още)"'''

new_inj = '''        home_inj, away_inj = 0, 0
        inj_note = None
        if has_injuries:
            # Хотфикс 12.08.2026: първо кешът (виж st.get_cached_injuries),
            # само при "студен" или изтекъл кеш се тегли на живо от API-то.
            cached_inj = st.get_cached_injuries(fixture_id)
            if cached_inj is not None:
                home_inj, away_inj, ok = cached_inj
            else:
                home_inj, away_inj, ok = fetch_fixture_injuries(fixture_id)
                st.set_cached_injuries(fixture_id, home_inj, away_inj, ok)
            if ok:
                inj_note = f"Контузии: {to_cyrillic(home, league)} {home_inj}, {to_cyrillic(away, league)} {away_inj}"
            else:
                inj_note = "Няма данни за контузии за този мач (все още)"'''

n3 = app_content.count(old_inj)
assert n3 == 1, f"anchor 3 (контузии блок) count: {n3}"
app_content = app_content.replace(old_inj, new_inj, 1)

old_log = '''        groups_for_log, _ = compute_grouped_markets(league, home, away, home_inj, away_inj)
        if groups_for_log and not st.already_logged(fixture_id):
            real_odds_for_log = fetch_fixture_odds(fixture_id)
            st.log_all_markets(league, fixture_id, match_date, home, away, groups_for_log, real_odds=real_odds_for_log)'''

new_log = '''        groups_for_log, _ = compute_grouped_markets(league, home, away, home_inj, away_inj)
        if groups_for_log and not st.already_logged(fixture_id):
            # Хотфикс 12.08.2026: премахнато живо API извикване тук - точно
            # това причиняваше rate limit/524 при /daily?league=all (до 8
            # успоредни лиги x по едно допълнително API извикване на мач).
            # Ползваме вече изтеглените cached_odds (кеширани по-горе в тази
            # функция); ако липсват - логваме без коефициент. Съществуващата
            # фонова задача refresh_pending_odds.py (get_fixtures_needing_odds_refresh
            # / update_odds_for_fixture) вече е предназначена точно за
            # асинхронно допълване на такива липсващи коефициенти по-късно.
            st.log_all_markets(league, fixture_id, match_date, home, away, groups_for_log, real_odds=cached_odds)'''

n4 = app_content.count(old_log)
assert n4 == 1, f"anchor 4 (лог на коефициенти блок) count: {n4}"
app_content = app_content.replace(old_log, new_log, 1)

ast.parse(app_content)

with open("match_predictor_app.py", "w", encoding="utf-8") as f:
    f.write(app_content)

print("match_predictor_app.py: OK")
print("ВСИЧКИ ПАТЧОВЕ УСПЕШНИ")
