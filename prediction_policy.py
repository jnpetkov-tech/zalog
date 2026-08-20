"""
prediction_policy.py

ЕДИНСТВЕН ИЗТОЧНИК НА ИСТИНАТА за това кои (лига, пазар) комбинации са
надеждни за показване/топ-прогноза/ROI. Заменя разпръснатите правила в
top_pick_with_code(), _TOP_PICK_SAFE_CODES/_is_safe_top_market(),
results_view.ROI_MARKETS, и хардкоднатите банери.

Чист модул: без Flask, без БД връзки, без API извиквания. Само данни и
функции. Затова е тривиален за независимо тестване и не може да счупи
нищо само от import.

Матрицата е попълнена директно от вече направените backtest-и
(PROJECT_STATE.md секции 3 и 5) + диагностиката от 2026-08-10
(diag_calib.py), която потвърди че corners/cards/offsides пазарите
системно подвеждат дори в лиги с реални мач-статистики, не само в
bulgaria2 (където моделите са трениран на 0% покритие).
"""

# --- Нива на доверие -------------------------------------------------

PROVEN = "proven"        # backtest бие baseline -> публикува се нормално
WEAK = "weak"             # маргинално/недостатъчно тествано -> публикува се с предупреждение
REJECTED = "rejected"     # backtest НЕ бие baseline -> НЕ се публикува
NO_DATA = "no_data"       # моделът е трениран върху празни колони -> НЕ се публикува

_VALID_TIERS = {PROVEN, WEAK, REJECTED, NO_DATA}

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

DEFAULT_TIER = WEAK  # лига/група извън матрицата -> предпазливо, не рухва


# --- Публично API --------------------------------------------------------

def tier(league, market_code):
    """Връща нивото на доверие (PROVEN/WEAK/REJECTED/NO_DATA) за дадена
    комбинация лига+пазар."""
    grp = market_group(market_code)
    league_row = TRUST_MATRIX.get(league)
    if league_row is None:
        return DEFAULT_TIER
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
    дали е "само в разгънатата секция"."""
    t = tier(league, market_code)
    return t in (PROVEN, WEAK)


def is_top_pick_eligible(league, market_code, allow_weak=False):
    """Дали дадена прогноза може да бъде избрана за ГЛАВНАТА/топ прогноза
    на мача. По-строго от is_publishable: по подразбиране изисква PROVEN
    И групата да не е изключена по бизнес причина (напр. двойни шансове -
    точни, но плащат твърде малко).

    allow_weak=True разхлабва изискването до PROVEN-или-WEAK - използва се
    само като fallback ниво, когато лига/пазар комбинация няма НИТО ЕДИН
    PROVEN кандидат (напр. europa_league, conference_league), за да не
    остане мач без никаква прогноза."""
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
