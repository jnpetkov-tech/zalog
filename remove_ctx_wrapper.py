import ast

PATH = "match_predictor_app.py"

with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

idx = 943  # line 944, 0-based
assert "wrapped = copy_current_request_context(_predict_matches_for_league)" in lines[idx], f"Line 944 mismatch: {lines[idx]!r}"
assert "futures = [executor.submit(wrapped, lg, from_date, to_date) for lg in league_keys]" in lines[idx+1], f"Line 945 mismatch: {lines[idx+1]!r}"

lines[idx] = "            futures = [executor.submit(_predict_matches_for_league, lg, from_date, to_date) for lg in league_keys]\n"
del lines[idx+1]

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(lines)

ast.parse(open(PATH, encoding="utf-8").read())
print("OK - context wrapper премахнат")
