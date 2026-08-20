import ast

PATH = "match_predictor_app.py"

with open(PATH, encoding="utf-8") as f:
    content = f.read()

old = '''    <button type="submit" class="home-refresh-btn">💰 Опресни пазарни коефициенти</button>'''
assert content.count(old) == 1, "green button anchor not found or not unique"

new = '''    <button type="submit" class="small green">💰 Опресни пазарни коефициенти</button>'''

content = content.replace(old, new)

ast.parse(content)

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("OK - written, syntax valid.")
