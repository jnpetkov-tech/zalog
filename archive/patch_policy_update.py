import ast

with open("prediction_policy.py", "r") as f:
    content = f.read()

# --- Патч 1: conference_league матрица - разграничи "тествано и се провали" (1x2)
# от "недостатъчно тествано" (останалите) ---
old1 = '''    "conference_league": {
        # 1X2 изрично НЕ бие baseline (48.2% vs 49.5%) - експериментална лига
        "1x2": REJECTED, "ou25": REJECTED, "team_total": REJECTED, "htft": REJECTED,
        "double_chance": REJECTED, "btts": REJECTED,
        "corners": REJECTED, "cards": REJECTED, "offsides": REJECTED,
    },'''
new1 = '''    "conference_league": {
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
    },'''
assert content.count(old1) == 1, f"anchor1 count={content.count(old1)}"
content = content.replace(old1, new1)

# --- Патч 2: is_top_pick_eligible() получава allow_weak параметър ---
old2 = '''def is_top_pick_eligible(league, market_code):
    """Дали дадена прогноза може да бъде избрана за ГЛАВНАТА/топ прогноза
    на мача. По-строго от is_publishable: изисква PROVEN И групата да не е
    изключена по бизнес причина (напр. двойни шансове - точни, но плащат
    твърде малко)."""
    if tier(league, market_code) != PROVEN:
        return False
    if market_group(market_code) in _TOP_PICK_EXCLUDED_GROUPS:
        return False
    return True'''
new2 = '''def is_top_pick_eligible(league, market_code, allow_weak=False):
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
    return True'''
assert content.count(old2) == 1, f"anchor2 count={content.count(old2)}"
content = content.replace(old2, new2)

ast.parse(content)

with open("prediction_policy.py", "w") as f:
    f.write(content)

print("OK - prediction_policy.py updated (conference_league + allow_weak).")
