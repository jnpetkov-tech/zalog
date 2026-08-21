import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old_func = '''def top_pick_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=None):
    max_g = 10
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    home_win = np.sum(np.tril(pm, -1))
    draw = np.sum(np.diag(pm))
    away_win = np.sum(np.triu(pm, 1))
    _, ou_p = fl.btts_ou_probs(lam, mu)
    extra = fl.extra_markets_probs(lam, mu)
    best_htft = max(ht_ft_probs.items(), key=lambda x: x[1])

    used_market = False
    if market_odds and market_odds.get("home_win") and market_odds.get("draw") and market_odds.get("away_win"):
        try:
            mh, md, ma = devig_1x2(market_odds["home_win"], market_odds["draw"], market_odds["away_win"])
            home_win = BLEND_WEIGHT * mh + (1 - BLEND_WEIGHT) * home_win
            draw = BLEND_WEIGHT * md + (1 - BLEND_WEIGHT) * draw
            away_win = BLEND_WEIGHT * ma + (1 - BLEND_WEIGHT) * away_win
            used_market = True
        except (ZeroDivisionError, TypeError):
            pass
    if market_odds and market_odds.get("over25") and market_odds.get("under25"):
        try:
            mo, mund = devig_ou(market_odds["over25"], market_odds["under25"])
            ou_p = BLEND_WEIGHT * mo + (1 - BLEND_WEIGHT) * ou_p
            used_market = True
        except (ZeroDivisionError, TypeError):
            pass

    home_cy, away_cy = to_cyrillic(home), to_cyrillic(away)
    candidates = [
        (f"{home_cy} печели", home_win, "home_win"),
        ("Равен", draw, "draw"),
        (f"{away_cy} печели", away_win, "away_win"),
        ("Над 2.5 гола", ou_p, "over25"),
        ("Под 2.5 гола", 1 - ou_p, "under25"),
        (f"{home_cy} над 1.5 гола", extra["home_over15"], "home_over15"),
        (f"{home_cy} под 1.5 гола", 1 - extra["home_over15"], "home_under15"),
        (f"Резултат почивка/край {best_htft[0]}", best_htft[1], f"htft:{best_htft[0]}"),
    ]
    pool = [c for c in candidates if policy.is_top_pick_eligible(league, c[2])]
    if not pool:
        pool = [c for c in candidates if policy.is_top_pick_eligible(league, c[2], allow_weak=True)]
    if not pool:
        pool = candidates
    label, pct, code = max(pool, key=lambda x: x[1])
    return label, pct * 100, code, used_market'''

new_func = '''def _build_pick_pool(lam, mu, home, away, ht_ft_probs, league, market_odds=None):
    """Общ helper: изгражда eligible candidates pool (0-1 скала) + used_market.
    Извлечено от top_pick_with_code() (Фаза F3) без промяна в логиката, за
    да го ползват и top_pick_with_code() (един pick, за логовете в
    compute_grouped_markets) и top_picks_with_code() (топ N, за /daily) -
    без разминаване между двата пътя."""
    max_g = 10
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    home_win = np.sum(np.tril(pm, -1))
    draw = np.sum(np.diag(pm))
    away_win = np.sum(np.triu(pm, 1))
    _, ou_p = fl.btts_ou_probs(lam, mu)
    extra = fl.extra_markets_probs(lam, mu)
    best_htft = max(ht_ft_probs.items(), key=lambda x: x[1])

    used_market = False
    if market_odds and market_odds.get("home_win") and market_odds.get("draw") and market_odds.get("away_win"):
        try:
            mh, md, ma = devig_1x2(market_odds["home_win"], market_odds["draw"], market_odds["away_win"])
            home_win = BLEND_WEIGHT * mh + (1 - BLEND_WEIGHT) * home_win
            draw = BLEND_WEIGHT * md + (1 - BLEND_WEIGHT) * draw
            away_win = BLEND_WEIGHT * ma + (1 - BLEND_WEIGHT) * away_win
            used_market = True
        except (ZeroDivisionError, TypeError):
            pass
    if market_odds and market_odds.get("over25") and market_odds.get("under25"):
        try:
            mo, mund = devig_ou(market_odds["over25"], market_odds["under25"])
            ou_p = BLEND_WEIGHT * mo + (1 - BLEND_WEIGHT) * ou_p
            used_market = True
        except (ZeroDivisionError, TypeError):
            pass

    home_cy, away_cy = to_cyrillic(home), to_cyrillic(away)
    candidates = [
        (f"{home_cy} печели", home_win, "home_win"),
        ("Равен", draw, "draw"),
        (f"{away_cy} печели", away_win, "away_win"),
        ("Над 2.5 гола", ou_p, "over25"),
        ("Под 2.5 гола", 1 - ou_p, "under25"),
        (f"{home_cy} над 1.5 гола", extra["home_over15"], "home_over15"),
        (f"{home_cy} под 1.5 гола", 1 - extra["home_over15"], "home_under15"),
        (f"Резултат почивка/край {best_htft[0]}", best_htft[1], f"htft:{best_htft[0]}"),
    ]
    pool = [c for c in candidates if policy.is_top_pick_eligible(league, c[2])]
    if not pool:
        pool = [c for c in candidates if policy.is_top_pick_eligible(league, c[2], allow_weak=True)]
    if not pool:
        pool = candidates
    return pool, used_market


def top_pick_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=None):
    pool, used_market = _build_pick_pool(lam, mu, home, away, ht_ft_probs, league, market_odds)
    label, pct, code = max(pool, key=lambda x: x[1])
    return label, pct * 100, code, used_market


_COMPLEMENTARY_PAIRS = [("over25", "under25"), ("home_over15", "home_under15")]


def top_picks_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=None, n=3):
    """НОВО (Фаза F3): топ N picks вместо форсирано само 1 - виж
    claude/daily_value_redesign_2026-08-10.md т.2. Дедупликира допълващи
    двойки (Над/Под 2.5 и т.н., p и 1-p носят еднаква информация) - пази
    по-силната страна, за да не хаби слот от N-те без нова информация."""
    pool, used_market = _build_pick_pool(lam, mu, home, away, ht_ft_probs, league, market_odds)
    by_code = {c[2]: c for c in pool}
    exclude = set()
    for a, b in _COMPLEMENTARY_PAIRS:
        if a in by_code and b in by_code:
            exclude.add(a if by_code[a][1] < by_code[b][1] else b)
    deduped = [c for c in pool if c[2] not in exclude]
    ranked = sorted(deduped, key=lambda x: x[1], reverse=True)[:n]
    return [(label, pct * 100, code) for label, pct, code in ranked], used_market'''

assert content.count(old_func) == 1, f"top_pick_with_code anchor count: {content.count(old_func)}"
content = content.replace(old_func, new_func, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - top_picks_with_code() добавена (top_pick_with_code() рефакторирана, поведението непроменено)")
