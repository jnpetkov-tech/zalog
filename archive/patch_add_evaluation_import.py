import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old_block = "import pick_selection as ps\n"
new_block = "import pick_selection as ps\nimport evaluation\n"

count = content.count(old_block)
assert count == 1, f"import anchor count: {count} (очаквано 1)"
content = content.replace(old_block, new_block, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - import evaluation добавен")
