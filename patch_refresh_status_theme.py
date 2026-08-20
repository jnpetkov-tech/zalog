import ast

PATH = "match_predictor_app.py"

with open(PATH, encoding="utf-8") as f:
    content = f.read()

old = '''<p style="font-size:12px;color:#888780;">Презареди страницата (F5), за да видиш последния прогрес.</p>
<pre style="background:white;border-radius:12px;padding:16px;font-size:12px;white-space:pre-wrap;border:0.5px solid #D3D1C7;">{content}</pre>'''
assert content.count(old) == 1, "refresh_status pre/hint anchor not found or not unique"

new = '''<p style="font-size:12px;color:var(--sub);">Презареди страницата (F5), за да видиш последния прогрес.</p>
<pre style="background:var(--panel2);color:var(--text);border-radius:12px;padding:16px;font-size:12px;white-space:pre-wrap;border:1px solid var(--border);">{content}</pre>'''

content = content.replace(old, new)

ast.parse(content)

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("OK - written, syntax valid.")
