import ast

PATH = "match_predictor_app.py"

with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

idx = 854  # line 855, 0-based
assert lines[idx].strip() == '@app.route("/")', f"Line 855 mismatch: {lines[idx]!r}"
assert lines[idx+1].strip() == 'def index():', f"Line 856 mismatch: {lines[idx+1]!r}"

lines[idx] = '@app.route("/manual")\n'

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(lines)

ast.parse(open(PATH, encoding="utf-8").read())
print("OK - route преместен на /manual")
