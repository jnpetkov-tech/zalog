"""
web/prognozi.py — /prognozi, новата ПУБЛИЧНА страница (Партида 2,
01.09.2026, задачата от Дака). За разлика от /daily (админска, остава
непокътната - т.2.1), тази страница НЕ прави никаква заявка към
API-Football (т.2.10) - чете само вече изчислени данни: predictions_snapshot
(бъдещи мачове), predictions_log (реално уредени резултати - същият
източник, който вече вика evaluation.summary(), т.2.3) и кешираните
коефициенти (odds_cache) - никога на живо.

Прогнозата на всеки ред е pick_selection.top_pick_for_match() -
единственият избор на "прогнозата за мача" в цялото приложение (виж
CLAUDE_HANDOFF.md, ПРЕУСТРОЙСТВО раздел 14) - нито отделна логика, нито
друг праг (т.2.7).

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

# Б2 (ZADACHA_PAT.md, 20.09.2026): "Най-голяма разлика с пазара" - минимален
# брой мачове с известен пазарен процент, за да си струва да се показва
# секцията, и колко реда показва.
DIFF_HIGHLIGHTS_MIN = 3
DIFF_HIGHLIGHTS_COUNT = 5
BG_WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
BG_MONTHS_SHORT = ["яну", "фев", "мар", "апр", "май", "юни",
                    "юли", "авг", "сеп", "окт", "ное", "дек"]


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


def _day_tab(d, today):
    if d == today:
        label = "Днес"
    elif d == today + timedelta(days=1):
        label = "Утре"
    else:
        label = BG_WEEKDAYS_SHORT[d.weekday()]
    return {"offset": (d - today).days, "date": d.isoformat(), "label": label,
            "short": f"{d.day} {BG_MONTHS_SHORT[d.month - 1]}"}


def register_prognozi_routes(app, ctx):
    ALL_LEAGUES = ctx["ALL_LEAGUES"]
    LEAGUE_FLAGS = ctx["LEAGUE_FLAGS"]
    st = ctx["st"]
    evaluation = ctx["evaluation"]
    ps = ctx["ps"]
    policy = ctx["policy"]
    to_cyrillic = ctx["to_cyrillic"]
    market_info_for_pick = ctx["_market_info_for_pick"]
    MARKET_COPY_CODES = ctx["MARKET_COPY_CODES"]
    MARKET_COPY_NOTE = ctx["MARKET_COPY_NOTE"]

    prognozi_bp = Blueprint("prognozi", __name__)

    def _row_diff(fixture_id, code, our_pct):
        """Т.2.4: СЪЩАТА формула/помощна функция, която /daily вече ползва
        за 'пазар X% · разлика +Y%' (_market_info_for_pick, devig от
        кеширани коефициенти) - приложена тук за пазара, избран от
        top_pick_for_match (т.2.7), не отделно пресметнат избор."""
        cached_odds = st.get_cached_odds(fixture_id)
        info = market_info_for_pick(code, cached_odds)
        if not info:
            return None, None
        market_p, _odd = info
        market_pct = market_p * 100
        return market_pct, our_pct - market_pct

    def _snapshot_ev_pct(fixture_id, code, pick_pct):
        """Поправка 02.09.2026 (Дака: guard-ът покриваше историята
        (predictions_log), не витрината): implied EV% за избраната
        прогноза на ПРЕДСТОЯЩ мач, за да може guard-ът в pick_selection.py
        (веднъж приложен само върху predictions_log/top_pick_for_match) да
        важи и тук. predictions_snapshot редовете НЯМАТ market_odds/
        our_fair_odds колони (виж validation/ev_guard_applied_20260902.md)
        - смята се от каквото има: кешираният пазарен коефициент (st.
        get_cached_odds, СЪЩИЯТ източник като _row_diff по-горе, покрива
        само home_win/draw/away_win/over25/under25 - odds_cache схемата)
        + our_fair_odds по СЪЩАТА конвенция като system_tracker.
        log_all_markets() (100/pick_pct, закръглено на 2 знака).

        Самата EV формула и прагът НЕ се преизобретяват тук - вика
        pick_selection._row_ev_pct()/MAX_TRUSTWORTHY_EV директно (ps е
        pick_selection модула). None, ако коефициент липсва - EV не е
        сметаем за пазар извън тези пет, не гадаем."""
        cached_odds = st.get_cached_odds(fixture_id)
        odds_key = st.MARKET_ODDS_MAP.get(code)
        market_odds_val = cached_odds.get(odds_key) if (cached_odds and odds_key) else None
        if not market_odds_val or not pick_pct:
            return None
        our_fair_odds = round(100.0 / pick_pct, 2)
        return ps._row_ev_pct({"market_odds": market_odds_val, "our_fair_odds": our_fair_odds})

    # Смяна на входните точки (01.09.2026, задача от Дака): "/" вече е
    # публичната начална страница - СЪЩАТА view функция, два маршрута
    # (не дублиран код). "/prognozi" остава като псевдоним, за да не се
    # счупят вече дадени връзки.
    @prognozi_bp.route("/")
    @prognozi_bp.route("/prognozi")
    def prognozi():
        today = date.today()
        try:
            day_offset = int(request.args.get("day", "0"))
        except ValueError:
            day_offset = 0
        day_offset = max(0, min(DAY_TAB_COUNT - 1, day_offset))
        selected_date = today + timedelta(days=day_offset)
        selected_date_str = selected_date.isoformat()

        day_tabs = [_day_tab(today + timedelta(days=i), today) for i in range(DAY_TAB_COUNT)]

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
        predictions = st.list_predictions()
        scorecard = evaluation.summary(predictions, policy)
        published = evaluation.published_picks(predictions, policy)

        # Б1 (ZADACHA_PAT.md, 20.09.2026): "Вчера" ред - вчерашната дата по
        # софийско време (СЪЩИЯТ SOFIA_TZ като _now_sofia_str по-горе, не
        # серверния UTC системен часовник - виж бележката там защо), от
        # вече наличния `published` списък - същият източник като scorecard/
        # finished_rows по-долу, никакво ново четене. Ако вчера няма нито
        # една уредена прогноза, `yesterday` остава None и редът не се
        # показва изобщо (решение на шаблона).
        yesterday_str = (datetime.now(SOFIA_TZ).date() - timedelta(days=1)).isoformat()
        yesterday_settled = [p for p in published
                              if p["status"] in ("won", "lost") and p["match_date"][:10] == yesterday_str]
        yesterday = None
        if yesterday_settled:
            yesterday = {"total": len(yesterday_settled),
                         "correct": sum(1 for p in yesterday_settled if p["status"] == "won")}

        notes_map = st.get_all_match_notes()

        # ---- Предстоящи / Пропуснати: от predictions_snapshot (т.2.10) ----
        snap_rows = st.get_snapshot_rows_for_date_range(selected_date_str, selected_date_str)
        snap_by_fixture = {}
        for r in snap_rows:
            snap_by_fixture.setdefault(r["fixture_id"], []).append(r)

        # НОЩ 02.09.2026 (задача 2, NOSHT2.md): лога на двата отбора - едно
        # групово четене от fixture_meta (нула API заявки, чист DB прочит),
        # по образец на notes_map по-горе.
        fixture_meta = st.get_fixture_meta_for_fixtures(list(snap_by_fixture.keys()))

        # Преглед на Дака (01.09.2026), т.2 от предишната поправка:
        # top_pick_for_match() връща None за мач без публикуема прогноза -
        # такъв мач вече отива в no_pick_rows, сгъната секция, вместо да
        # изчезва без следа.
        #
        # Преглед на Дака (01.09.2026), нова т.2 ("мачовете в ход изчезват"):
        # часовият филтър от предишната поправка (само бъдещи в
        # "Предстоящи") остави дупка - мач, започнал, но още неуреден
        # (check_results върви на 3 часа), не е нито в "Предстоящи" (вече в
        # миналото), нито в "Приключили" (не е settled) - изчезваше напълно.
        # settled_fixture_ids - същият published списък, който вече дефинира
        # "Приключили" по-долу (т.3 от предишната поправка) - едно
        # определение за "уреден", не второ.
        settled_fixture_ids = {p["fixture_id"] for p in published if p["status"] in ("won", "lost")}
        now_sofia_str = _now_sofia_str()

        upcoming_rows, skipped_rows, no_pick_rows, in_progress_rows = [], [], [], []
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
                # Пропуснат от Дака - приоритетно пред "без доверена
                # прогноза"/"в ход" (мачът може реално да няма прогноза И да
                # е пропуснат - показва се като пропуснат, не дублиран).
                skipped_rows.append(base)
                continue

            # НОЩ 02.09.2026 (задача 3, NOSHT2.md): predictions_snapshot вече
            # пази до 24 пазара на мач (виж build_predictions_snapshot.py),
            # не само осемте сурови кандидата - ГРАНИЦАТА, изрично поставена
            # в задачата, е top_pick_for_match() да продължи да избира от
            # ТОЧНО СЪЩОТО множество като преди. Филтърът тук е буквално
            # предишното съдържание на снимката (is_candidate=1 маркира
            # редовете от m["picks"], незасегнати от тазвечершната промяна) -
            # потвърдено с 0 разминавания върху 168 живи мача преди деплой,
            # виж validation/full_market_table_20260902.md.
            candidate_rows = [r for r in rows if r["is_candidate"]]
            top = ps.top_pick_for_match(candidate_rows, league, policy)
            if top:
                # 02.09.2026: guard-ът в pick_selection.py вече отхвърля
                # такъв избор за predictions_log/top_pick_for_match, но
                # predictions_snapshot редовете (тук) нямат market_odds/
                # our_fair_odds - guard-ът там е физически неприложим.
                # Смятаме implied EV отделно (_snapshot_ev_pct, СЪЩАТА
                # формула/праг от pick_selection) и третираме "над прага"
                # точно като "top_pick_for_match върна None" - НЕ показваме
                # прогнозата с предупреждение, отива в "без доверена
                # прогноза" (прагът значи "не вярваме", не "с уговорка").
                ev_pct = _snapshot_ev_pct(fixture_id, top["market_code"], top["pick_pct"])
                if ev_pct is not None and ev_pct > ps.MAX_TRUSTWORTHY_EV:
                    top = None
            if not top:
                # "Без доверена прогноза" - само бъдещи (т.3 от предишната
                # поправка); ако вече е започнал и няма прогноза, просто
                # няма какво честно да се покаже - извън обявения обхват.
                if base["date"] > now_sofia_str:
                    no_pick_rows.append(base)
                continue

            market_pct, diff = _row_diff(fixture_id, top["market_code"], top["pick_pct"])
            # Преглед на Дака (01.09.2026), спешно т.1: BLEND_WEIGHTS["home_win"]=1.0
            # -> home_win е в MARKET_COPY_CODES -> показаното число Е
            # обезвигованата пазарна оценка буквално, моделът не добавя
            # нищо - вече честно разкрито тук (преди го нямаше на
            # /prognozi, само на админските страници през build_diff_row()).
            card = {**base, "pick_label": top["pick_label"], "pick_pct": top["pick_pct"],
                    "market_pct": market_pct, "diff": diff, "status": None,
                    "market_copy": top["market_code"] in MARKET_COPY_CODES}

            if base["date"] > now_sofia_str:
                upcoming_rows.append(card)
            elif fixture_id not in settled_fixture_ids:
                # "Мачове в ход": започнал, не е в published_picks() като
                # won/lost - показва СЪЩАТА прогноза, изчислена преди мача
                # (predictions_snapshot не се преизчислява живо за мачове в
                # ход), без резултат/минута/live преизчисление. Излиза
                # оттук автоматично, щом published_picks() го покаже
                # settled - никаква отделна логика за премахване.
                in_progress_rows.append(card)
            # else: започнал И уреден -> вече е в "Приключили" по-долу,
            # пропускаме тук напълно (без дублиране).

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
        finished_meta = st.get_fixture_meta_for_fixtures([p["fixture_id"] for p in published])
        finished_rows = []
        for p in published:
            if p["status"] not in ("won", "lost"):
                continue
            league = p["league"]
            fixture_id = p["fixture_id"]
            f_meta = finished_meta.get(fixture_id)
            market_pct, diff = _row_diff(fixture_id, p["market_code"], p["pick_pct"])
            finished_rows.append({
                "fixture_id": fixture_id, "league": league,
                "league_name": ALL_LEAGUES.get(league, {}).get("name", league),
                "league_logo": ALL_LEAGUES.get(league, {}).get("logo"),
                "flag": LEAGUE_FLAGS.get(league, "⚽"),
                "date": p["match_date"], "home": p["home_team"], "away": p["away_team"],
                "home_cy": to_cyrillic(p["home_team"], league), "away_cy": to_cyrillic(p["away_team"], league),
                "home_logo": f_meta.get("home_logo") if f_meta else None,
                "away_logo": f_meta.get("away_logo") if f_meta else None,
                "pick_label": p["pick_label"], "pick_pct": p["pick_pct"],
                "market_pct": market_pct, "diff": diff, "status": p["status"],
                "market_copy": p["market_code"] in MARKET_COPY_CODES,
                # A1 (ZADACHA_FAZA1.md, 19.09.2026): реалният резултат на мача.
                # predictions_log ги пази още от init_db() (actual_home_goals/
                # actual_away_goals, попълвани от check_results()) - published_picks()
                # връща същите редове, така че тук няма нито ново четене, нито
                # нова заявка. None-безопасно: шаблонът пада към тиренцето.
                "hg": p["actual_home_goals"], "ag": p["actual_away_goals"],
            })

        # Преглед на Дака (01.09.2026), т.1: падащото меню обещаваше лиги от
        # СУРОВАТА снимка (snap_rows) - england2 се появяваше в менюто, но
        # нито един неин мач не оцеляваше след top_pick_for_match()
        # филтъра - избор на лигата даваше празна страница. Менюто вече се
        # строи от лигите, които РЕАЛНО имат ред в активния таб (upcoming +
        # no_pick заедно за "Предстоящи", всяка от другите две за своя таб) -
        # смятано ПРЕДИ league_filter да отреже списъците по-долу, иначе
        # менюто би показвало само една лига (избраната).
        if status_tab == "finished":
            tab_leagues = {r["league"] for r in finished_rows}
        elif status_tab == "skipped":
            tab_leagues = {r["league"] for r in skipped_rows}
        else:
            tab_leagues = ({r["league"] for r in upcoming_rows} | {r["league"] for r in no_pick_rows}
                            | {r["league"] for r in in_progress_rows})
        active_leagues = sorted(tab_leagues, key=lambda k: ALL_LEAGUES.get(k, {}).get("name", k))
        league_options = [(k, ALL_LEAGUES.get(k, {}).get("name", k)) for k in active_leagues]

        if league_filter != "all" and league_filter in ALL_LEAGUES:
            upcoming_rows = [r for r in upcoming_rows if r["league"] == league_filter]
            finished_rows = [r for r in finished_rows if r["league"] == league_filter]
            skipped_rows = [r for r in skipped_rows if r["league"] == league_filter]
            no_pick_rows = [r for r in no_pick_rows if r["league"] == league_filter]
            in_progress_rows = [r for r in in_progress_rows if r["league"] == league_filter]
        else:
            league_filter = "all"

        upcoming_rows.sort(key=lambda r: r["date"])

        # Б2 (ZADACHA_PAT.md, 20.09.2026): "Най-голяма разлика с пазара" -
        # само в таба "Предстоящи", от буквално upcoming_rows (вече носи
        # pick_pct/market_pct/diff - никаква нова сметка), след league
        # филтъра по-горе и след сортирането, за да отговаря на точно това,
        # което се вижда в списъка отдолу. Скрито под DIFF_HIGHLIGHTS_MIN
        # известни пазарни проценти - твърде малка извадка да е показателна.
        diff_highlights = []
        if status_tab == "upcoming":
            known_market = [r for r in upcoming_rows if r["market_pct"] is not None]
            if len(known_market) >= DIFF_HIGHLIGHTS_MIN:
                diff_highlights = sorted(known_market, key=lambda r: abs(r["diff"]), reverse=True)[:DIFF_HIGHLIGHTS_COUNT]

        finished_rows.sort(key=lambda r: r["date"], reverse=True)  # най-скоро уредените отгоре
        # A2: пълният брой се пази ЗА ПОКАЗВАНЕ (броячът на таба, "Показани X
        # от Y") - режем чак тук, след сортирането и след league филтъра, за
        # да е "последните X от избраната лига".
        finished_total = len(finished_rows)
        finished_rows = finished_rows[:finished_limit]
        finished_has_more = finished_total > len(finished_rows)
        finished_next_limit = finished_limit + FINISHED_PAGE_SIZE
        skipped_rows.sort(key=lambda r: r["date"])
        no_pick_rows.sort(key=lambda r: r["date"])
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
            no_pick_rows=no_pick_rows, in_progress_rows=in_progress_rows,
            snapshot_empty=snapshot_empty, snapshot_stale_note=snapshot_stale_note,
            market_copy_note=MARKET_COPY_NOTE,
            yesterday=yesterday, diff_highlights=diff_highlights,
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
