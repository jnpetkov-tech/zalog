"""
web/prognozi.py — /prognozi, новата ПУБЛИЧНА страница (Партида 2,
01.09.2026, задачата от Дака). За разлика от /daily (админска, остава
непокътната - т.2.1), тази страница НЕ прави никаква заявка към
API-Football (т.2.10) - чете само вече изчислени данни: predictions_snapshot
(бъдещи мачове), predictions_log (реално уредени резултати - същият
източник, който вече вика evaluation.summary(), т.2.3) и кешираните
коефициенти (odds_cache) - никога на живо.

ZADACHA_PAZARI.md (22.09.2026): редът в списъка показва трите числа 1/X/2,
страницата на мача - карта с всички публикуеми пазари (MARKET_SECTIONS,
build_market_sections по-долу). pick_selection.top_pick_for_match() вече не
се показва тук - остава единственият избор за метриките (evaluation).

Оформление/шрифт/цветове/структура: design_mockup_prognozi.html (Дака,
committed като спецификация) - числата в макета са измислен пълнеж, тук
всяко идва от базата.

Регистрира се по същия модел като web/daily.py и др. - register_X(app, ctx),
за да няма кръгов импорт с match_predictor_app.py.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, request, render_template

# Преглед на Дака (01.09.2026), т.3: match_date в predictions_snapshot/
# predictions_log е Sofia МЕСТНО време като низ "YYYY-MM-DD HH:MM", БЕЗ
# явен timezone offset (идва от fetch_upcoming_fixtures(timezone=
# "Europe/Sofia"), после [:16] отрязва offset-а - виж match_predictor_app.py).
# Серверният системен часовник е UTC (потвърдено с journalctl, gunicorn
# показва "+0000") - datetime.now() (наивно) НЕ е Sofia час, разминава се с
# 2-3 часа според DST. За коректно сравнение "мина ли началният час" взимаме
# ТЕКУЩОТО Sofia време изрично, форматирано по същия начин ("YYYY-MM-DD
# HH:MM") - низово сравнение работи коректно, защото форматът е ISO-подобен.
SOFIA_TZ = ZoneInfo("Europe/Sofia")


def _now_sofia_str():
    return datetime.now(SOFIA_TZ).strftime("%Y-%m-%d %H:%M")

# т.2.5: build-predictions-snapshot.timer (systemd, /etc/systemd/system/) -
# OnCalendar=*-*-* *:15/30:00 - точно на 30 мин. Ако таймерът някога се
# промени, тази стойност трябва да се обнови ръчно заедно с него (чисто
# козметичен текст в подзаглавието, не логика).
SNAPSHOT_INTERVAL_MINUTES = 30

# Преглед на Дака (01.09.2026), т.1: ако build-predictions-snapshot.timer
# спре (същия клас проблем като incremental_refresh.py, архивиран по грешка
# - виж CLAUDE_HANDOFF.md, раздел 3), страницата не бива тихо да сервира
# вчерашни прогнози с уверен тон. 90 мин = 3 пропуснати 30-мин пускания.
SNAPSHOT_STALE_AFTER_MINUTES = 90

DAY_TAB_COUNT = 7  # съвпада с DAYS_AHEAD прозореца, проверено т.2.6

# A2 (ZADACHA_FAZA1.md, 19.09.2026): колко уредени мача се показват наведнъж
# в таб "Приключили" и колко добавя бутонът "Покажи още".
FINISHED_PAGE_SIZE = 25
FINISHED_LIMIT_MAX = 2000

BG_WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
BG_MONTHS_SHORT = ["яну", "фев", "мар", "апр", "май", "юни",
                    "юли", "авг", "сеп", "окт", "ное", "дек"]

# ZADACHA_PRAZNO.md (24.09.2026): в международните паузи страницата стоеше
# празна без обяснение. Колко дни напред гледаме в снимката, за да кажем
# "следващите мачове са в ..." - ако в тези дни няма нито един мач, текстът
# е "още не са изчислени" (различно от "почиват").
EMPTY_LOOKAHEAD_DAYS = 14
# "в петък, 26 септември" - с предлога ("във вторник"), както се казва.
BG_WEEKDAYS_ON = ["в понеделник", "във вторник", "в сряда", "в четвъртък",
                  "в петък", "в събота", "в неделя"]
BG_MONTHS_GEN = ["януари", "февруари", "март", "април", "май", "юни", "юли",
                 "август", "септември", "октомври", "ноември", "декември"]


def _next_day_phrase(d, today):
    """ZADACHA_PRAZNO.md: "в петък, 26 септември" / "утре, 25 септември"."""
    when = "утре" if d == today + timedelta(days=1) else BG_WEEKDAYS_ON[d.weekday()]
    return f"{when}, {d.day} {BG_MONTHS_GEN[d.month - 1]}"


# ZADACHA_PAZARI.md, ЧАСТ Б (22.09.2026): страницата на мача е карта с
# пазари - всеки пазар с ВСИЧКИТЕ си изходи един до друг, в този ред.
# (заглавие на секция, [(код, етикет на изхода), ...] на пазар, сбор на
# изходите в %). Етикетите с {home}/{away} се попълват с кирилските имена.
# Голове над/под 1.5 и 3.5 не се смятат никъде в системата (само 2.5) -
# затова секция "Голове" има само реда за 2.5 (виж доклада в git log).
MARKET_SECTIONS = [
    ("Краен резултат", [
        ([("home_win", "1"), ("draw", "X"), ("away_win", "2")], 100),
    ]),
    ("Двоен шанс", [
        ([("dc_1x", "1X"), ("dc_12", "12"), ("dc_x2", "X2")], 200),
    ]),
    ("Голове", [
        ([("over25", "Над 2.5"), ("under25", "Под 2.5")], 100),
    ]),
    ("Двата отбора отбелязват", [
        ([("btts_yes", "Да"), ("btts_no", "Не")], 100),
    ]),
    ("Голове на отбор", [
        ([("home_over15", "{home} над 1.5"), ("home_under15", "{home} под 1.5")], 100),
        ([("away_over15", "{away} над 1.5"), ("away_under15", "{away} под 1.5")], 100),
    ]),
    ("Корнери", [
        ([("corners_total_over_9.5", "Над 9.5"), ("corners_total_under_9.5", "Под 9.5")], 100),
    ]),
]
# Изходите на един пазар трябва да се събират около 100% (двойният шанс -
# около 200%, всеки изход покрива два от трите). 1X2 може да се отклони,
# защото BLEND_WEIGHTS смесва изходите с различно тегло (виж
# validation/blend_weights_v2_20260922.md) - пазар извън този диапазон не се
# показва за конкретния мач, вместо да публикуваме числа, които не се сумират.
# 23.09.2026 (ZADACHA_MODEL1.md): BLEND_WEIGHTS = 0.0 -> 1X2 вече се сумира до
# 100%, правилото остава само като предпазител (validation/blend_off_impact_20260923.txt).
MARKET_SUM_TOLERANCE_PCT = 3.0


def build_market_sections(rows, league, policy, max_pct, home_cy, away_cy):
    """Редовете (predictions_snapshot или predictions_log) за един мач ->
    секциите на картата. Пазар влиза само ако ВСИЧКИТЕ му изходи са налични,
    publishable за лигата, под max_pct (артефакт праг) и сборът им е в
    допустимия диапазон. Секция без нито един пазар отпада изцяло."""
    pct_by_code = {r["market_code"]: r["pick_pct"] for r in rows if r["pick_pct"] is not None}
    sections = []
    for title, markets in MARKET_SECTIONS:
        shown = []
        for outcomes, expected_sum in markets:
            pcts = [pct_by_code.get(code) for code, _ in outcomes]
            if any(p is None or p >= max_pct for p in pcts):
                continue
            if not all(policy.is_publishable(league, code) for code, _ in outcomes):
                continue
            total = sum(pcts) * 100.0 / expected_sum
            if abs(total - 100.0) > MARKET_SUM_TOLERANCE_PCT:
                continue
            shown.append([{"code": code, "label": label.format(home=home_cy, away=away_cy), "pct": p}
                          for (code, label), p in zip(outcomes, pcts)])
        if shown:
            sections.append({"title": title, "markets": shown})
    return sections


def x12_from_sections(sections):
    """ЧАСТ В: трите числа 1/X/2 за реда в списъка - буквално секцията
    "Краен резултат" от картата на мача (същите филтри), или None, ако 1X2
    не е публикуем/не се сумира за този мач. Най-високото се маркира."""
    for sec in sections:
        if sec["title"] == "Краен резултат":
            outcomes = sec["markets"][0]
            top = max(o["pct"] for o in outcomes)
            return [{**o, "top": o["pct"] == top} for o in outcomes]
    return None


def _day_tab(d, today, match_count=0):
    if d == today:
        label = "Днес"
    elif d == today + timedelta(days=1):
        label = "Утре"
    else:
        label = BG_WEEKDAYS_SHORT[d.weekday()]
    return {"offset": (d - today).days, "date": d.isoformat(), "label": label,
            "short": f"{d.day} {BG_MONTHS_SHORT[d.month - 1]}",
            "count": match_count}


# ZADACHA_GOLQMA.md, Етап 1.3 (24.09.2026): колоните от дневника, нужни за
# отчета и "Приключили" (evaluation.summary/published_picks + редът в списъка).
HISTORY_COLUMNS = ["fixture_id", "league", "match_date", "home_team", "away_team", "market_code",
                   "pick_pct", "status", "market_odds", "our_fair_odds",
                   "actual_home_goals", "actual_away_goals"]


def register_prognozi_routes(app, ctx):
    ALL_LEAGUES = ctx["ALL_LEAGUES"]
    LEAGUE_FLAGS = ctx["LEAGUE_FLAGS"]
    st = ctx["st"]
    evaluation = ctx["evaluation"]
    ps = ctx["ps"]
    policy = ctx["policy"]
    to_cyrillic = ctx["to_cyrillic"]

    prognozi_bp = Blueprint("prognozi", __name__)

    # ZADACHA_GOLQMA.md, Етап 1.3-1.4 (24.09.2026): всичко, което зависи от
    # ЦЕЛИЯ дневник (трите числа горе, "Вчера", списъкът "Приключили"), се
    # смята веднъж и се пази в паметта, докато дневникът или доверието
    # (trust_derived) не се сменят. Преди всяко зареждане четеше целия
    # predictions_log и два пъти избираше публикуваната прогноза за всеки мач
    # (~0.5 с при 25 хил. реда, растящо с дневника). Ключът: броячът на
    # промените в predictions_log (тригери, system_tracker.init_db) +
    # статусите от trust_derived, с които policy реално работи в момента.
    history_cache = {"key": None, "state": None}

    def _policy_fingerprint():
        use_derived = bool(getattr(policy, "USE_DERIVED_TRUST", False))
        derived = policy._get_derived() if use_derived else {}
        return use_derived, tuple(sorted((k, (v or {}).get("status")) for k, v in derived.items()))

    def _history_state():
        version = st.get_table_version("predictions_log")
        key = (version, _policy_fingerprint())
        if version is not None and history_cache["key"] == key:
            return history_cache["state"]
        # Само мачовете с поне един уреден ред (SQL) - прогнозата на мач без
        # уреден ред не може да е уредена, а отчетът/списъкът са само за уредени.
        predictions = st.list_predictions(only_settled_fixtures=True, columns=HISTORY_COLUMNS)
        scorecard = evaluation.summary(predictions, policy)
        published = evaluation.published_picks(predictions, policy)
        finished = [p for p in published if p["status"] in ("won", "lost")]
        # най-скоро уредените отгоре; sort-ът е стабилен - при еднаква дата
        # остава редът на published, както и преди.
        finished.sort(key=lambda p: p["match_date"], reverse=True)
        by_league, by_day = {}, {}
        for p in finished:
            by_league.setdefault(p["league"], []).append(p)
            day = by_day.setdefault(p["match_date"][:10], {"total": 0, "correct": 0})
            day["total"] += 1
            day["correct"] += p["status"] == "won"
        state = {"scorecard": scorecard, "finished": finished,
                 "finished_by_league": by_league, "by_day": by_day}
        history_cache["key"], history_cache["state"] = key, state
        return state

    # Смяна на входните точки (01.09.2026, задача от Дака): "/" вече е
    # публичната начална страница - СЪЩАТА view функция, два маршрута
    # (не дублиран код). "/prognozi" остава като псевдоним, за да не се
    # счупят вече дадени връзки.
    @prognozi_bp.route("/")
    @prognozi_bp.route("/prognozi")
    def prognozi():
        today = date.today()
        # ZADACHA_PRAZNO.md т.1: дали посетителят е избрал ден ИЗРИЧНО
        # (?day= в адреса). Ако не е и днес няма мачове - отваряме на първия
        # ден с мачове по-долу; ако е - уважаваме избора му.
        day_explicit = "day" in request.args
        try:
            day_offset = int(request.args.get("day", "0"))
        except ValueError:
            day_offset = 0
        day_offset = max(0, min(DAY_TAB_COUNT - 1, day_offset))

        league_filter = request.args.get("league", "all")
        status_tab = request.args.get("status", "upcoming")
        # A3 (ZADACHA_FAZA1.md, 19.09.2026): "Пропуснати" е админска функция
        # (мачове, ръчно маркирани от Дака да се пропуснат) - на публиката не
        # ѝ говори нищо, табът е махнат. Валидните стойности са само две;
        # ?status=skipped вече пада към "Предстоящи". Самата skipped_rows
        # логика долу остава непокътната (мачът продължава да НЕ се показва
        # сред предстоящите), просто няма свой таб.
        if status_tab not in ("upcoming", "finished"):
            status_tab = "upcoming"

        # A2 (ZADACHA_FAZA1.md, 19.09.2026): "Приключили" показваше ЦЯЛАТА
        # история (300+ реда) на една страница. Сървърно странициране -
        # само за този таб ("Предстоящи" е ограничен до един ден, няма нужда).
        # Рязането става ЧАК СЛЕД сортирането по-долу, за да е "последните
        # X", не "случайни X". Горната граница е предпазна - не искаме
        # ?limit=999999999 да строи безкраен списък.
        try:
            finished_limit = int(request.args.get("limit", FINISHED_PAGE_SIZE))
        except ValueError:
            finished_limit = FINISHED_PAGE_SIZE
        finished_limit = max(FINISHED_PAGE_SIZE, min(finished_limit, FINISHED_LIMIT_MAX))

        # т.2.3: трите числа горе - САМО от evaluation.summary(), нищо друго.
        # Единен fetch на predictions_log - за отчета И за "Приключили" по-долу
        # (т.3, преглед на Дака 01.09.2026: и двете вече минават през
        # evaluation.published_picks() - виж бележката там).
        #
        # A1 (ZADACHA_FAZA2.md, 19.09.2026): обратно на summary() - границата
        # до мачове с реален market_odds (summary_priced_only()) съществуваше
        # само за да съвпада n-ото на калибрацията с доходността. Доходността
        # вече не се показва тук (виж templates/prognozi.html), значи
        # калибрацията няма нужда от коефициент - стъпва на всички уредени
        # публикувани прогнози. summary_priced_only() остава в evaluation.py
        # непокътната, просто вече не се вика оттук.
        history = _history_state()
        scorecard = history["scorecard"]

        # Б1 (ZADACHA_PAT.md, 20.09.2026): "Вчера" ред - вчерашната дата по
        # софийско време (СЪЩИЯТ SOFIA_TZ като _now_sofia_str по-горе, не
        # серверния UTC системен часовник - виж бележката там защо), от
        # вече наличния `published` списък - същият източник като scorecard/
        # finished_rows по-долу, никакво ново четене. Ако вчера няма нито
        # една уредена прогноза, `yesterday` остава None и редът не се
        # показва изобщо (решение на шаблона).
        yesterday_str = (datetime.now(SOFIA_TZ).date() - timedelta(days=1)).isoformat()
        yesterday = history["by_day"].get(yesterday_str)

        notes_map = st.get_all_match_notes()

        # ---- Предстоящи / Пропуснати: от predictions_snapshot (т.2.10) ----
        # ZADACHA_PRAZNO.md: четем EMPTY_LOOKAHEAD_DAYS дни наведнъж (не само
        # избрания ден) - за броя мачове до всеки ден в лентата и за "кога са
        # следващите мачове". Същото едно четене, същият подбор по-долу -
        # броят в лентата е точно броят редове, които денят ще покаже.
        range_end_str = (today + timedelta(days=EMPTY_LOOKAHEAD_DAYS - 1)).isoformat()
        snap_rows = st.get_snapshot_rows_for_date_range(today.isoformat(), range_end_str)
        snap_by_fixture = {}
        for r in snap_rows:
            snap_by_fixture.setdefault(r["fixture_id"], []).append(r)

        # НОЩ 02.09.2026 (задача 2, NOSHT2.md): лога на двата отбора - едно
        # групово четене от fixture_meta (нула API заявки, чист DB прочит),
        # по образец на notes_map по-горе.
        fixture_meta = st.get_fixture_meta_for_fixtures(list(snap_by_fixture.keys()))

        # ZADACHA_PAZARI.md, ЧАСТ В (22.09.2026): редът в списъка вече не е
        # "една избрана прогноза" (top_pick_for_match), а трите числа 1/X/2 -
        # СЪЩИТЕ като на картата на мача (build_market_sections). Мач влиза в
        # списъка, ако картата му има поне един публикуем пазар; ако 1X2 не
        # е публикуем, колоната остава празна. Мач без нито един публикуем
        # пазар не се показва (досегашната сгъната секция "без доверена
        # прогноза" отпада - без обяснителни надписи). top_pick_for_match()
        # остава непокътнат - ползва се от метриките (evaluation), просто
        # вече не се показва тук.
        #
        # "Мачове в ход" (преглед на Дака 01.09.2026, т.2): започнал, още
        # неуреден. settled_fixture_ids - всеки уреден ред в лога (не само
        # published), за да не остане мач без публикувана топ прогноза
        # завинаги "в ход".
        settled_fixture_ids = st.get_settled_fixture_ids(snap_by_fixture.keys())
        now_sofia_str = _now_sofia_str()

        upcoming_rows, skipped_rows, in_progress_rows, settled_days = [], [], [], []
        for fixture_id, rows in snap_by_fixture.items():
            league = rows[0]["league"]
            meta = fixture_meta.get(fixture_id)
            base = {
                "fixture_id": fixture_id, "league": league,
                "league_name": ALL_LEAGUES.get(league, {}).get("name", league),
                "league_logo": ALL_LEAGUES.get(league, {}).get("logo"),
                "flag": LEAGUE_FLAGS.get(league, "⚽"),
                "date": rows[0]["match_date"], "home": rows[0]["home_team"], "away": rows[0]["away_team"],
                "home_cy": to_cyrillic(rows[0]["home_team"], league), "away_cy": to_cyrillic(rows[0]["away_team"], league),
                "home_logo": meta.get("home_logo") if meta else None,
                "away_logo": meta.get("away_logo") if meta else None,
            }
            note = notes_map.get(fixture_id)
            if note and note["skip"]:
                skipped_rows.append(base)
                continue

            sections = build_market_sections(rows, league, policy, ps.MAX_PUBLISHABLE_PCT,
                                             base["home_cy"], base["away_cy"])
            if not sections:
                continue
            card = {**base, "x12": x12_from_sections(sections)}

            if base["date"] > now_sofia_str:
                upcoming_rows.append(card)
            elif fixture_id not in settled_fixture_ids:
                in_progress_rows.append(card)
            else:
                # започнал И уреден -> в "Приключили" по-долу. Пазим само
                # деня - за текста "мачовете за този ден приключиха".
                settled_days.append(base["date"][:10])

        # ZADACHA_PRAZNO.md т.1-2: брой мачове по ден = това, което денят
        # реално показва (предстоящи + в ход), след филтъра по лига.
        league_ok = league_filter != "all" and league_filter in ALL_LEAGUES
        counts_by_day = {}
        for r in upcoming_rows + in_progress_rows:
            if not league_ok or r["league"] == league_filter:
                counts_by_day[r["date"][:10]] = counts_by_day.get(r["date"][:10], 0) + 1

        # т.1: без ?day= и днес празно -> първият ден с мачове в лентата.
        # Само за "Предстоящи" (в "Приключили" денят няма значение).
        if not day_explicit and status_tab == "upcoming" and not counts_by_day.get(today.isoformat()):
            for i in range(1, DAY_TAB_COUNT):
                if counts_by_day.get((today + timedelta(days=i)).isoformat()):
                    day_offset = i
                    break
        selected_date = today + timedelta(days=day_offset)
        selected_date_str = selected_date.isoformat()
        day_tabs = [_day_tab(today + timedelta(days=i), today,
                             counts_by_day.get((today + timedelta(days=i)).isoformat(), 0))
                    for i in range(DAY_TAB_COUNT)]

        # т.3: текст за празен ден - следващият ден с мачове СЛЕД избрания
        # (до EMPTY_LOOKAHEAD_DAYS от днес). Ако няма такъв, но другаде в
        # снимката има мачове (друга лига/по-ранен ден) - друг текст; ако
        # няма нито един мач - "още не са изчислени" (не бъркаме почивка
        # със спряла снимка).
        next_match_phrase = None
        for d_str in sorted(counts_by_day):
            if d_str > selected_date_str:
                next_match_phrase = _next_day_phrase(date.fromisoformat(d_str), today)
                break
        any_match_ahead = bool(upcoming_rows or in_progress_rows)
        selected_day_finished = selected_date_str in settled_days

        # Оттук надолу - само избраният ден, както преди.
        upcoming_rows = [r for r in upcoming_rows if r["date"][:10] == selected_date_str]
        in_progress_rows = [r for r in in_progress_rows if r["date"][:10] == selected_date_str]
        skipped_rows = [r for r in skipped_rows if r["date"][:10] == selected_date_str]

        # ---- Приключили: т.3, преглед на Дака (01.09.2026) - "два филтъра,
        # една таблица". Преди тази поправка тук се групираше predictions_log
        # ПРЕДВАРИТЕЛНО филтриран до won/lost редове, после се пускаше
        # top_pick_for_match върху ТОЗИ подмножество - различен избор от
        # evaluation.published_picks() (което избира каноничния топ пазар
        # върху ВСИЧКИ логнати редове за мача, включително pending, после
        # едва след избора проверява дали точно ТОЗИ избран ред е settled).
        # За мач с частично уредени пазари двата пътя могат да изберат
        # различен пазар - разминаване, което директно противоречи на
        # "Приключили" отговарящо на n_settled горе. Сега: буквално същият
        # `published` списък като scorecard - никакъв втори подбор.
        #
        # НЕ филтрирано по избрания ден (нарочно, за разлика от Предстоящи/
        # Пропуснати по-долу): деновете в daystrip-а са бъдещи (0..+6, т.2.6),
        # а уредените мачове са почти изцяло в миналото - ден-по-ден филтър
        # тук би направил "Приключили" практически недостижимо (сумата по
        # достъпните дни никога не би стигнала n_settled). Затова таб-броячът
        # и списъкът показват ЦЯЛАТА история на публикуваните уредени
        # прогнози (само с league филтъра по-долу) - винаги точно n_settled.
        # НОЩ 02.09.2026 (задача 2): fixture_meta не се трие никога (за
        # разлика от predictions_snapshot - clear_stale_snapshot по-долу) -
        # затова логата остават достъпни и за отдавна приключили мачове,
        # веднъж записани, докато е бил предстоящ.
        #
        # ZADACHA_GOLQMA.md 1.4: списъкът (сортиран, по лига) идва от
        # history_state; картата с пазари, логата и редовете от дневника се
        # четат САМО за мачовете, които реално ще се покажат (finished_limit),
        # не за цялата история.
        finished_all = (history["finished_by_league"].get(league_filter, []) if league_ok
                        else history["finished"])
        finished_total = len(finished_all)
        # Редовете се показват само в таб "Приключили" - в "Предстоящи" трябва
        # само броят (finished_total), затова там не четем нищо повече.
        finished_page = finished_all[:finished_limit] if status_tab == "finished" else []
        page_ids = [p["fixture_id"] for p in finished_page]
        finished_meta = st.get_fixture_meta_for_fixtures(page_ids)
        # ЧАСТ В: при приключилите - резултатът и трите числа 1/X/2 (от
        # логнатите редове за мача, същата build_market_sections), без
        # ✓/✗ оценка на избран залог.
        log_by_fixture = {}
        for r in st.list_predictions(fixture_ids=page_ids):
            log_by_fixture.setdefault(r["fixture_id"], []).append(r)
        finished_rows = []
        for p in finished_page:
            league = p["league"]
            fixture_id = p["fixture_id"]
            f_meta = finished_meta.get(fixture_id)
            home_cy, away_cy = to_cyrillic(p["home_team"], league), to_cyrillic(p["away_team"], league)
            sections = build_market_sections(log_by_fixture.get(fixture_id, []), league, policy,
                                             ps.MAX_PUBLISHABLE_PCT, home_cy, away_cy)
            finished_rows.append({
                "fixture_id": fixture_id, "league": league,
                "league_name": ALL_LEAGUES.get(league, {}).get("name", league),
                "league_logo": ALL_LEAGUES.get(league, {}).get("logo"),
                "flag": LEAGUE_FLAGS.get(league, "⚽"),
                "date": p["match_date"], "home": p["home_team"], "away": p["away_team"],
                "home_cy": home_cy, "away_cy": away_cy,
                "home_logo": f_meta.get("home_logo") if f_meta else None,
                "away_logo": f_meta.get("away_logo") if f_meta else None,
                "x12": x12_from_sections(sections),
                # A1 (ZADACHA_FAZA1.md, 19.09.2026): реалният резултат на мача.
                "hg": p["actual_home_goals"], "ag": p["actual_away_goals"],
            })

        # Преглед на Дака (01.09.2026), т.1: падащото меню обещаваше лиги от
        # СУРОВАТА снимка (snap_rows) - england2 се появяваше в менюто, но
        # нито един неин мач не оцеляваше след top_pick_for_match()
        # филтъра - избор на лигата даваше празна страница. Менюто вече се
        # строи от лигите, които РЕАЛНО имат ред в активния таб (upcoming +
        # "в ход" заедно за "Предстоящи", другите за своя таб) -
        # смятано ПРЕДИ league_filter да отреже списъците по-долу, иначе
        # менюто би показвало само една лига (избраната).
        if status_tab == "finished":
            tab_leagues = set(history["finished_by_league"])
        elif status_tab == "skipped":
            tab_leagues = {r["league"] for r in skipped_rows}
        else:
            tab_leagues = {r["league"] for r in upcoming_rows} | {r["league"] for r in in_progress_rows}
        active_leagues = sorted(tab_leagues, key=lambda k: ALL_LEAGUES.get(k, {}).get("name", k))
        league_options = [(k, ALL_LEAGUES.get(k, {}).get("name", k)) for k in active_leagues]

        if league_filter != "all" and league_filter in ALL_LEAGUES:
            upcoming_rows = [r for r in upcoming_rows if r["league"] == league_filter]
            skipped_rows = [r for r in skipped_rows if r["league"] == league_filter]
            in_progress_rows = [r for r in in_progress_rows if r["league"] == league_filter]
        else:
            league_filter = "all"

        upcoming_rows.sort(key=lambda r: r["date"])

        # A2: пълният брой се пази ЗА ПОКАЗВАНЕ (броячът на таба, "Показани X
        # от Y") - рязането е по-горе, след сортирането и league филтъра
        # (history_state), за да е "последните X от избраната лига".
        finished_has_more = finished_total > len(finished_rows)
        finished_next_limit = finished_limit + FINISHED_PAGE_SIZE
        skipped_rows.sort(key=lambda r: r["date"])
        in_progress_rows.sort(key=lambda r: r["date"])

        snapshot_freshness = st.get_snapshot_freshness()
        # т.2.10: ако снимката е изцяло празна (фоновата задача никога не е
        # пускана успешно), кажи го изрично - НЕ отиваме до API-то да
        # запълним дупката. т.2.6: ако САМО избраният ден е празен (напр.
        # извън прозореца), също казваме честно, не скриваме с празна
        # страница без обяснение.
        snapshot_empty = snapshot_freshness is None

        # Преглед на Дака (01.09.2026), т.1: видима лента, ако снимката е
        # по-стара от SNAPSHOT_STALE_AFTER_MINUTES - не крие прогнозите,
        # само казва честно кога са смятани за последно. Отделно от
        # snapshot_empty (там таблицата е изцяло празна, тук е само остаряла).
        snapshot_stale_note = None
        if snapshot_freshness:
            try:
                computed_dt = datetime.fromisoformat(snapshot_freshness)
                age_minutes = (datetime.now() - computed_dt).total_seconds() / 60
                if age_minutes > SNAPSHOT_STALE_AFTER_MINUTES:
                    snapshot_stale_note = f"Последно изчислено в {computed_dt.strftime('%H:%M')}"
            except (ValueError, TypeError):
                pass

        return render_template(
            "prognozi.html", active_page="prognozi",
            scorecard=scorecard, snapshot_interval_minutes=SNAPSHOT_INTERVAL_MINUTES,
            day_tabs=day_tabs, day_offset=day_offset, selected_date=selected_date_str,
            league_filter=league_filter, league_options=league_options,
            status_tab=status_tab,
            upcoming_rows=upcoming_rows, finished_rows=finished_rows, skipped_rows=skipped_rows,
            finished_total=finished_total, finished_limit=finished_limit,
            finished_has_more=finished_has_more, finished_next_limit=finished_next_limit,
            in_progress_rows=in_progress_rows,
            snapshot_empty=snapshot_empty, snapshot_stale_note=snapshot_stale_note,
            yesterday=yesterday,
            next_match_phrase=next_match_phrase, any_match_ahead=any_match_ahead,
            selected_day_finished=selected_day_finished,
        )

    # Публична страница на мача (01.09.2026, задача от Дака, т.2). Изричен
    # маршрут ПОД префикс "/prognozi/" - PUBLIC_PATHS е за точно съвпадение,
    # динамичен път (fixture_id) няма как да съвпадне буквално. Белият
    # списък в match_predictor_app.py::require_auth() пуска изрична
    # проверка `request.path.startswith("/prognozi/")` (по образец на
    # /static), НЕ добавя префикси в самия PUBLIC_PATHS набор (Дака: "не
    # превръщай PUBLIC_PATHS в списък с префикси"). Префиксът "/prognozi/"
    # е избран нарочно - не се пресича с никой съществуващ частен маршрут
    # (за разлика от напр. "/match", което би съвпаднало с /match_detail).
    @prognozi_bp.route("/prognozi/match/<int:fixture_id>")
    def prognozi_match(fixture_id):
        # т.2.10 (нула API заявки): само вече изчислена снимка; ако мачът е
        # извън 7-дневния прозорец (стар, вече изтрит от predictions_snapshot),
        # пада към predictions_log (също само база, никакво API извикване).
        rows = st.get_snapshot_rows_for_fixture(fixture_id)
        if not rows:
            rows = st.get_predictions_for_fixture(fixture_id)
        if not rows:
            # Тест преди commit: невалиден/несъществуващ fixture_id не бива
            # да гърми със stack trace пред публика - чиста страница.
            return render_template("prognozi_match.html", active_page="prognozi",
                                    found=False), 404

        league = rows[0]["league"]
        home, away = rows[0]["home_team"], rows[0]["away_team"]
        match_date = rows[0]["match_date"]
        meta = st.get_fixture_meta_for_fixtures([fixture_id]).get(fixture_id)

        # ZADACHA_PAZARI.md, ЧАСТ Б (22.09.2026): вместо "топ 7 по
        # вероятност" - карта с пазари, всички изходи на пазара един до друг
        # (build_market_sections по-горе). Непубликуем пазар просто липсва -
        # без бележка, без брояч на скритото, без етикет за доверие.
        home_cy, away_cy = to_cyrillic(home, league), to_cyrillic(away, league)
        sections = build_market_sections(rows, league, policy, ps.MAX_PUBLISHABLE_PCT, home_cy, away_cy)

        return render_template(
            "prognozi_match.html", active_page="prognozi", found=True,
            fixture_id=fixture_id, league=league,
            league_name=ALL_LEAGUES.get(league, {}).get("name", league),
            league_logo=ALL_LEAGUES.get(league, {}).get("logo"),
            flag=LEAGUE_FLAGS.get(league, "⚽"),
            home_cy=home_cy, away_cy=away_cy,
            home_logo=meta.get("home_logo") if meta else None,
            away_logo=meta.get("away_logo") if meta else None,
            date=match_date, sections=sections,
        )

    app.register_blueprint(prognozi_bp)
