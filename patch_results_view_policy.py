import ast

with open("results_view.py", "r") as f:
    content = f.read()

# --- Патч 1: import ---
old1 = '''from flask import request, render_template_string
from datetime import datetime, date, timedelta'''
new1 = '''from flask import request, render_template_string
from datetime import datetime, date, timedelta
import prediction_policy as policy'''
assert content.count(old1) == 1, f"anchor1 count={content.count(old1)}"
content = content.replace(old1, new1)

# --- Патч 2: group_by_match() - top_pred/other_preds през policy ---
old2 = '''        m["pending_count"] = sum(1 for p in m["predictions"] if p["status"] in ("pending", "no_data"))
        safe = [p for p in m["predictions"] if p["market_code"] in ROI_MARKETS or p["market_code"].startswith("htft:")]
        m["top_pred"] = max(safe or m["predictions"], key=lambda p: p["pick_pct"] or 0)
        m["other_preds"] = [p for p in m["predictions"] if p is not m["top_pred"]]'''
new2 = '''        m["pending_count"] = sum(1 for p in m["predictions"] if p["status"] in ("pending", "no_data"))
        publishable = [p for p in m["predictions"] if policy.is_publishable(m["league"], p["market_code"])]
        safe = [p for p in publishable if policy.is_top_pick_eligible(m["league"], p["market_code"], allow_weak=True)]
        m["top_pred"] = max(safe or publishable or m["predictions"], key=lambda p: p["pick_pct"] or 0)
        m["other_preds"] = [p for p in publishable if p is not m["top_pred"]]'''
assert content.count(old2) == 1, f"anchor2 count={content.count(old2)}"
content = content.replace(old2, new2)

ast.parse(content)

with open("results_view.py", "w") as f:
    f.write(content)

print("OK - results_view.py wired to prediction_policy (top_pred + other_preds filtered).")
