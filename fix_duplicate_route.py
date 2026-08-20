import ast

PATH = "match_predictor_app.py"

with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

assert lines[860].strip() == '@app.route("/daily")', f"Line 861 mismatch: {lines[860]!r}"
assert lines[861].strip() == 'def _predict_matches_for_league(league, from_date, to_date):', f"Line 862 mismatch: {lines[861]!r}"

# Remove the stray decorator line (index 860)
del lines[860]

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(lines)

ast.parse(open(PATH, encoding="utf-8").read())
print("OK - премахнат дублиран декоратор, синтаксисът е валиден")
