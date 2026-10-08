"""i18n.py — бутон БГ | EN на публичните страници (ZADACHA_EZIK, Дака 08.10.2026).

Само публичните страници: "/", "/prognozi", "/prognozi/match/<id>" (web/prognozi.py, register(bp) върху неговия Blueprint - така
езикът не стига до админа: /admin, /1 и всичко зад паролата остават на български, независимо от бисквитката).

Превключвател LANG_SWITCH в .env (0/липсва = няма бутон, ?lang= се пренебрегва, страниците байт по байт както без този модул).
Изборът: ?lang=en|bg -> бисквитка "lang" (1 година, SameSite=Lax) и важи веднага; иначе бисквитката; иначе bg. Друга стойност -> bg.

t("български текст") -> английският превод при en, оригиналът при bg. Ключът е самият български низ - при bg изходът не може да се
промени. Липсващ превод при en -> българският и ред (веднъж на низ) в i18n_missing_log.txt. Сравненията в кода и шаблоните остават
върху българските стойности - превежда се само при рисуване.
"""
import gzip
import json
import os
import re
import threading
from datetime import datetime, timedelta

import config

ROOT = os.path.dirname(os.path.abspath(__file__))
MISSING_LOG = os.path.join(ROOT, "i18n_missing_log.txt")
LANGS = ("bg", "en")
COOKIE = "lang"
COOKIE_MAX_AGE = 365 * 24 * 3600
KEEP_ARGS = ("day", "status", "league", "limit")      # параметрите, които бутонът пази
CYR = re.compile(r"[А-Яа-яЁёЪъ]")

# ----------------------------------------------------------------------------------------------- преводите (ключ = българският низ)
EN = {
    # заглавия, подзаглавие
    "SportBG — Прогнози": "SportBG — Predictions",
    "Прогнози": "Predictions",
    "Числата преди мача — за всички големи първенства.": "Pre-match numbers for all major leagues.",
    "Показваме и какво сме познали, и какво не.": "We show both what we got right and what we got wrong.",
    "Обновява се на всеки {n} минути.": "Updated every {n} minutes.",
    # отчетът (само при PUBLIC_HIDE=0)
    "{n} проверени прогнози ·": "{n} checked predictions ·",
    "обещахме {p}%, познахме само {a}%": "we said {p}%, we got only {a}% right",
    "обещахме {p}%, познахме {a}%": "we said {p}%, we got {a}% right",
    "Все още няма достатъчно уредени прогнози за отчет": "Not enough settled predictions for a report yet",
    "виж пълния отчет →": "see the full report →",
    "Вчера: познахме {c} от {n}": "Yesterday: {c} of {n} correct",
    "Пълен отчет": "Full report",
    "уредени прогнози до момента": "settled predictions so far",
    "колко точни са вероятностите ни": "how accurate our probabilities are",
    "обещахме": "we said",
    "познахме": "we got right",
    # лентата, филтрите, табовете
    "Числата може да не са най-новите.": "The numbers may not be the latest.",
    "Всички лиги": "All leagues",
    "Предстоящи": "Upcoming",
    "Приключили": "Finished",
    "Час": "Time",
    "Мач": "Match",
    "Дата": "Date",
    "мач": "match",
    "мача": "matches",
    "обновено след съставите {hm}": "updated after the line-ups {hm}",
    "Мачове в ход ({n}). Показаното е отпреди началото на мача.": "Matches in progress ({n}). What is shown is from before kick-off.",
    "резултатът се проверява": "result being checked",
    "експериментална прогноза - за тази лига не е минала проверката": "experimental prediction - it has not passed the check for this league",
    "експ.": "exp.",
    # празни състояния
    "Прогнозите за този ден още не са готови.": "Predictions for this day are not ready yet.",
    "Мачовете за този ден приключиха.": "The matches for this day are over.",
    "В тази лига няма мачове този ден.": "There are no matches in this league on this day.",
    "Първенствата почиват.": "The leagues are on a break.",
    "Следващите мачове са {when}.": "The next matches are {when}.",
    "Прогнозите за следващите дни още не са изчислени.": "Predictions for the next days have not been calculated yet.",
    "В тази лига няма мачове за този и следващите дни.": "There are no matches in this league on this day or the next days.",
    "Няма мачове за този и следващите дни.": "There are no matches on this day or the next days.",
    "Няма уредени мачове все още.": "No settled matches yet.",
    "Всички приключили мачове, не само от избрания ден.": "All finished matches, not only from the selected day.",
    "Показани {shown} от {total}": "Showing {shown} of {total}",
    "Покажи още 25": "Show 25 more",
    "Няма пропуснати мачове за този ден.": "No skipped matches on this day.",
    "Изключен от прогнозите": "Excluded from predictions",
    # „Как да чета тези числа“
    "Как да чета тези числа": "How to read these numbers",
    "<b>Процентът</b> до всеки изход — нашата прогноза.": "<b>The percentage</b> next to each outcome is our prediction.",
    "⚠️ Честно казано засега": "⚠️ To be honest, so far",
    "Часовете са българско време.": "Times are Bulgarian time (EET/EEST).",
    "Числата са оценка на нашия статистически модел и могат да грешат. Проверявали сме и дали следването на тези прогнози би било "
    "печелившо — не би било: измерено върху всички публикувани прогнози, резултатът е отрицателен и вече не се обяснява със случайност. "
    "Затова тук няма съвети за залагане, а само статистика: колко вероятен смятаме даден изход.":
        "The numbers are an estimate from our statistical model and can be wrong. We have also checked whether following these predictions "
        "would be profitable — it would not: measured over all published predictions, the result is negative and can no longer be explained "
        "by chance. That is why there is no betting advice here, only statistics: how likely we think an outcome is.",
    "Затова числата тук са <b>описателни</b> — показват какво сме измерили до момента. Не са съвет какво да правиш.":
        "So the numbers here are <b>descriptive</b> — they show what we have measured so far. They are not advice on what to do.",
    "🔞 Отговорна игра": "🔞 Responsible gambling",
    "Съдържанието в тази секция е информационно и статистическо. То не е съвет за залагане и не гарантира резултат — никой модел не може "
    "да гарантира изхода на спортно събитие.":
        "The content in this section is informational and statistical. It is not betting advice and does not guarantee any result — no model "
        "can guarantee the outcome of a sporting event.",
    "Хазартът е забранен за лица под 18 години. Залагането носи финансов риск и може да доведе до пристрастяване — играй отговорно, само с "
    "пари, които можеш да си позволиш да загубиш.":
        "Gambling is prohibited for persons under 18. Betting carries financial risk and can lead to addiction — play responsibly, only with "
        "money you can afford to lose.",
    "Прогнозите се основават на статистически модел и не представляват съвет за залагане. Хазартът е забранен за лица под 18 години. "
    "Резултатите от миналото не гарантират бъдещи резултати.":
        "The predictions are based on a statistical model and do not constitute betting advice. Gambling is prohibited for persons under 18. "
        "Past results do not guarantee future results.",
    # страницата на мача
    "Мачът не е намерен": "Match not found",
    "← Всички прогнози": "← All predictions",
    "Няма прогноза за този мач.": "There is no prediction for this match.",
    "срещу": "vs",
    "За мача": "About the match",
    "Искаш повече обяснения? → Как да чета тези числа": "Want more explanation? → How to read these numbers",
    "Прогнозите са вероятности, изчислени от модел. Не са гаранция за резултат.":
        "Predictions are probabilities calculated by a model. They are not a guarantee of any result.",
    "Показваме всичко, което моделът смята. „Проверен“ — прогнозата е минала проверката на минали мачове; „експериментален“ — не е минал "
    "или още няма история.":
        "We show everything the model calculates. “Verified” — the prediction has passed the check on past matches; “experimental” — it "
        "has not passed or there is no history yet.",
    # секциите на картата (MARKET_SECTIONS, ALL_SECTIONS, EXTRA_SECTIONS)
    "Краен резултат": "Full-time result",
    "Двоен шанс": "Double chance",
    "Голове": "Goals",
    "Двата отбора отбелязват": "Both teams to score",
    "Голове на отбор": "Team goals",
    "Корнери": "Corners",
    "Полувреме": "Half-time",
    "Пръв гол": "First goal",
    "Точен резултат": "Correct score",
    "Точен резултат (най-вероятните)": "Correct score (most likely)",
    "Чиста мрежа": "Clean sheet",
    "Полувреме / край": "Half-time / full-time",
    "Картони": "Cards",
    "няма данни": "no data",
    # етикетите и причините (само при PUBLIC_HIDE=0 и SHOW_ALL=1)
    "проверен": "verified",
    "експериментален": "experimental",
    "не е мерен": "not measured",
    "прекалено уверен": "overconfident",
    "на ръба": "borderline",
    "слаб в лигата": "weak in this league",
    "малко данни": "little data",
    "плах": "too cautious",
}

# изходите на пазарите (етикетите на клетките); {home}/{away} се попълват с имената след превода
OUTCOME_EN = {"Да": "Yes", "Не": "No", "Никой": "No goal", "{home} не допуска": "{home} keeps a clean sheet",
              "{away} не допуска": "{away} keeps a clean sheet"}
_OVER_UNDER = re.compile(r"^(\{home\} |\{away\} )?(Над|Под|над|под) (\d+(?:\.\d+)?)$")

LEAGUES_EN = {
    "bulgaria": "Bulgaria – First League", "bulgaria2": "Bulgaria – Second League", "england": "Premier League",
    "england2": "England – Championship", "germany": "Bundesliga", "germany2": "Germany – 2. Bundesliga", "spain": "La Liga",
    "spain2": "Spain – Segunda División", "italy": "Serie A", "italy2": "Italy – Serie B", "france": "Ligue 1",
    "france2": "France – Ligue 2", "portugal": "Primeira Liga", "portugal2": "Portugal – Liga Portugal 2",
    "champions_league": "Champions League", "europa_league": "Europa League", "conference_league": "Conference League",
}

WEEKDAYS_SHORT_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS_SHORT_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


# ----------------------------------------------------------------------------------------------- езикът на заявката
def enabled():
    return bool(getattr(config, "LANG_SWITCH", False))


def current():
    """"en" само в заявка към публичната страница (g.lang, сложено от register) при включен превключвател; иначе "bg"."""
    try:
        from flask import g, has_request_context
        return g.get("lang", "bg") if has_request_context() else "bg"
    except Exception:
        return "bg"


_missing_seen = set()
_missing_lock = threading.Lock()


def _missing(s):
    with _missing_lock:
        if s in _missing_seen:
            return
        _missing_seen.add(s)
    try:
        with open(MISSING_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.utcnow().isoformat(timespec='seconds')} {s!r}\n")
    except Exception:
        pass


def t(s, **kw):
    out = s
    if current() == "en":
        tr = EN.get(s)
        if tr is None:
            _missing(s)
        else:
            out = tr
    return out.format(**kw) if kw else out


# ----------------------------------------------------------------------------------------------- лиги, изходи, дати
_api_names = {}


def _api_league_name(key):
    """Английското име от API-то (api_raw/leagues/<лига>.json.gz, теглено вече) - за нова лига без превод в LEAGUES_EN."""
    if key not in _api_names:
        name = None
        try:
            with gzip.open(os.path.join(ROOT, "api_raw", "leagues", f"{key}.json.gz"), "rt", encoding="utf-8") as f:
                name = json.load(f)["response"][0]["league"]["name"]
        except Exception:
            name = None
        _api_names[key] = name
    return _api_names[key]


def league_name(key, bg_name):
    if current() != "en":
        return bg_name
    if key in LEAGUES_EN:
        return LEAGUES_EN[key]
    name = _api_league_name(key)
    if name:
        return name
    _missing(f"лига: {key}")
    return key


def outcome_label(label):
    """"Над 2.5" -> "Over 2.5", "{home} под 1.5" -> "{home} under 1.5", "Да" -> "Yes"; без кирилица ("1", "X", "1:0", "{home}") - както е."""
    m = _OVER_UNDER.match(label)
    if m:
        word = "Over" if m.group(2) in ("Над", "над") else "Under"
        return f"{m.group(1)}{word.lower()} {m.group(3)}" if m.group(1) else f"{word} {m.group(3)}"
    if label in OUTCOME_EN:
        return OUTCOME_EN[label]
    if CYR.search(label):
        _missing(label)
    return label


def localize_sections(sections, home, away):
    """Секции, построени с имена "{home}"/"{away}" (web/prognozi.py при en) -> етикетите на изходите на английски, с имената на отборите.
    Заглавията на секциите остават български в данните (по тях се сравнява) - превеждат се в шаблона."""
    for sec in sections:
        for m in sec["markets"]:
            for o in (m["outcomes"] if isinstance(m, dict) else m):
                o["label"] = outcome_label(o["label"]).format(home=home, away=away)
    return sections


def day_label(match_date, enabled=True):
    """"Fri, 9 Oct" (английският вариант на web/prognozi.bg_day_label)."""
    if not enabled:
        return ""
    try:
        d = datetime.strptime(str(match_date)[:10], "%Y-%m-%d").date()
        return f"{WEEKDAYS_SHORT_EN[d.weekday()]}, {d.day} {MONTHS_SHORT_EN[d.month - 1]}"
    except Exception:
        return ""


def day_tab(d, today):
    """-> (етикет, кратка дата): ("Today", "8 Oct"), ("Tomorrow", ...), ("Fri", "10 Oct")."""
    label = "Today" if d == today else "Tomorrow" if d == today + timedelta(days=1) else WEEKDAYS_SHORT_EN[d.weekday()]
    return label, f"{d.day} {MONTHS_SHORT_EN[d.month - 1]}"


def next_day_phrase(d, today):
    """"on Friday, 26 September" / "tomorrow, 25 September"."""
    when = "tomorrow" if d == today + timedelta(days=1) else f"on {WEEKDAYS_EN[d.weekday()]}"
    return f"{when}, {d.day} {MONTHS_EN[d.month - 1]}"


# ----------------------------------------------------------------------------------------------- Flask
def lang_url(code):
    """Същият адрес със същите параметри (day, status, league, limit) + lang=code."""
    from flask import request
    from urllib.parse import urlencode
    args = [(k, request.args.get(k)) for k in KEEP_ARGS if k in request.args] + [("lang", code)]
    return f"{request.path}?{urlencode(args)}"


def register(bp):
    """Върху Blueprint-а на публичните страници (web/prognozi.py): езикът на заявката, бисквитката, Vary: Cookie, и t/lang/lang_url
    в шаблоните. Превключвателят се чете тук (при старта на приложението)."""
    from flask import g, request
    on = enabled()

    @bp.before_request
    def _lang():
        g.lang, g.lang_set = "bg", None
        if not on:
            return
        q = request.args.get("lang")
        if q is not None:
            if q in LANGS:
                g.lang = g.lang_set = q
        else:
            c = request.cookies.get(COOKIE)
            if c in LANGS:
                g.lang = c

    @bp.after_request
    def _cookie(resp):
        if on:
            if g.get("lang_set"):
                resp.set_cookie(COOKIE, g.lang_set, max_age=COOKIE_MAX_AGE, samesite="Lax", path="/")
            resp.vary.add("Cookie")
        return resp

    @bp.context_processor
    def _ctx():
        return {"t": t, "lang": current(), "lang_switch": on, "lang_url": lang_url}
