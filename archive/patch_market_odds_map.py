import ast

with open("system_tracker.py", "r") as f:
    content = f.read()

old = '''MARKET_ODDS_MAP = {
    "home_win": "home_win", "draw": "draw", "away_win": "away_win",
    "over25": "over25", "under25": "under25",
}'''

new = '''MARKET_ODDS_MAP = {
    "home_win": "home_win", "draw": "draw", "away_win": "away_win",
    "over25": "over25", "under25": "under25",
    "home_over15": "home_over15", "home_under15": "home_under15",
    "away_over15": "away_over15", "away_under15": "away_under15",
    "dc_1x": "dc_1x", "dc_x2": "dc_x2", "dc_12": "dc_12",
}
for _a in ("1", "X", "2"):
    for _b in ("1", "X", "2"):
        MARKET_ODDS_MAP[f"htft:{_a}/{_b}"] = f"htft:{_a}/{_b}"'''

assert content.count(old) == 1, f"anchor count={content.count(old)}"
content = content.replace(old, new)

ast.parse(content)

with open("system_tracker.py", "w") as f:
    f.write(content)

print("OK - MARKET_ODDS_MAP extended (D2).")
