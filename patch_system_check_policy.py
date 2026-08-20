import ast

with open("match_predictor_app.py", "r") as f:
    content = f.read()

old = '''        m["pending_count"] = sum(1 for p in m["predictions"] if p["status"] == "pending")
        safe_preds = [p for p in m["predictions"] if _is_safe_top_market(p["market_code"])]
        m["top_pred"] = max(safe_preds or m["predictions"], key=lambda p: p["pick_pct"])'''
new = '''        m["pending_count"] = sum(1 for p in m["predictions"] if p["status"] == "pending")
        publishable_preds = [p for p in m["predictions"] if policy.is_publishable(m["league"], p["market_code"])]
        safe_preds = [p for p in publishable_preds if policy.is_top_pick_eligible(m["league"], p["market_code"], allow_weak=True)]
        m["top_pred"] = max(safe_preds or publishable_preds or m["predictions"], key=lambda p: p["pick_pct"])'''
assert content.count(old) == 1, f"anchor count={content.count(old)}"
content = content.replace(old, new)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - system_check top_pred wired to prediction_policy.")
