import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old_block = "import prediction_policy as policy\n"
new_block = "import prediction_policy as policy\nimport pick_selection as ps\n"

count = content.count(old_block)
assert count == 1, f"import anchor count: {count} (очаквано 1)"
content = content.replace(old_block, new_block, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - import pick_selection as ps добавен")
