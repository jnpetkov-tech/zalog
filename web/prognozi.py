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
BG_WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
BG_MONTHS_SHORT = ["яну", "фев", "мар", "апр", "май", "юни",
                    "юли", "авг", "сеп", "окт", "ное", "дек"]


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
        if status_tab not in ("upcoming", "finished", "skipped"):
            status_tab = "upcoming"

        # т.2.3: трите числа горе - САМО от evaluation.summary(), нищо друго.
        # Единен fetch на predictions_log - за отчета И за "Приключили" по-долу
        # (т.3, преглед на Дака 01.09.2026: и двете вече минават през
        # evaluation.published_picks() - виж бележката там).
        predictions = st.list_predictions()
        scorecard = evaluation.summary_priced_only(predictions, policy)
        published = evaluation.published_picks(predictions, policy)

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
        finished_rows.sort(key=lambda r: r["date"], reverse=True)  # най-скоро уредените отгоре
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
            no_pick_rows=no_pick_rows, in_progress_rows=in_progress_rows,
            snapshot_empty=snapshot_empty, snapshot_stale_note=snapshot_stale_note,
            market_copy_note=MARKET_COPY_NOTE,
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

        # НОЩ 02.09.2026 (задача 3, NOSHT2.md): "пълната таблица" на
        # страницата на мача вече показва ВСИЧКО публикуемо
        # (policy.is_publishable - PROVEN/WEAK/UNVERIFIED), не само
        # top-pick-eligible (ps.rank_logged_rows, стария филтър тук до
        # тази нощ - PROVEN/WEAK, никога UNVERIFIED). Разликата има
        # значение точно за england2/germany2 (структурно UNVERIFIED, виж
        # validation/pokritie_i_byudzhet_20260902.md т.5) - преди тази
        # промяна страницата им показваше празна таблица за ВСЕКИ мач,
        # сега поне честно показва "още няма история" на всеки ред. Тази
        # по-широка селекция засяга САМО тази таблица - top_pick_for_match()
        # (списъка на /prognozi) продължава да минава през rank_logged_rows/
        # is_top_pick_eligible, непроменено (виж prognozi() по-горе).
        # REJECTED/NO_DATA (is_publishable()==False) и >=95% артефакти
        # (ps.MAX_PUBLISHABLE_PCT) остават скрити, преброени в hidden_count.
        eligible = [r for r in rows
                    if r["pick_pct"] is not None and r["pick_pct"] < ps.MAX_PUBLISHABLE_PCT
                    and policy.is_publishable(league, r["market_code"])]
        eligible.sort(key=lambda r: r["pick_pct"], reverse=True)
        # Задача 3 (NOSHT3.md, 02.09.2026): посетителите виждат само топ 7
        # прогнози за мача (опростена таблица, без Пазарно/Разлика/Доверие
        # колоните) - hidden_count вече брои И филтрираните (REJECTED/NO_DATA/
        # >=95%), И всичко след топ 7, за да остане честно число.
        eligible = eligible[:7]
        hidden_count = len(rows) - len(eligible)

        def _trust_label(code, is_market_copy):
            if is_market_copy:
                return "= пазарна оценка"
            t = policy.tier(league, code)
            if t == policy.PROVEN:
                return "измерен и добър"
            if t == policy.UNVERIFIED:
                return "още няма история"
            return "измерен и слаб"  # WEAK/REJECTED/NO_DATA (REJECTED/NO_DATA вече филтрирани по-горе)

        market_rows = []
        for r in eligible:
            code = r["market_code"]
            market_pct, diff = _row_diff(fixture_id, code, r["pick_pct"])
            is_copy = code in MARKET_COPY_CODES
            market_rows.append({
                "label": r["pick_label"], "our_pct": r["pick_pct"],
                "market_pct": market_pct, "diff": diff,
                "market_copy": is_copy, "trust_label": _trust_label(code, is_copy),
            })

        return render_template(
            "prognozi_match.html", active_page="prognozi", found=True,
            fixture_id=fixture_id, league=league,
            league_name=ALL_LEAGUES.get(league, {}).get("name", league),
            league_logo=ALL_LEAGUES.get(league, {}).get("logo"),
            flag=LEAGUE_FLAGS.get(league, "⚽"),
            home_cy=to_cyrillic(home, league), away_cy=to_cyrillic(away, league),
            home_logo=meta.get("home_logo") if meta else None,
            away_logo=meta.get("away_logo") if meta else None,
            date=match_date, market_rows=market_rows, hidden_count=hidden_count,
            market_copy_note=MARKET_COPY_NOTE,
        )

    app.register_blueprint(prognozi_bp)
