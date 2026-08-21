"""
prediction_policy.py

ЕДИНСТВЕН ИЗТОЧНИК НА ИСТИНАТА за това кои (лига, пазар) комбинации са
надеждни за показване/топ-прогноза/ROI. Заменя разпръснатите правила в
top_pick_with_code(), _TOP_PICK_SAFE_CODES/_is_safe_top_market(),
results_view.ROI_MARKETS, и хардкоднатите банери.

Чист модул: без Flask, без API извиквания. Само данни и функции - лесен за
независимо тестване, не може да счупи нищо само от import. Партида 4
(21.08.2026) добави ЕДИН лек, лениво зареждан sqlite прочит на
trust_derived (виж _get_derived() по-долу) - това НЕ е Flask/API
зависимост и деградира тихо (връща {} - чисто ръчната матрица), ако БД
липсва/е заключена, точно както преди.

Матрицата е попълнена директно от вече направените backtest-и
(PROJECT_STATE.md секции 3 и 5) + диагностиката от 2026-08-10
(diag_calib.py), която потвърди че corners/cards/offsides пазарите
системно подвеждат дори в лиги с реални мач-статистики, не само в
bulgaria2 (където моделите са трениран на 0% покритие). Партида 4
(Граница 3, ARCHITECTURE.md) добавя `trust_derived` - реално измерено
доверие от settled данни - с предимство пред тази ръчна матрица, щом
натрупа достатъчно наблюдения (виж tier()).
"""
import time

# --- Нива на доверие -------------------------------------------------

PROVEN = "proven"        # backtest бие baseline -> публикува се нормално
WEAK = "weak"             # маргинално/недостатъчно тествано -> публикува се с предупреждение
REJECTED = "rejected"     # backtest НЕ бие baseline -> НЕ се публикува
NO_DATA = "no_data"       # моделът е трениран върху празни колони -> НЕ се публикува
UNVERIFIED = "unverified"  # Партида 4 (21.08.2026): лига/пазар без ръчна класификация
                            # И без достатъчно реални данни - показва се, никога не се
                            # препоръчва (виж is_top_pick_eligible). Заменя тихото
                            # падане в DEFAULT_TIER=WEAK за нови/непроверени лиги
                            # (одитът от 21.08 показа england2/germany2 точно в тази
                            # дупка - виж CLAUDE_HANDOFF.md, Граница 3).

_VALID_TIERS = {PROVEN, WEAK, REJECTED, NO_DATA, UNVERIFIED}

# --- Групи пазари ------------------------------------------------------
# Ключът е (лига, група), НЕ (лига, конкретен market_code) - иначе матрицата
# би имала 150+ реда, които никой няма да поддържа.


def market_group(market_code):
    """Мапва конкретен market_code към груба група за целите на матрицата."""
    if market_code is None:
        return "other"
    if market_code in ("home_win", "draw", "away_win"):
        return "1x2"
    if market_code in ("over25", "under25"):
        return "ou25"
    if market_code.startswith(("home_over", "home_under", "away_over",
                                "away_under", "home_clean_sheet",
                                "away_clean_sheet")):
        return "team_total"
    if market_code.startswith("htft"):
        return "htft"
    if market_code.startswith("dc_"):
        return "double_chance"
    if market_code.startswith("btts"):
        return "btts"
    if market_code.startswith("corners"):
        return "corners"
    if market_code.startswith("cards"):
        return "cards"
    if market_code.startswith("offsides"):
        return "offsides"
    return "other"


# --- Матрицата на доверието --------------------------------------------
# Попълнена от PROJECT_STATE.md секции 3 (лиги) и 5 (пазари) + diag_calib.py
# резултатите от 2026-08-10. Пазари, отсъстващи от речника на дадена лига,
# по подразбиране са WEAK (предпазливо, не REJECTED - не значи "лошо",
# значи "недостатъчно тествано изрично").

TRUST_MATRIX = {
    # --- 5-те "пълен пакет" лиги (1X2/HTFT/OU/team_total доказани 4-5/5) ---
    "bulgaria": {
        "1x2": PROVEN, "ou25": PROVEN, "team_total": PROVEN, "htft": PROVEN,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "england": {
        "1x2": PROVEN, "ou25": PROVEN, "team_total": PROVEN, "htft": PROVEN,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "germany": {
        # изключение: O/U 2.5 НЕ бие baseline за Германия (секция 5)
        "1x2": PROVEN, "ou25": REJECTED, "team_total": PROVEN, "htft": PROVEN,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "spain": {
        "1x2": PROVEN, "ou25": PROVEN, "team_total": PROVEN, "htft": PROVEN,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "france": {
        "1x2": PROVEN, "ou25": PROVEN, "team_total": PROVEN, "htft": PROVEN,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },

    # --- Европейски турнири ---
    "champions_league": {
        "1x2": PROVEN, "ou25": REJECTED, "team_total": WEAK, "htft": WEAK,
        "double_chance": WEAK, "btts": WEAK,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "europa_league": {
        # 1X2 маргинален (+2.4pp) - WEAK, не PROVEN
        "1x2": WEAK, "ou25": REJECTED, "team_total": REJECTED, "htft": REJECTED,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "conference_league": {
        # 1X2 изрично тествано и НЕ бие baseline (48.2% vs 49.5%) - REJECTED.
        # ou25/team_total/htft/double_chance/btts НЕ са формално backtest-нати
        # за тази лига (само 1X2 е споменат в PROJECT_STATE секция 5) - WEAK
        # (недостатъчно тествано), не REJECTED (което би значело "тествано
        # и се провали", а не е вярно за тях). corners/cards/offsides остават
        # REJECTED - тази лига е с най-голям обем логнати записи (1652,
        # най-много от всички), силно вероятно е основният източник на
        # свръхувереността, открита в diag_calib.py на 2026-08-10.
        "1x2": REJECTED, "ou25": WEAK, "team_total": WEAK, "htft": WEAK,
        "double_chance": WEAK, "btts": WEAK,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },

    # --- Италия / Португалия (само базов модел) ---
    "italy": {
        "1x2": PROVEN, "ou25": WEAK, "team_total": WEAK, "htft": WEAK,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "portugal": {
        "1x2": PROVEN, "ou25": PROVEN, "team_total": WEAK, "htft": WEAK,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },

    # --- Втори дивизии (базов модел, добавени 2026-08-09) ---
    "france2": {
        "1x2": PROVEN, "ou25": PROVEN, "team_total": WEAK, "htft": WEAK,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "spain2": {
        # 1X2 маргинален/вероятно шум (+0.9pp) - WEAK
        "1x2": WEAK, "ou25": PROVEN, "team_total": WEAK, "htft": WEAK,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "italy2": {
        "1x2": PROVEN, "ou25": PROVEN, "team_total": WEAK, "htft": WEAK,
        "double_chance": WEAK, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "portugal2": {
        # НИТО ЕДИН пазар не бие baseline - оставена жива по изрично
        # желание на потребителя, но всичко REJECTED в матрицата (банерът
        # на страницата, не тази матрица, показва предупреждението)
        "1x2": REJECTED, "ou25": REJECTED, "team_total": REJECTED, "htft": REJECTED,
        "double_chance": REJECTED, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },
    "bulgaria2": {
        # 1X2 доказано (+3.7pp), OU слабо (+1.5pp)
        "1x2": PROVEN, "ou25": WEAK, "team_total": WEAK, "htft": WEAK,
        "double_chance": WEAK, "btts": REJECTED,
        # 0% match-statistics покритие от API-то -> моделите са трениран
        # на празни колони, структурно невалидни, не просто статистически
        # слаби
        "corners": NO_DATA, "cards": NO_DATA, "offsides": NO_DATA,
    },
}

# Пазарни групи, изключени от избора за ТОП прогноза по БИЗНЕС причина
# (не заради точност) - вижте PROJECT_STATE секция 5: "Double Chance
# изключен изрично от избора за топ прогноза" - двойните шансове плащат
# твърде малко, за да са полезна "топ" препоръка, дори когато са точни.
_TOP_PICK_EXCLUDED_GROUPS = {"double_chance"}

DEFAULT_TIER = WEAK  # позната лига, непозната група в матрицата -> предпазливо, не рухва
                      # (тесен ръб случай - непозната ЛИГА изобщо връща UNVERIFIED, виж tier())

# --- Партида 4 (21.08.2026): реално измерено доверие --------------------
# `trust_derived` (system_tracker.py) се пълни нощно от build_trust_derived.py
# от реални settled публикувани прогнози - виж докстринга на скрипта за пълна
# методология (Бернули baseline, MIN_N=20, MARGIN=0.02 Brier разлика).
# tier() го чете тук, с ръчната TRUST_MATRIX като резерва, докато няма
# достатъчно данни (derived статус "unverified") - точно поведението, описано
# в ARCHITECTURE.md, Граница 3: "prediction_policy чете нея; ръчната матрица
# остава резерва под минимален брой наблюдения."
#
# Съзнателно НЕ внасяме system_tracker (БД) с твърд import на ниво модул -
# лениво, вътре в _get_derived(), за да не гърми самият import на този модул,
# ако БД файлът липсва/е заключен (напр. unit тест без БД context, точно
# случаят, заради който модулът е бил направен "чист" в началото). TTL=60 сек
# е достатъчен да покрие всички tier() извиквания за едно смятане на един мач
# (десетина кандидата), без да отваря нова sqlite връзка при всеки едничен
# candidate - но пак реагира до минута след ново нощно пускане на скрипта.
_DERIVED_CACHE_TTL = 60
_derived_cache = {"data": {}, "loaded_at": 0.0}

USE_DERIVED_TRUST = True  # флаг за връщане - смени на False за пълно връщане
                          # към старата чиста-ръчна матрица, без рестарт на кода


def _get_derived():
    if not USE_DERIVED_TRUST:
        return {}
    now_ts = time.time()
    if now_ts - _derived_cache["loaded_at"] > _DERIVED_CACHE_TTL:
        try:
            import system_tracker as st
            _derived_cache["data"] = st.get_all_trust_derived()
        except Exception:
            pass  # БД временно недостъпна/липсва - просто продължи с ръчната матрица
        _derived_cache["loaded_at"] = now_ts
    return _derived_cache["data"]


# --- Публично API --------------------------------------------------------

def tier(league, market_code):
    """Връща нивото на доверие (PROVEN/WEAK/REJECTED/NO_DATA/UNVERIFIED) за
    дадена комбинация лига+пазар. Реално измерените данни (trust_derived)
    имат предимство пред ръчната матрица, ако имат достатъчно наблюдения
    (derived статус != UNVERIFIED) - "измерване срещу правило" (Граница 3).

    USE_DERIVED_TRUST=False връща ТОЧНОТО старо (преди Партида 4) поведение,
    вкл. непозната лига -> DEFAULT_TIER (WEAK), не само пропуска derived
    четенето - флагът е пълно връщане назад, не частично."""
    grp = market_group(market_code)
    if USE_DERIVED_TRUST:
        derived = _get_derived().get((league, grp))
        if derived and derived["status"] != UNVERIFIED:
            return derived["status"]
    league_row = TRUST_MATRIX.get(league)
    if league_row is None:
        return UNVERIFIED if USE_DERIVED_TRUST else DEFAULT_TIER
    return league_row.get(grp, DEFAULT_TIER)


def is_proven(league, market_code):
    """Фаза L.3 (20.08.2026): по-строго от is_publishable() - само PROVEN,
    без WEAK fallback. Използва се от /value (value_view.py), борд, който
    твърди конкретен количествен edge% ("тук има стойност"), не просто
    показва прогноза с предупреждение както is_publishable() позволява за
    WEAK пазари. Комбинация от "недостатъчно тествано" (WEAK) И "твърдим
    конкретен процент печалба" би подвела - затова по-високата летва тук."""
    return tier(league, market_code) == PROVEN


def is_publishable(league, market_code):
    """Дали изобщо трябва да се показва на потребителя (в каквато и да е
    форма - основен ред, разгъната секция, ROI таблица). REJECTED и
    NO_DATA пазари НЕ се показват никъде - показването на "94.8%
    сигурност" за пазар, който реално познава 63%, е подвеждащо, независимо
    дали е "само в разгънатата секция". UNVERIFIED (Партида 4) Е
    publishable - "показва се" по изричния текст в ARCHITECTURE.md,
    просто никога не е top-pick eligible (виж is_top_pick_eligible)."""
    t = tier(league, market_code)
    return t in (PROVEN, WEAK, UNVERIFIED)


def is_top_pick_eligible(league, market_code, allow_weak=False):
    """Дали дадена прогноза може да бъде избрана за ГЛАВНАТА/топ прогноза
    на мача. По-строго от is_publishable: по подразбиране изисква PROVEN
    И групата да не е изключена по бизнес причина (напр. двойни шансове -
    точни, но плащат твърде малко).

    allow_weak=True разхлабва изискването до PROVEN-или-WEAK - използва се
    само като fallback ниво, когато лига/пазар комбинация няма НИТО ЕДИН
    PROVEN кандидат (напр. europa_league, conference_league), за да не
    остане мач без никаква прогноза.

    UNVERIFIED (Партида 4) НИКОГА не е eligible тук, дори с allow_weak=True -
    ok_tiers е винаги PROVEN или PROVEN+WEAK, никога не включва UNVERIFIED.
    Точно това реализира "показва се, никога не се препоръчва" от
    ARCHITECTURE.md - живият модел път (compute_grouped_markets,
    full_fallback=True в pick_selection._apply_rules) пак ще покаже
    прогноза за такъв мач (никога не оставя мач без нищо), но НЕ през тази
    "одобрена" пътека - същият механизъм, който вече важи за REJECTED
    (напр. portugal2)."""
    ok_tiers = (PROVEN, WEAK) if allow_weak else (PROVEN,)
    if tier(league, market_code) not in ok_tiers:
        return False
    if market_group(market_code) in _TOP_PICK_EXCLUDED_GROUPS:
        return False
    return True


def fair_odds(prob_pct):
    """Честен коефициент от вероятност в проценти (0-100)."""
    if prob_pct is None or prob_pct <= 0:
        return None
    return round(100.0 / prob_pct, 3)


def edge_pct(prob_pct, market_odds):
    """Колко повече плаща пазарът спрямо нашата честна оценка, в %.
    Положително = пазарът плаща повече от нашата вероятност предполага."""
    if not prob_pct or not market_odds:
        return None
    fo = fair_odds(prob_pct)
    if not fo:
        return None
    return round((market_odds / fo - 1) * 100, 1)


def calibrate(prob_pct, league, market_code):
    """Заглушка за Фаза E. Днес връща входа непроменен - диагностиката от
    2026-08-10 показа, че свръхувереността е концентрирана в REJECTED/
    NO_DATA пазари (corners/cards), не в PROVEN пазарите, затова
    калибрация все още НЕ Е оправдана. Закачена навсякъде отсега, за да
    може да се включи на едно място, ако бъдещи данни го оправдаят."""
    return prob_pct
