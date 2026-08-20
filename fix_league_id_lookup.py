import ast

PATH = "match_predictor_app.py"

with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

idx = 386  # line 387, 0-based
assert '"league": get_league_ids()[league],' in lines[idx], f"Line 387 mismatch: {lines[idx]!r}"

lines[idx] = lines[idx].replace("get_league_ids()[league]", 'ALL_LEAGUES[league]["id"]')

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(lines)

ast.parse(open(PATH, encoding="utf-8").read())
print("OK - league id lookup поправен")
