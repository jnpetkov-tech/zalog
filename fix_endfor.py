import ast

PATH = "match_predictor_app.py"

with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

idx = 1221  # line 1222, 0-based
assert lines[idx].strip() == "{% endfor %}", f"Line 1222 mismatch: {lines[idx]!r}"
assert lines[idx-1].strip() == "{% endfor %}", f"Line 1221 mismatch: {lines[idx-1]!r}"
assert lines[idx+1].strip() == "</div>", f"Line 1223 mismatch: {lines[idx+1]!r}"

del lines[idx]

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(lines)

ast.parse(open(PATH, encoding="utf-8").read())
print("OK - излишният endfor е премахнат")
