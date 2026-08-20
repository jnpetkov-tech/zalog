import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old_block = '''<div class="stats-row">
  <div class="stat-box"><div class="stat-value">{{overall.won}}</div><div class="stat-label">Печеливши</div></div>
  <div class="stat-box"><div class="stat-value">{{overall.lost}}</div><div class="stat-label">Губещи</div></div>
  <div class="stat-box"><div class="stat-value">{{overall.pending}}</div><div class="stat-label">Чакащи</div></div>
  <div class="stat-box"><div class="stat-value">{{ "%.1f%%"|format(overall.win_rate) if overall.win_rate is not none else "—" }}</div><div class="stat-label">Успеваемост</div></div>
</div>'''

new_block = '''<div class="stats-row">
  <div class="stat-box"><div class="stat-value">{{overall.won}}</div><div class="stat-label">Печеливши</div></div>
  <div class="stat-box"><div class="stat-value">{{overall.lost}}</div><div class="stat-label">Губещи</div></div>
  <div class="stat-box"><div class="stat-value">{{overall.pending}}</div><div class="stat-label">Чакащи</div></div>
  <!-- Фаза H.2 (2026-08-11): "Успеваемост" плочката е скрита умишлено - смесва пазари с
       различен baseline (33%/50%/67%), числото е аритметичен артефакт, не показател за
       качество. Ще се върне като честна метрика (само върху публикувани пикове) след
       Фаза I (evaluation.py). Виж claude/ACTION_PLAN.md Фаза H.2. -->
</div>'''

count = content.count(old_block)
assert count == 1, f"INDEX_TEMPLATE stats-row anchor count: {count} (очаквано 1)"
content = content.replace(old_block, new_block, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - 'Успеваемост' плочката на началната страница е скрита (Фаза H.2)")
