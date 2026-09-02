"""evaluation.py - Фаза I.2 (11.08.2026).

Честни метрики за представянето на системата - смятани САМО върху
публикуваните прогнози (реконструирани със същите правила, каквито вижда
потребителят на витрината, чрез pick_selection.rank_logged_rows() от
Фаза I.1), не върху суровия predictions_log (който логва всеки възможен
изход на всеки пазар - виж opus_review_2026-08-11.md раздел 1 защо
суровите числа са безсмислени: 1X2 винаги дава точно 33.3%, двойните
пазари точно 50.0%, двоен шанс точно 66.7%, независимо от качеството на
модела).

Чист модул: работи върху вече заредени редове (списък от dict-ове/
sqlite3.Row обекти), без БД връзка вътре в себе си - викащият подава rows
(напр. от system_tracker) и policy модула (prediction_policy).
"""
import math
from datetime import datetime, timedelta

import pick_selection as ps

SETTLED = ("won", "lost")

# Същите бандове, каквито вече ползва diag_full_review.py (Q4) - за да
# може човек директно да сравни резултата с диагностиката.
DEFAULT_BANDS = [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]


def published_picks(rows, policy):
    """Групира rows по fixture_id (реалният API-Football fixture_id е
    глобално уникален - same convention като results_view.group_by_match()
    и system_check()), за всеки мач избира ЕДИНСТВЕНАТА прогноза, която
    реално бихме показали на витрината (pick_selection.rank_logged_rows(),
    n=1 - същите правила като index_home() от Фаза H.1/I.1).

    Връща плосък списък от row-подобни обекти - по един на мач, само за
    мачове с publishable избор. Мач без нито един eligible ред (напр. само
    corners/cards логнати за bulgaria2) просто не влиза в списъка - точно
    като на началната страница, не показваме боклук само за да имаме число."""
    groups = {}
    for r in rows:
        groups.setdefault(r["fixture_id"], []).append(r)

    picks = []
    for fixture_id, group_rows in groups.items():
        league = group_rows[0]["league"]
        ranked = ps.rank_logged_rows(group_rows, league, policy, n=1)
        if ranked:
            picks.append(ranked[0])
    return picks


def _settled(picks):
    """Само мачове с известен изход - изключва pending/no_data. Именно
    тези настоящи ~51 приключили мача (виж PROJECT_STATE Б.3/Фаза Б.3 в
    ACTION_PLAN.md) са единствената реална извадка, с която разполагаме."""
    return [p for p in picks if p["status"] in SETTLED]


def calibration_curve(picks, bands=None):
    """[{"lo","hi","n","promised","actual","diff"}] само за settled
    публикувани прогнози. Празните бандове се пропускат (не се показва
    n=0 ред)."""
    bands = bands or DEFAULT_BANDS
    settled = _settled(picks)
    out = []
    for lo, hi in bands:
        band_picks = [p for p in settled if lo <= (p["pick_pct"] or 0) < hi]
        n = len(band_picks)
        if not n:
            continue
        promised = sum((p["pick_pct"] or 0) for p in band_picks) / n
        won = sum(1 for p in band_picks if p["status"] == "won")
        actual = won / n * 100.0
        out.append({"lo": lo, "hi": hi, "n": n, "promised": promised,
                     "actual": actual, "diff": actual - promised})
    return out


def brier_score(picks):
    """mean((prob - outcome)^2) само върху settled публикувани прогнози.
    Опростена (chosen-class) версия - вижда само вероятността на
    ИЗБРАНИЯ изход, не пълното разпределение на пазара (predictions_log
    не пази пълното разпределение свързано с една публикувана прогноза
    компактно - виж бележката в ACTION_PLAN.md I.2). По-ниско = по-добре.
    Връща (score, n); (None, 0) ако няма settled прогнози."""
    settled = _settled(picks)
    if not settled:
        return None, 0
    total = 0.0
    for p in settled:
        prob = (p["pick_pct"] or 0) / 100.0
        outcome = 1.0 if p["status"] == "won" else 0.0
        total += (prob - outcome) ** 2
    return total / len(settled), len(settled)


def weekly_brier(rows, policy, n_weeks=8):
    """Фаза I.4 (20.08.2026): Brier score по седмици върху ПУБЛИКУВАНИ
    прогнози (същата методология като brier_score() - виж бележката там
    защо суровият predictions_log е неизползваем). Седмица = понеделник
    старт, като weekly_roi() в results_view.py. Цел: да се вижда дали
    калибрацията се подобрява или влошава във времето, не само едно общо
    число за целия период. Връща последните n_weeks непразни седмици,
    най-старата първа (за хронологична графика). Празни списъци, ако няма
    settled публикувани прогнози."""
    picks = published_picks(rows, policy)
    settled = _settled(picks)
    buckets = {}
    for p in settled:
        try:
            d = datetime.strptime((p["match_date"] or "")[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        wk_start = d - timedelta(days=d.weekday())
        buckets.setdefault(wk_start, []).append(p)
    out = []
    for wk, items in sorted(buckets.items()):
        score, n = brier_score(items)
        if score is None:
            continue
        out.append({"week": wk.strftime("%d.%m"), "brier": score, "n": n})
    return out[-n_weeks:]


def log_loss(picks, eps=1e-9):
    """Логаритмична загуба, същата (chosen-class) опростена постановка
    като brier_score(). По-ниско = по-добре. Връща (score, n);
    (None, 0) ако няма settled прогнози."""
    settled = _settled(picks)
    if not settled:
        return None, 0
    total = 0.0
    for p in settled:
        prob = min(1 - eps, max(eps, (p["pick_pct"] or 0) / 100.0))
        outcome = 1.0 if p["status"] == "won" else 0.0
        total += -(outcome * math.log(prob) + (1 - outcome) * math.log(1 - prob))
    return total / len(settled), len(settled)


def roi(picks):
    """ROI само за settled публикувани прогнози С реален market_odds.
    Печалба при залог от 1 единица на всяка (не Kelly - просто "какво би
    станало, ако бяхме заложили еднакво на всяка публикувана прогноза").
    Връща (roi_pct, n); (None, 0) ако няма нито един ред с коефициент."""
    eligible = [p for p in _settled(picks) if p["market_odds"]]
    if not eligible:
        return None, 0
    stake = len(eligible)
    ret = sum((p["market_odds"] if p["status"] == "won" else 0.0) for p in eligible)
    return (ret - stake) / stake * 100.0, len(eligible)


def roi_confidence_interval(eligible):
    """Спешна поправка (01.09.2026, преглед на Дака): ROI без интервал на
    несигурност е подвеждащ - +4.7% при n=308 звучи като находка, но е в
    рамките на шума. `eligible`: същият списък settled публикувани редове
    С market_odds, който вече строи `roi()`/`summary()` (не пресмятаме
    отделен набор - едно определение за "кои залози броим").

    Печалба на залог: (market_odds - 1) при won, -1 при lost (същата
    формула като `roi()`, само по едно число на залог вместо сумарно).
    Wald 95% интервал: mean ± 1.96 * SE, SE = извадкова стандартна грешка
    на средното (sample sd / sqrt(n), n-1 знаменател - обичайната
    несмесена оценка). Връща None ако n < 2 (няма как да се смята
    отклонение от една точка)."""
    n = len(eligible)
    if n < 2:
        return None
    profits = [(p["market_odds"] - 1.0) if p["status"] == "won" else -1.0 for p in eligible]
    mean = sum(profits) / n
    var = sum((x - mean) ** 2 for x in profits) / (n - 1)
    se = (var / n) ** 0.5
    return {
        "mean_pct": mean * 100.0, "se_pct": se * 100.0,
        "ci_lo_pct": (mean - 1.96 * se) * 100.0, "ci_hi_pct": (mean + 1.96 * se) * 100.0,
        "n": n, "contains_zero": (mean - 1.96 * se) <= 0 <= (mean + 1.96 * se),
    }


def summary(rows, policy, bands=None):
    """Всичко наведнъж - за витрините (началната страница, /results).
    n е винаги видим до всяко число - никога скрит зад проценти без
    контекст (виж Б.3/opus_review за защо малката извадка е важна)."""
    picks = published_picks(rows, policy)
    settled = _settled(picks)
    n_settled = len(settled)
    promised_avg = (sum((p["pick_pct"] or 0) for p in settled) / n_settled) if n_settled else None
    won = sum(1 for p in settled if p["status"] == "won")
    actual_pct = (won / n_settled * 100.0) if n_settled else None

    brier, brier_n = brier_score(picks)
    ll, ll_n = log_loss(picks)
    roi_pct, roi_n = roi(picks)
    # Фаза I.3 (остатък, 20.08.2026): "Чиста печалба" и "Среден коеф." на
    # /results смятаха по суровите редове от predictions_log (всеки логнат
    # пазар, не само публикуваната прогноза) - не пасваха на roi_pct горе,
    # който вече е честен (виж бележката в results_view.py преди тази
    # промяна). Същият eligible набор като roi() - settled публикувани
    # прогнози с реален market_odds.
    roi_eligible = [p for p in settled if p["market_odds"]]
    profit = (sum((p["market_odds"] if p["status"] == "won" else 0.0) - 1.0 for p in roi_eligible)
              if roi_eligible else None)
    avg_odds = (sum(p["market_odds"] for p in roi_eligible) / len(roi_eligible)
                if roi_eligible else None)
    roi_ci = roi_confidence_interval(roi_eligible)

    return {
        "n_published": len(picks),
        "n_settled": n_settled,
        "n_won": won,
        "n_lost": n_settled - won,
        "promised_avg": promised_avg,
        "actual_pct": actual_pct,
        "calibration": calibration_curve(picks, bands),
        "brier": brier, "brier_n": brier_n,
        "log_loss": ll, "log_loss_n": ll_n,
        "roi": roi_pct, "roi_n": roi_n,
        "profit": profit, "avg_odds": avg_odds, "roi_ci": roi_ci,
    }


def summary_priced_only(rows, policy, bands=None):
    """Вариант на summary() само за /prognozi (публичната витрина) -
    Дака поиска (02.09.2026) четирите показани числа (брой, калибрация,
    ROI, печалба) да минават през ЕДНО n, вместо calibration да показва
    n_settled а ROI/печалба по-малко n (объркващо разминаване на едно
    табло). Разлика от summary(): всичко тук се смята само върху
    roi_eligible (settled публикувани топ-прогнози С реален
    market_odds), не върху всички settled. summary() (за /results,
    админ одит) остава непроменена нарочно."""
    picks = published_picks(rows, policy)
    settled = _settled(picks)
    roi_eligible = [p for p in settled if p["market_odds"]]
    n = len(roi_eligible)
    promised_avg = (sum((p["pick_pct"] or 0) for p in roi_eligible) / n) if n else None
    won = sum(1 for p in roi_eligible if p["status"] == "won")
    actual_pct = (won / n * 100.0) if n else None
    roi_pct, roi_n = roi(picks)
    profit = (sum((p["market_odds"] if p["status"] == "won" else 0.0) - 1.0
                  for p in roi_eligible) if roi_eligible else None)
    avg_odds = (sum(p["market_odds"] for p in roi_eligible) / n) if n else None
    roi_ci = roi_confidence_interval(roi_eligible)
    return {
        "n_settled": n, "n_won": won, "n_lost": n - won,
        "promised_avg": promised_avg, "actual_pct": actual_pct,
        "calibration": calibration_curve(roi_eligible, bands),
        "roi": roi_pct, "roi_n": roi_n,
        "profit": profit, "avg_odds": avg_odds, "roi_ci": roi_ci,
    }
