import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old_block = '''        top_pred = max(preds, key=lambda x: x["pick_pct"])
        top_matches.append({"date": mdate, "home": home, "away": away, "league": league, "top_pred": top_pred})'''

new_block = '''        eligible = [p for p in preds if (p["pick_pct"] or 0) < 95
                    and policy.is_top_pick_eligible(league, p["market_code"])]
        if not eligible:
            eligible = [p for p in preds if (p["pick_pct"] or 0) < 95
                        and policy.is_top_pick_eligible(league, p["market_code"], allow_weak=True)]
        if not eligible:
            continue
        top_pred = max(eligible, key=lambda x: x["pick_pct"])
        top_matches.append({"date": mdate, "home": home, "away": away, "league": league, "top_pred": top_pred})'''

count = content.count(old_block)
assert count == 1, f"index_home anchor count: {count} (очаквано 1)"
content = content.replace(old_block, new_block, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - index_home() вече филтрира през policy.is_top_pick_eligible() + PROVEN->WEAK fallback + pick_pct<95")
