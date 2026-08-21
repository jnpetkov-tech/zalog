
import ast

with open("match_predictor_app.py", "r") as f:
    content = f.read()

# --- Патч 1: import ---
old1 = '''import bets_tracker as bt
import player_props as pp
import system_tracker as st'''
new1 = '''import bets_tracker as bt
import player_props as pp
import system_tracker as st
import prediction_policy as policy'''
assert content.count(old1) == 1, f"anchor1 count={content.count(old1)}"
content = content.replace(old1, new1)

# --- Патч 2: top_pick_with_code() дефиниция ---
old2 = '''def top_pick_with_code(lam, mu, home, away, ht_ft_probs, market_odds=None):
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
    label, pct, code = max(candidates, key=lambda x: x[1])
    return label, pct * 100, code, used_market'''
new2 = '''def top_pick_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=None):
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
assert content.count(old2) == 1, f"anchor2 count={content.count(old2)}"
content = content.replace(old2, new2)

# --- Патч 3: извикване #1 (compute_grouped_markets) ---
old3 = '''    top_label, top_pct, top_code, _ = top_pick_with_code(lam, mu, home, away, ht_ft_probs, market_odds=None)'''
new3 = '''    top_label, top_pct, top_code, _ = top_pick_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=None)'''
assert content.count(old3) == 1, f"anchor3 count={content.count(old3)}"
content = content.replace(old3, new3)

# --- Патч 4: извикване #2 (daily route) ---
old4 = '''        pick, pct, code, used_market = top_pick_with_code(lam, mu, home, away, ht_ft_probs, market_odds=cached_odds)'''
new4 = '''        pick, pct, code, used_market = top_pick_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=cached_odds)'''
assert content.count(old4) == 1, f"anchor4 count={content.count(old4)}"
content = content.replace(old4, new4)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - top_pick_with_code wired to prediction_policy (4 patches applied).")
