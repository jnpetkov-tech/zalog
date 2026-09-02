import json
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DB_PATH = "predictions.db"

# Поправка 01.09.2026 (диагноза от validation/odds_refresh_timezone_
# diagnosis_20260901.md): match_date навсякъде в predictions_log/
# predictions_snapshot е Sofia МЕСТНО време (низ, без явен offset - идва от
# fetch_upcoming_fixtures(timezone="Europe/Sofia"), offset-ът се отрязва
# при запис). Серверният системен часовник е UTC (потвърдено с journalctl,
# gunicorn показва "+0000") - наивно datetime.now() тук би било грешно
# сравнение с 2-3 часа разлика според DST. Същият подход като
# web/prognozi.py::_now_sofia_str() (не импортирано оттам - system_tracker.py
# е долен слой, web/ зависи от него, не обратното - локално дублиран малък
# helper, не кръгов импорт).
SOFIA_TZ = ZoneInfo("Europe/Sofia")


def _now_sofia_naive():
    """Текущото Sofia време, като наивен datetime (без tzinfo) - директно
    сравнимо с match_date низовете "YYYY-MM-DD HH:MM", които също са Sofia
    местно време без offset."""
    return datetime.now(SOFIA_TZ).replace(tzinfo=None)


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at TEXT,
            league TEXT,
            fixture_id INTEGER,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            market_code TEXT,
            pick_label TEXT,
            pick_pct REAL,
            status TEXT DEFAULT 'pending',
            actual_home_goals INTEGER,
            actual_away_goals INTEGER,
            market_odds REAL,
            our_fair_odds REAL
        )
    """)
    for col_def in ["market_odds REAL", "our_fair_odds REAL", "odds_logged_at TEXT"]:
        try:
            conn.execute(f"ALTER TABLE predictions_log ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass
    conn.execute("""
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_notes (
            fixture_id INTEGER PRIMARY KEY,
            note TEXT,
            skip INTEGER DEFAULT 0,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS form_standings_cache (
            fixture_id INTEGER PRIMARY KEY,
            data TEXT,
            fetched_at TEXT
        )
    """)
    # 22.08.2026: списъкът с предстоящи мачове за (лига, период) се теглеше
    # поотделно от три различни 30-минутни фонови задачи (опресняване на
    # коефициенти, опресняване на контузии, предизчисляване на прогнозите)
    # за едни и същи 17 лиги - тройно едно и също запитване към API-Football
    # на всеки цикъл. Кратък TTL кеш тук, ползван само от фоновите задачи
    # (виж use_cache в api_football.fetch_upcoming_fixtures) - НЕ и от
    # страниците, които потребителят реално гледа (/daily, /live), за да не
    # закъснява живия статус/резултат там.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fixture_list_cache (
            league TEXT,
            from_date TEXT,
            to_date TEXT,
            fetched_at TEXT,
            data TEXT,
            PRIMARY KEY (league, from_date, to_date)
        )
    """)
    # Партида 3, Стъпка 1 (21.08.2026, ARCHITECTURE.md, Граница 2): празна
    # засега таблица. ЦЕЛ (следващи стъпки, поетапно): фонова задача по
    # график смята прогнозите за 7 дни напред за всички лиги и пълни тази
    # таблица; /daily накрая чете от нея вместо да смята "на момента" при
    # всяка заявка (сегашната причина за бавния студен старт и TTL кеша от
    # И.3). За разлика от predictions_log (постоянен, append-only исторически
    # запис за оценка на точността), тази таблица е "снимка" на ТЕКУЩОТО
    # състояние - UNIQUE(fixture_id, market_code) + INSERT OR REPLACE
    # презаписва реда при всяко ново пресмятане, не трупа история.
    # model_version пази какъв код/конфигурация е дала резултата - позволява
    # честно сравнение преди/след бъдеща промяна в модела, от реални данни.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fixture_id INTEGER NOT NULL,
            league TEXT NOT NULL,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            market_code TEXT NOT NULL,
            pick_label TEXT,
            pick_pct REAL,
            fair_odds REAL,
            ev REAL,
            computed_at TEXT NOT NULL,
            model_version TEXT,
            UNIQUE(fixture_id, market_code)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_predictions_snapshot_league_date
        ON predictions_snapshot(league, match_date)
    """)
    # Партида 4, Стъпка 1 (21.08.2026, ARCHITECTURE.md, Граница 3: „измерване
    # срещу правило"). Едно място за реалното измерено доверие в
    # (лига, пазарна група) - за разлика от TRUST_MATRIX в prediction_policy.py
    # (ръчно писана, веднъж), тук се пише автоматично, нощно, от реални
    # settled публикувани прогнози (виж build_trust_derived.py). market_group
    # използва СЪЩАТА група като policy.market_group() (1x2/ou25/team_total/
    # htft/double_chance/btts/corners/cards/offsides/other), не суровия
    # market_code - иначе таблицата би имала 150+ реда, никой не би я четял
    # смислено с малкия обем settled данни, който реално имаме сега.
    # UNIQUE(league, market_group) - INSERT OR REPLACE презаписва при всяко
    # ново нощно смятане, не трупа история (различно от predictions_log).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trust_derived (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT NOT NULL,
            market_group TEXT NOT NULL,
            n_settled INTEGER NOT NULL,
            model_brier REAL,
            baseline_brier REAL,
            promised_avg REAL,
            actual_pct REAL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            computed_at TEXT NOT NULL,
            UNIQUE(league, market_group)
        )
    """)
    # Партида 1, т.1.2 (01.09.2026): fetch_lineups_available() не се кешираше
    # никъде - всеки мач до 60 мин преди начало питаше API-то на ВСЯКО
    # зареждане на /daily, докато не потвърдеше състав. По образец на
    # injuries_cache: True се пази трайно (веднъж потвърден състав не се
    # разпотвърждава), False има кратък TTL (виж get_cached_lineups_available).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lineups_cache (
            fixture_id INTEGER PRIMARY KEY,
            available INTEGER,
            fetched_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def set_cached_form_standings(fixture_id, data):
    # Фаза P.1 (21.08.2026): последни 5 мача + класиране на /match_detail -
    # 3 допълнителни API извиквания (2x /fixtures last5 + 1x /standings) на
    # некеширан преглед, по образец на injuries_cache (виж N.3) - кешираме
    # дори частичен резултат (напр. standings=None за чист knockout турнир),
    # за да не удряме API-то при всяко презареждане на страницата.
    conn = get_conn()
    conn.execute("""
        INSERT INTO form_standings_cache (fixture_id, data, fetched_at)
        VALUES (?,?,?)
        ON CONFLICT(fixture_id) DO UPDATE SET
            data=excluded.data, fetched_at=excluded.fetched_at
    """, (fixture_id, json.dumps(data), datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_cached_form_standings(fixture_id, max_age_hours=12):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM form_standings_cache WHERE fixture_id=?", (fixture_id,)).fetchone()
    conn.close()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except (ValueError, TypeError):
        return None
    if datetime.now() - fetched > timedelta(hours=max_age_hours):
        return None
    try:
        return json.loads(row["data"])
    except (ValueError, TypeError):
        return None


def set_match_note(fixture_id, note, skip):
    """Фаза N.4, етап 1 (20.08.2026): ръчна бележка/контекст на Дака за
    конкретен мач + флаг "пропусни" (виж CLAUDE_HANDOFF.md - категорична
    забрана: НИКОГА не коригира pick_pct/prediction, чисто информативно +
    изключва мача от препоръчания списък на /daily)."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO match_notes (fixture_id, note, skip, updated_at)
        VALUES (?,?,?,?)
        ON CONFLICT(fixture_id) DO UPDATE SET
            note=excluded.note, skip=excluded.skip, updated_at=excluded.updated_at
    """, (fixture_id, note, int(bool(skip)), datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_match_note(fixture_id):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM match_notes WHERE fixture_id=?", (fixture_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {"note": row["note"], "skip": bool(row["skip"])}


def get_all_match_notes():
    """Едно зареждане на всички бележки наведнъж - за /daily, където се
    проверяват много fixture_id-та наведнъж (избягва N отделни заявки)."""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM match_notes").fetchall()
    conn.close()
    return {r["fixture_id"]: {"note": r["note"], "skip": bool(r["skip"])} for r in rows}


def log_prediction(league, fixture_id, match_date, home, away, market_code, pick_label, pick_pct,
                    market_odds=None, our_fair_odds=None):
    # 2026-08-10: INSERT OR IGNORE вместо SELECT-then-INSERT - старият модел
    # имаше TOCTOU race при паралелни заявки (два thread-а минават SELECT
    # проверката преди първият да успее да INSERT-не), причинил реален
    # дубликат на живо (fixture_id=1551072, dc_1x). Сега, с UNIQUE индекс
    # idx_predictions_fixture_market, race-ът е безопасен - вторият опит
    # просто се игнорира на ниво SQLite, атомарно.
    # Задача 01.09.2026, т.1.3: odds_logged_at - КОГА е записан market_odds,
    # за да може занапред да се провери дали коефициентът е дошъл преди или
    # след началото на мача. Само ако market_odds вече е наличен ТОЧНО СЕГА
    # (рядко при първо логване - обичайно се допълва по-късно през
    # update_odds_for_fixture()) - иначе NULL, честно "още нямаме
    # коефициент", не грешна времева марка. Sofia местно време (_now_sofia_
    # naive()), НЕ UTC като logged_at - нарочно, за да е директно сравнимо с
    # match_date (също Sofia местно), без допълнително преобразуване по-късно.
    odds_logged_at = _now_sofia_naive().isoformat() if market_odds is not None else None
    conn = get_conn()
    cur = conn.execute(
        """INSERT OR IGNORE INTO predictions_log (logged_at, league, fixture_id, match_date, home_team, away_team,
           market_code, pick_label, pick_pct, market_odds, our_fair_odds, odds_logged_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(), league, fixture_id, match_date, home, away,
         market_code, pick_label, pick_pct, market_odds, our_fair_odds, odds_logged_at)
    )
    conn.commit()
    if cur.rowcount == 0:
        existing = conn.execute(
            "SELECT id FROM predictions_log WHERE fixture_id=? AND market_code=?",
            (fixture_id, market_code)
        ).fetchone()
        conn.close()
        return existing[0] if existing else None
    log_id = cur.lastrowid
    conn.close()
    return log_id


MARKET_ODDS_MAP = {
    "home_win": "home_win", "draw": "draw", "away_win": "away_win",
    "over25": "over25", "under25": "under25",
    "home_over15": "home_over15", "home_under15": "home_under15",
    "away_over15": "away_over15", "away_under15": "away_under15",
    "dc_1x": "dc_1x", "dc_x2": "dc_x2", "dc_12": "dc_12",
    # 25.08.2026: BTTS вече сравним - fetch_fixture_odds() парсва "Both Teams
    # Score" (виж api_football.py). Само за записване на market_odds/бъдещо
    # измерване (validation/vs_market_brier.py и подобни) - НЕ е включен в
    # _blend_with_market()/BLEND_WEIGHTS, живата прогноза остава чист модел.
    "btts_yes": "btts_yes", "btts_no": "btts_no",
}
for _a in ("1", "X", "2"):
    for _b in ("1", "X", "2"):
        MARKET_ODDS_MAP[f"htft:{_a}/{_b}"] = f"htft:{_a}/{_b}"


def already_logged(fixture_id):
    conn = get_conn()
    existing = conn.execute("SELECT id FROM predictions_log WHERE fixture_id=? LIMIT 1", (fixture_id,)).fetchone()
    conn.close()
    return existing is not None


def save_snapshot_predictions(rows):
    """Партида 3, Стъпка 2 (21.08.2026, ARCHITECTURE.md): UPSERT в
    predictions_snapshot по (fixture_id, market_code) - за разлика от
    log_prediction() (predictions_log, append-once история), тук всяко
    ново пресмятане ПРЕЗАПИСВА реда - таблицата пази текущото състояние,
    не история. rows: списък dict-и с fixture_id, league, match_date,
    home_team, away_team, market_code, pick_label, pick_pct, fair_odds,
    ev (може None), model_version."""
    if not rows:
        return
    conn = get_conn()
    now = datetime.now().isoformat()
    conn.executemany("""
        INSERT INTO predictions_snapshot
            (fixture_id, league, match_date, home_team, away_team, market_code,
             pick_label, pick_pct, fair_odds, ev, computed_at, model_version)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(fixture_id, market_code) DO UPDATE SET
            league=excluded.league, match_date=excluded.match_date,
            home_team=excluded.home_team, away_team=excluded.away_team,
            pick_label=excluded.pick_label, pick_pct=excluded.pick_pct,
            fair_odds=excluded.fair_odds, ev=excluded.ev,
            computed_at=excluded.computed_at, model_version=excluded.model_version
    """, [(r["fixture_id"], r["league"], r["match_date"], r["home_team"], r["away_team"],
           r["market_code"], r["pick_label"], r["pick_pct"], r["fair_odds"], r.get("ev"),
           now, r.get("model_version")) for r in rows])
    conn.commit()
    conn.close()


def clear_stale_snapshot(before_date):
    """Изтрива редове с match_date преди before_date (ISO YYYY-MM-DD) -
    държи predictions_snapshot ограничена до текущия 7-дневен прозорец,
    вместо да трупа мачове, изпаднали от него, безкрайно."""
    conn = get_conn()
    conn.execute("DELETE FROM predictions_snapshot WHERE match_date < ?", (before_date,))
    conn.commit()
    conn.close()


def get_snapshot_picks_for_fixtures(fixture_ids):
    """Партида 3, Стъпка 4: чете предварително пресметнатите picks за
    списък fixture_id-та наведнъж (ИЗБЯГВА N отделни заявки за N мача на
    страница - по образец на get_all_match_notes()). Връща
    {fixture_id: [ред, ред, ...]}, всеки списък сортиран по pick_pct
    низходящо (rank_candidates() вече е избрал/подредил picks-а при
    смятането - тук просто пазим същата подредба)."""
    if not fixture_ids:
        return {}
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in fixture_ids)
    rows = conn.execute(f"""
        SELECT fixture_id, market_code, pick_label, pick_pct, fair_odds, ev, computed_at, model_version
        FROM predictions_snapshot
        WHERE fixture_id IN ({placeholders})
        ORDER BY fixture_id, pick_pct DESC
    """, fixture_ids).fetchall()
    conn.close()
    result = {}
    for r in rows:
        result.setdefault(r["fixture_id"], []).append(dict(r))
    return result


def get_snapshot_rows_for_date_range(from_date, to_date):
    """Партида 2 (01.09.2026, /prognozi): всички редове от
    predictions_snapshot с match_date в диапазона [from_date, to_date]
    (ISO YYYY-MM-DD, включително двата края) - за публичната страница,
    която НЕ прави никаква заявка към API-Football (задачата, т.2.10) -
    четем директно снимката, никога fetch_upcoming_fixtures(). Връща
    суров списък редове (dict-ове), викащият групира по fixture_id (по
    образец на get_snapshot_picks_for_fixtures, само за диапазон дати
    вместо конкретни fixture_id-та - тук нямаме предварителен списък
    мачове от API, за да го подадем)."""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT fixture_id, league, match_date, home_team, away_team, market_code,
               pick_label, pick_pct, fair_odds, ev, computed_at, model_version
        FROM predictions_snapshot
        WHERE substr(match_date,1,10) BETWEEN ? AND ?
        ORDER BY match_date, fixture_id, pick_pct DESC
    """, (from_date, to_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_snapshot_rows_for_fixture(fixture_id):
    """Публична страница на мача (01.09.2026, задача от Дака): всички
    редове от predictions_snapshot за ЕДИН fixture_id, с всички колони,
    нужни за показване (league/match_date/home_team/away_team - за разлика
    от get_snapshot_picks_for_fixtures(), която пази само pick полетата,
    без мач-контекста). Не е ключирано по дата - самата
    predictions_snapshot вече пази само текущия прозорец (днес..+7 дни),
    затова fixture_id е достатъчен, без диапазон дати."""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT fixture_id, league, match_date, home_team, away_team, market_code,
               pick_label, pick_pct, fair_odds, ev, computed_at, model_version
        FROM predictions_snapshot
        WHERE fixture_id = ?
        ORDER BY pick_pct DESC
    """, (fixture_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_snapshot_freshness():
    """Партида 3, довършване (21.08.2026): най-новият computed_at в цялата
    predictions_snapshot таблица - ISO низ, или None ако таблицата е
    празна (build_predictions_snapshot.py никога не е пускан успешно).
    Използва се от /daily, за да предупреди Дака ако фоновата задача
    (build-predictions-snapshot.timer, на 30 мин) е спряла да презаписва -
    иначе страницата би сервирала стари данни мълчаливо."""
    conn = get_conn()
    row = conn.execute("SELECT MAX(computed_at) FROM predictions_snapshot").fetchone()
    conn.close()
    return row[0] if row else None


def save_trust_derived(rows):
    """Партида 4, Стъпка 1 (21.08.2026): UPSERT в trust_derived по
    (league, market_group) - по образец на save_snapshot_predictions().
    rows: списък dict-и с league, market_group, n_settled, model_brier,
    baseline_brier (може None и двете, ако n_settled=0), promised_avg,
    actual_pct (може None), status, reason."""
    if not rows:
        return
    conn = get_conn()
    now = datetime.now().isoformat()
    conn.executemany("""
        INSERT INTO trust_derived
            (league, market_group, n_settled, model_brier, baseline_brier,
             promised_avg, actual_pct, status, reason, computed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(league, market_group) DO UPDATE SET
            n_settled=excluded.n_settled, model_brier=excluded.model_brier,
            baseline_brier=excluded.baseline_brier, promised_avg=excluded.promised_avg,
            actual_pct=excluded.actual_pct, status=excluded.status,
            reason=excluded.reason, computed_at=excluded.computed_at
    """, [(r["league"], r["market_group"], r["n_settled"], r.get("model_brier"),
           r.get("baseline_brier"), r.get("promised_avg"), r.get("actual_pct"),
           r["status"], r["reason"], now) for r in rows])
    conn.commit()
    conn.close()


def get_all_trust_derived():
    """Всички редове от trust_derived, ключувани по (league, market_group) -
    за prediction_policy.py (Стъпка 4, все още не wire-нато) и за ръчна
    инспекция на резултата от build_trust_derived.py."""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM trust_derived").fetchall()
    conn.close()
    return {(r["league"], r["market_group"]): dict(r) for r in rows}


def get_fixtures_needing_odds_refresh(hours_ahead=48):
    """НОВО (Фаза F0): намира fixture_id-та, логнати преди коефициентите
    да са били налични (market_odds IS NULL), чийто начален час е в
    близките hours_ahead часа - прозорецът, в който букмейкърите обичайно
    вече имат котировки. Използва се от refresh_pending_odds.py, НЕ от
    nightly_snapshot.py - целенасочено, за да не умножава API заявките за
    целия 7-дневен прозорец всяка нощ.

    Поправка 01.09.2026: `now` вече е РЕАЛНО Sofia време (_now_sofia_naive()),
    не наивно сървърно UTC - преди тази поправка мач, започнал до 2-3 часа
    (според DST) преди истинския момент, все още изглеждаше "в бъдещето" на
    сравнението и оставаше в списъка за опресняване - риск да се запише
    коефициент от вече течащ мач като предматчов. Виж
    validation/odds_timezone_fix_20260901.md за измерването."""
    now = _now_sofia_naive()
    cutoff = (now + timedelta(hours=hours_ahead)).strftime("%Y-%m-%d %H:%M")
    now_str = now.strftime("%Y-%m-%d %H:%M")
    # ВАЖНО: филтрираме само по пазари, за които изобщо теглим коефициент
    # (MARKET_ODDS_MAP). Иначе corners/cards/offsides/btts редовете (чийто
    # market_odds е NULL завинаги, по дизайн - REJECTED tier) биха държали
    # fixture-а в списъка безкрайно, дори след като всичко проследимо вече
    # е обновено.
    trackable = list(MARKET_ODDS_MAP.keys())
    placeholders = ",".join("?" for _ in trackable)
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"""
        SELECT DISTINCT fixture_id, league, match_date, home_team, away_team
        FROM predictions_log
        WHERE market_odds IS NULL
          AND market_code IN ({placeholders})
          AND match_date >= ?
          AND match_date <= ?
        ORDER BY match_date ASC
    """, (*trackable, now_str, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
def update_odds_for_fixture(fixture_id, real_odds):
    """НОВО (Фаза F0): обновява market_odds за вече логнати редове на
    fixture_id, при които все още е NULL. НИКОГА не презаписва
    съществуваща стойност и НИКОГА не пипа pick_pct/pick_label -
    прогнозата остава заключена към момента на първото логване, само
    коефициентът се допълва, когато стане наличен."""
    if not real_odds:
        return 0
    # т.1.3 (01.09.2026): odds_logged_at - Sofia местно време, момента на
    # ТОВА обновяване (не когато мачът реално е започнал) - позволява
    # занапред да се провери "записан ли е коефициентът преди или след
    # началото на мача" (match_date, също Sofia местно).
    odds_logged_at = _now_sofia_naive().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    updated = 0
    rows = conn.execute(
        "SELECT id, market_code FROM predictions_log WHERE fixture_id=? AND market_odds IS NULL",
        (fixture_id,)
    ).fetchall()
    for row_id, market_code in rows:
        odds_key = MARKET_ODDS_MAP.get(market_code)
        odds_val = real_odds.get(odds_key) if odds_key else None
        if odds_val is None:
            continue
        cur.execute(
            "UPDATE predictions_log SET market_odds=?, odds_logged_at=? WHERE id=? AND market_odds IS NULL",
            (odds_val, odds_logged_at, row_id)
        )
        updated += cur.rowcount
    conn.commit()
    conn.close()
    return updated


def log_all_markets(league, fixture_id, match_date, home, away, groups, real_odds=None):
    count = 0
    for title, items, has_form in groups:
        for row in items:
            if len(row) > 3 and row[3]:
                market_code = row[3]
                pick_pct = row[1]
                fair = round(100 / pick_pct, 2) if pick_pct > 0 else None
                odds_key = MARKET_ODDS_MAP.get(market_code)
                market_odds = real_odds.get(odds_key) if (real_odds and odds_key) else None
                log_prediction(league, fixture_id, match_date, home, away, market_code, row[0], pick_pct,
                                market_odds=market_odds, our_fair_odds=fair)
                count += 1
    return count


def list_predictions():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM predictions_log ORDER BY match_date DESC, id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_predictions_for_fixture(fixture_id):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM predictions_log WHERE fixture_id=? ORDER BY pick_pct DESC",
                         (fixture_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


STALE_DAYS_CUTOFF = 3


def check_results(api_key, base_url, requests_module):
    import sys
    sys.path.insert(0, '.')
    import bets_tracker as bt

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    pending = conn.execute("SELECT * FROM predictions_log WHERE status='pending'").fetchall()
    updated = 0
    no_data = 0
    fixture_cache = {}
    now = datetime.now()

    for row in pending:
        fixture_id = row["fixture_id"]
        market_code = row["market_code"]

        def mark_stale_if_old():
            nonlocal no_data
            try:
                match_dt = datetime.fromisoformat(row["match_date"])
            except (ValueError, TypeError):
                return
            if (now - match_dt).days >= STALE_DAYS_CUTOFF:
                conn.execute("UPDATE predictions_log SET status='no_data' WHERE id=?", (row["id"],))
                no_data += 1

        if fixture_id not in fixture_cache:
            r = requests_module.get(f"{base_url}/fixtures", headers={"x-apisports-key": api_key},
                                     params={"id": fixture_id})
            data = r.json()
            fixture_cache[fixture_id] = data.get("response", [])

        response = fixture_cache[fixture_id]
        if not response:
            mark_stale_if_old()
            continue
        fixture = response[0]
        if fixture["fixture"]["status"]["short"] != "FT":
            mark_stale_if_old()
            continue

        hg = fixture["goals"]["home"]
        ag = fixture["goals"]["away"]
        ht = fixture.get("score", {}).get("halftime", {})
        ht_hg, ht_ag = ht.get("home"), ht.get("away")

        if market_code.startswith(("corners_", "cards_", "offsides_")):
            stats = bt.fetch_fixture_stats(api_key, base_url, requests_module, fixture_id,
                                             row["home_team"], row["away_team"])
            result = bt.evaluate_stat_market(market_code, stats)
        else:
            result = bt.evaluate_market_v2(market_code, hg, ag, ht_hg, ht_ag)

        if result is None:
            mark_stale_if_old()
            continue

        new_status = "won" if result else "lost"
        conn.execute(
            "UPDATE predictions_log SET status=?, actual_home_goals=?, actual_away_goals=? WHERE id=?",
            (new_status, hg, ag, row["id"]),
        )
        updated += 1

    conn.commit()
    conn.close()
    return updated


def get_stats_by_market():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT market_code,
               SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) as won,
               SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) as lost,
               SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending
        FROM predictions_log
        GROUP BY market_code
        ORDER BY (won + lost) DESC
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        total = r["won"] + r["lost"]
        win_rate = (r["won"] / total * 100) if total > 0 else None
        result.append({"market_code": r["market_code"], "won": r["won"], "lost": r["lost"],
                        "pending": r["pending"], "win_rate": win_rate})
    return result


def get_stats_by_league():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT league,
               SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) as won,
               SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) as lost,
               SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending
        FROM predictions_log
        GROUP BY league
        ORDER BY (won + lost) DESC
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        total = r["won"] + r["lost"]
        win_rate = (r["won"] / total * 100) if total > 0 else None
        result.append({"league": r["league"], "won": r["won"], "lost": r["lost"],
                        "pending": r["pending"], "win_rate": win_rate})
    return result


def set_cached_odds(fixture_id, odds_dict):
    """odds_dict: {'home_win':.., 'draw':.., 'away_win':.., 'over25':.., 'under25':..} (decimal odds, могат да липсват)."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO odds_cache (fixture_id, home_odds, draw_odds, away_odds, over25_odds, under25_odds, fetched_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(fixture_id) DO UPDATE SET
            home_odds=excluded.home_odds, draw_odds=excluded.draw_odds, away_odds=excluded.away_odds,
            over25_odds=excluded.over25_odds, under25_odds=excluded.under25_odds, fetched_at=excluded.fetched_at
    """, (fixture_id, odds_dict.get("home_win"), odds_dict.get("draw"), odds_dict.get("away_win"),
          odds_dict.get("over25"), odds_dict.get("under25"), datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_cached_odds(fixture_id):
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


def get_cached_fixture_list(league, from_date, to_date, max_age_minutes=20):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM fixture_list_cache WHERE league=? AND from_date=? AND to_date=?",
        (league, from_date, to_date)
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except (ValueError, TypeError):
        return None
    if datetime.now() - fetched > timedelta(minutes=max_age_minutes):
        return None
    return json.loads(row["data"])


def set_cached_fixture_list(league, from_date, to_date, fixtures):
    conn = get_conn()
    conn.execute("""
        INSERT INTO fixture_list_cache (league, from_date, to_date, fetched_at, data)
        VALUES (?,?,?,?,?)
        ON CONFLICT(league, from_date, to_date) DO UPDATE SET
            fetched_at=excluded.fetched_at, data=excluded.data
    """, (league, from_date, to_date, datetime.now().isoformat(), json.dumps(fixtures)))
    conn.commit()
    conn.close()


def get_cached_lineups_available(fixture_id, max_age_minutes_false=10):
    """Партида 1, т.1.2 (01.09.2026). Връща True/False, ако кешът е валиден,
    None ако трябва да се пита API-то. True се пази без изтичане - веднъж
    потвърден състав не изчезва обратно. False изтича след
    max_age_minutes_false (по подразбиране 10 мин, per заданието) - съставът
    все още може да се обяви междувременно."""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM lineups_cache WHERE fixture_id=?", (fixture_id,)).fetchone()
    conn.close()
    if not row:
        return None
    if row["available"]:
        return True
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except (ValueError, TypeError):
        return None
    if datetime.now() - fetched > timedelta(minutes=max_age_minutes_false):
        return None
    return False


def set_cached_lineups_available(fixture_id, available):
    conn = get_conn()
    conn.execute("""
        INSERT INTO lineups_cache (fixture_id, available, fetched_at)
        VALUES (?,?,?)
        ON CONFLICT(fixture_id) DO UPDATE SET
            available=excluded.available, fetched_at=excluded.fetched_at
    """, (fixture_id, int(available), datetime.now().isoformat()))
    conn.commit()
    conn.close()


init_db()
