"""pick_selection.py - Фаза I.1 (11.08.2026).

Единствен източник на истината за "коя е топ прогнозата", когато вече
знаем кандидатите и лигата. Преди тази промяна логиката живееше
разпръсната на няколко места (top_pick_with_code()/_build_pick_pool() в
match_predictor_app.py за живия модел път, плюс отделна inline версия в
index_home() след Фаза H.1) и се разминаваше при всяка промяна - точно
проблемът, описан в PROJECT_STATE.md раздел 11: "еднаквата логика,
копирана на няколко места, се разминава по различен начин всеки път".

Чист модул: без Flask, без БД, без API извиквания, без импорт на
prediction_policy (за да няма кръгов импорт и за да е лесен за unit тест
без цялото приложение). Извикващият подава policy модула като параметър.

ЗАБЕЛЕЖКА за results_view.group_by_match() и /system_check (11.08.2026):
те все още НЕ минават през този модул. Тяхната fallback семантика е малко
по-различна (винаги показват top_pred за мача, дори неелигибъл пазар -
разумно за "какво реално стана с мача" контекст) и нямат MAX_PUBLISHABLE_PCT
таван. Обединяването им е отделна продуктова decision (променя видимото
поведение на /results и /system_check), не чиста техническа рефакторинг -
виж claude/ACTION_PLAN.md Фаза I.1.
"""

MAX_PUBLISHABLE_PCT = 95.0  # >= това е модел артефакт, не увереност (opus_review раздел 1)

# Поправка 02.09.2026 (Дака одобри - validation/ev_guard_impact_20260902.md
# симулира точно тази промяна, validation/ev_guard_applied_20260902.md
# документира прилагането): implied EV над това не вярваме на модела си -
# същия праг и същата формула като match_predictor_app.MAX_TRUSTWORTHY_EV
# (там 0.40 като дроб, тук 40.0 като %). Прилага се само в rank_logged_rows()
# (top_pick_for_match пътя) - rank_candidates() (живият /daily модел път)
# няма market_odds/our_fair_odds в кандидатите си (label, prob, code) и
# остава непипнат.
MAX_TRUSTWORTHY_EV = 40.0

_COMPLEMENTARY_PAIRS = [("over25", "under25"), ("home_over15", "home_under15")]


def _row_ev_pct(row):
    """implied EV% = (market_odds/our_fair_odds - 1) * 100 - същата формула
    като match_predictor_app.py и validation/ev_threshold_backtest.py.
    None, ако редът няма двете стойности (напр. predictions_snapshot
    редове от живия /prognozi списък - нямат market_odds/our_fair_odds
    изобщо, само fair_odds/ev с друг смисъл) - guard-ът не спъва избор,
    за който EV не е смятаем, вместо да гадае."""
    try:
        odds, fair = row["market_odds"], row["our_fair_odds"]
    except (KeyError, IndexError):
        return None
    if not odds or not fair or fair <= 0:
        return None
    return (odds / fair - 1) * 100.0


def _eligible(items, league, policy, get_pct, get_code, allow_weak, get_ev=None):
    return [it for it in items
            if get_pct(it) < MAX_PUBLISHABLE_PCT
            and policy.is_top_pick_eligible(league, get_code(it), allow_weak=allow_weak)
            and (get_ev is None or get_ev(it) is None or get_ev(it) <= MAX_TRUSTWORTHY_EV)]


def _dedupe_complementary(pool, get_pct, get_code):
    """Маха по-слабата страна на допълваща двойка (Над/Под 2.5 и т.н.) -
    p и 1-p носят еднаква информация, не хаби слот от топ N с нея.
    Никога не маха глобалния максимум: ако елемент е max в целия pool,
    той е >= партньора си по двойка, следователно никога не е тази,
    която се маха тук (важно за n=1 извиквания - виж тестовете)."""
    by_code = {get_code(it): it for it in pool}
    exclude = set()
    for a, b in _COMPLEMENTARY_PAIRS:
        if a in by_code and b in by_code:
            exclude.add(a if get_pct(by_code[a]) < get_pct(by_code[b]) else b)
    return [it for it in pool if get_code(it) not in exclude]


def _apply_rules(items, league, policy, get_pct, get_code, n, full_fallback, get_ev=None):
    """PROVEN -> allow_weak=True -> (по избор) пълен неfiltриран списък -> [].

    full_fallback=True възпроизвежда старото поведение на
    top_pick_with_code()/_build_pick_pool(): "никога не оставяй мач без
    прогноза" - за живия модел път (/daily, compute_grouped_markets),
    където кандидатите винаги идват от реално изчислени вероятности.

    full_fallback=False спира на WEAK - поведението на index_home() от
    Фаза H.1: ако нищо не е eligible, връща [] и викащият решава да
    пропусне мача изцяло, вместо да покаже нещо неелигибъл на "витрината".

    get_ev: незадължителен, EV guard (виж MAX_TRUSTWORTHY_EV по-горе) -
    прилага се на всеки етап (PROVEN и WEAK), НЕ и на full_fallback капания
    списък (капанът е "никога не оставяй мач без нищо", последна инстанция,
    не участва в EV доверието)."""
    pool = _eligible(items, league, policy, get_pct, get_code, allow_weak=False, get_ev=get_ev)
    if not pool:
        pool = _eligible(items, league, policy, get_pct, get_code, allow_weak=True, get_ev=get_ev)
    if not pool and full_fallback:
        capped = [it for it in items if get_pct(it) < MAX_PUBLISHABLE_PCT]
        pool = capped or list(items)
    if not pool:
        return []
    deduped = _dedupe_complementary(pool, get_pct, get_code)
    return sorted(deduped, key=get_pct, reverse=True)[:n]


def rank_candidates(candidates, league, policy, n=3):
    """candidates: [(label, prob_0_1, code)]. За ЖИВИЯ модел път - заменя
    старата логика в top_picks_with_code()/_build_pick_pool(). Пази
    старото "никога не оставяй мач без прогноза" поведение на /daily.

    НОВО спрямо старата логика (съзнателна унификация, Фаза I.1): вече
    отхвърля >=MAX_PUBLISHABLE_PCT навсякъде, не само на началната
    страница както след Фаза H.1 - виж claude/ACTION_PLAN.md Фаза I.1."""
    ranked = _apply_rules(
        candidates, league, policy,
        get_pct=lambda c: c[1] * 100,
        get_code=lambda c: c[2],
        n=n, full_fallback=True,
    )
    return [(label, prob * 100, code) for label, prob, code in ranked]


def rank_logged_rows(rows, league, policy, n=3):
    """rows: dict-ове от predictions_log (pick_pct вече е 0-100 скала,
    market_code е ключ за пазара). За index_home() - Фаза H.1 семантика:
    PROVEN -> WEAK -> ако пак празно, връща [] (мачът отпада, не се
    показва боклук).

    02.09.2026: EV guard (MAX_TRUSTWORTHY_EV) вече включен тук - виж
    validation/ev_guard_applied_20260902.md."""
    return _apply_rules(
        rows, league, policy,
        get_pct=lambda r: r["pick_pct"] or 0,
        get_code=lambda r: r["market_code"],
        get_ev=_row_ev_pct,
        n=n, full_fallback=False,
    )


def top_pick_for_match(rows, league, policy):
    """rows: predictions_log dict-ове за ЕДИН мач (pick_pct 0-100 скала,
    market_code ключ). Единствената функция за "коя е прогнозата за този
    мач" - Стъпка 1 от PREUSTROYSTVO.md (25.08.2026), обединява /daily
    (rank_candidates), началната страница (rank_logged_rows) и /results +
    /system_check в едно място. Преди това /results и /system_check имаха
    трета, отделна имплементация: ръчен max() с fallback до буквално всеки
    логнат пазар за мача, включително REJECTED, без policy филтър изобщо -
    виж validation/audit_misleading_selection_20260825.md, Находка 2+3.

    Същата PROVEN -> WEAK семантика като rank_logged_rows(): връща None,
    ако нищо публикуемо съществува за мача, вместо да пада до недоверен
    пазар - викащият трябва да покаже това изрично ("няма доверена
    прогноза"), не да измисля една."""
    ranked = rank_logged_rows(rows, league, policy, n=1)
    return ranked[0] if ranked else None
