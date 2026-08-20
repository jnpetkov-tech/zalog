import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old_block = '''<div class="stats-row">
  <div class="stat-box"><div class="stat-value">{{overall.won}}</div><div class="stat-label">Печеливши</div></div>
  <div class="stat-box"><div class="stat-value">{{overall.lost}}</div><div class="stat-label">Губещи</div></div>
  <div class="stat-box"><div class="stat-value">{{overall.pending}}</div><div class="stat-label">Чакащи</div></div>
  <!-- Фаза H.2 (2026-08-11): "Успеваемост" плочката е скрита умишлено - смесва пазари с
       различен baseline (33%/50%/67%), числото е аритметичен артефакт, не показател за
       качество. Ще се върне като честна метрика (само върху публикувани пикове) след
       Фаза I (evaluation.py). Виж claude/ACTION_PLAN.md Фаза H.2. -->
</div>'''

new_block = '''<div class="stats-row">
  <div class="stat-box"><div class="stat-value">{{overall.won}}</div><div class="stat-label">Печеливши</div></div>
  <div class="stat-box"><div class="stat-value">{{overall.lost}}</div><div class="stat-label">Губещи</div></div>
  <div class="stat-box"><div class="stat-value">{{overall.pending}}</div><div class="stat-label">Чакащи</div></div>
</div>
{% if promised_avg is not none %}
<div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap;margin-bottom:20px;padding:14px 18px;background:var(--panel);border:1px solid var(--border);border-radius:10px;">
  <div><div style="font-size:22px;font-weight:700;">{{ "%.1f%%"|format(promised_avg) }}</div><div style="font-size:11px;color:var(--sub);">обещано средно</div></div>
  <div style="color:var(--sub);font-size:18px;">&rarr;</div>
  <div><div style="font-size:22px;font-weight:700;">{{ "%.1f%%"|format(actual_pct) }}</div><div style="font-size:11px;color:var(--sub);">реално познати</div></div>
  <div style="margin-left:auto;font-size:11px;color:var(--sub);">само публикувани прогнози &middot; n={{n_settled}} приключили</div>
</div>
{% endif %}'''

count = content.count(old_block)
assert count == 1, f"stats-row anchor count: {count} (очаквано 1)"
content = content.replace(old_block, new_block, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - началната страница показва честната метрика (обещано средно -> реално познати)")
