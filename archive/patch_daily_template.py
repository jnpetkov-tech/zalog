import ast

with open("match_predictor_app.py") as f:
    content = f.read()

# --- Патч 1: компактен филтър на ЕДИН ред (лига + от дата + до дата + бутон) ---
old_filter = '''<form class="filter" method="get">
  <select name="league"><option value="all" {% if selected_league=="all" %}selected{% endif %}>🌍 Всички лиги</option>{% for key, name in leagues.items() %}<option value="{{key}}" {% if key==selected_league %}selected{% endif %}>{{name}}</option>{% endfor %}</select>
  <div style="display:flex;gap:10px;margin-bottom:10px;">
    <div style="flex:1;">
      <label style="font-size:11px;color:var(--sub);">От дата</label>
      <input type="date" name="from_date" value="{{from_value}}" style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);box-sizing:border-box;background:var(--panel2);color:var(--text);">
    </div>
    <div style="flex:1;">
      <label style="font-size:11px;color:var(--sub);">До дата</label>
      <input type="date" name="to_date" value="{{to_value}}" style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);box-sizing:border-box;background:var(--panel2);color:var(--text);">
    </div>
  </div>
  <button type="submit">Покажи мачове</button>
</form>'''

new_filter = '''<form class="filter" method="get" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;margin-bottom:14px;">
  <div style="flex:2;min-width:200px;">
    <label style="font-size:11px;color:var(--sub);">Лига</label>
    <select name="league" style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);box-sizing:border-box;background:var(--panel2);color:var(--text);"><option value="all" {% if selected_league=="all" %}selected{% endif %}>🌍 Всички лиги</option>{% for key, name in leagues.items() %}<option value="{{key}}" {% if key==selected_league %}selected{% endif %}>{{name}}</option>{% endfor %}</select>
  </div>
  <div style="flex:1;min-width:130px;">
    <label style="font-size:11px;color:var(--sub);">От дата</label>
    <input type="date" name="from_date" value="{{from_value}}" style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);box-sizing:border-box;background:var(--panel2);color:var(--text);">
  </div>
  <div style="flex:1;min-width:130px;">
    <label style="font-size:11px;color:var(--sub);">До дата</label>
    <input type="date" name="to_date" value="{{to_value}}" style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);box-sizing:border-box;background:var(--panel2);color:var(--text);">
  </div>
  <button type="submit" style="flex:0 0 auto;">Покажи</button>
</form>'''

assert content.count(old_filter) == 1, f"filter anchor count: {content.count(old_filter)}"
content = content.replace(old_filter, new_filter, 1)

# --- Патч 2: upcoming tab pick-row - множество прогнози (picks), честно
# labeling на fair price ("оценка", не "(~1.28)" самò по себе си), по-неутрален
# бутон "Направи залог" (де-акцентиран спрямо самата прогноза) ---
old_pickrow = '''    <div class="match-pick-row">
      {% if m.pct is not none %}
      <span>{{m.pick}} <b>{{"%.1f"|format(m.pct)}}%</b>{% if m.odds %} <span style="color:var(--sub);">(~{{m.odds}})</span>{% endif %}
        {% if m.used_market %}<span style="font-size:11px;background:var(--green-bg);color:var(--green);padding:2px 6px;border-radius:6px;margin-left:6px;">🎯 с пазарни коеф.</span>{% else %}<span style="font-size:11px;background:var(--panel2);color:var(--sub);padding:2px 6px;border-radius:6px;margin-left:6px;">⏳ чисто моделна</span>{% endif %}
      </span>
      <span>
        <a href="/match_detail?league={{m.league}}&fixture_id={{m.fixture_id}}&home={{m.home}}&away={{m.away}}&date={{m.date}}" style="font-size:12px;color:var(--accent);text-decoration:none;margin-right:10px;">Влез в мача →</a>
        <button type="submit" formaction="/place_bet_single/{{m.idx}}" class="small green">Направи залог</button>
      </span>
      {% else %}
      <span style="color:var(--sub);">{{m.pick}}</span>
      <span>
        <a href="/live?league={{m.league}}&home={{m.home}}&away={{m.away}}" style="font-size:12px;color:var(--sub);text-decoration:none;">Следи на живо →</a>
      </span>
      {% endif %}
    </div>'''

new_pickrow = '''    <div class="match-pick-row" style="display:block;">
      {% if m.pct is not none %}
      <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px;">
        {% for p in m.picks %}
        <span style="background:var(--panel2);border:1px solid {% if loop.first %}var(--accent){% else %}var(--border){% endif %};border-radius:8px;padding:5px 10px;font-size:13px;">{{p.label}} <b>{{"%.1f"|format(p.pct)}}%</b>{% if p.odds %} <span style="color:var(--sub);font-size:11px;" title="Наша изчислена честна цена по вероятността - НЕ котировка на букмейкър">оценка ≈{{p.odds}}</span>{% endif %}</span>
        {% endfor %}
        {% if m.used_market %}<span style="font-size:11px;background:var(--green-bg);color:var(--green);padding:2px 6px;border-radius:6px;">🎯 с пазарни коеф.</span>{% else %}<span style="font-size:11px;background:var(--panel2);color:var(--sub);padding:2px 6px;border-radius:6px;">⏳ чисто моделна</span>{% endif %}
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <a href="/match_detail?league={{m.league}}&fixture_id={{m.fixture_id}}&home={{m.home}}&away={{m.away}}&date={{m.date}}" style="font-size:12px;color:var(--accent);text-decoration:none;">Влез в мача →</a>
        <button type="submit" formaction="/place_bet_single/{{m.idx}}" class="small" style="background:transparent;border:1px solid var(--border);color:var(--sub);font-weight:400;">Залог на топ прогнозата</button>
      </div>
      {% else %}
      <span style="color:var(--sub);">{{m.pick}}</span>
      <span>
        <a href="/live?league={{m.league}}&home={{m.home}}&away={{m.away}}" style="font-size:12px;color:var(--sub);text-decoration:none;">Следи на живо →</a>
      </span>
      {% endif %}
    </div>'''

assert content.count(old_pickrow) == 1, f"pickrow anchor count: {content.count(old_pickrow)}"
content = content.replace(old_pickrow, new_pickrow, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - DAILY_TEMPLATE: компактен филтър + честно labeling + множество picks + де-акцентиран бутон")
