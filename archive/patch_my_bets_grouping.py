with open("match_predictor_app.py", encoding="utf-8") as f:
    content = f.read()

old_route = '''@app.route("/my_bets")
def my_bets():
    bets = bt.list_bets()
    stats = bt.get_stats()
    return render_template_string(MY_BETS_TEMPLATE, bets=bets, stats=stats, cyrillic=to_cyrillic)'''

new_route = '''@app.route("/my_bets")
def my_bets():
    bets = bt.list_bets()
    stats = bt.get_stats()

    singles = [b for b in bets if b["combo_id"] is None]

    combo_groups = {}
    for b in bets:
        if b["combo_id"] is not None:
            combo_groups.setdefault(b["combo_id"], []).append(b)

    combos = []
    for combo_id, legs in sorted(combo_groups.items(), key=lambda x: -x[0]):
        combined_pct = 1.0
        for leg in legs:
            combined_pct *= leg["pick_pct"] / 100
        combined_pct *= 100

        statuses = [leg["status"] for leg in legs]
        if "lost" in statuses:
            combo_status = "lost"
        elif all(s == "won" for s in statuses):
            combo_status = "won"
        else:
            combo_status = "pending"

        combos.append({
            "combo_id": combo_id, "legs": legs,
            "combined_pct": combined_pct, "status": combo_status,
        })

    return render_template_string(MY_BETS_TEMPLATE, singles=singles, combos=combos,
                                    stats=stats, cyrillic=to_cyrillic)'''

if old_route not in content:
    print("ГРЕШКА: не намерих стария route.")
else:
    content = content.replace(old_route, new_route)
    print("Route-ът е обновен успешно.")

old_table = '''<table>
<tr><th>Дата</th><th style="text-align:left;">Мач</th><th style="text-align:left;">Прогноза</th><th>%</th><th>Статус</th></tr>
{% for b in bets %}
<tr>
  <td>{{b.match_date}}</td>
  <td style="text-align:left;">{{cyrillic(b.home_team)}} - {{cyrillic(b.away_team)}}{% if b.combo_id %} <small>(колона #{{b.combo_id}})</small>{% endif %}</td>
  <td style="text-align:left;">{{b.pick_label}}</td>
  <td>{{"%.1f"|format(b.pick_pct)}}%</td>
  <td class="{{b.status}}">{{ {'won':'✅ печели','lost':'❌ губи','pending':'⏳ чака'}[b.status] }}</td>
</tr>
{% endfor %}
</table>'''

new_table = '''<div class="group-title" style="margin-top:20px;">Единични залози</div>
<table>
<tr><th>Дата</th><th style="text-align:left;">Мач</th><th style="text-align:left;">Прогноза</th><th>%</th><th>Статус</th></tr>
{% for b in singles %}
<tr>
  <td>{{b.match_date}}</td>
  <td style="text-align:left;">{{cyrillic(b.home_team)}} - {{cyrillic(b.away_team)}}</td>
  <td style="text-align:left;">{{b.pick_label}}</td>
  <td>{{"%.1f"|format(b.pick_pct)}}%</td>
  <td class="{{b.status}}">{{ {'won':'✅ печели','lost':'❌ губи','pending':'⏳ чака'}[b.status] }}</td>
</tr>
{% endfor %}
</table>

<div class="group-title" style="margin-top:20px;">Комбинирани колони (Права колонка)</div>
{% for c in combos %}
<div class="match-card">
  <div class="match-header">
    <span class="match-teams">Колона #{{c.combo_id}} ({{c.legs|length}} мача)</span>
    <span class="{{c.status}}">{{ {'won':'✅ печели','lost':'❌ губи','pending':'⏳ чака'}[c.status] }}</span>
  </div>
  {% for leg in c.legs %}
  <div style="font-size:13px;padding:4px 0;border-bottom:1px solid #EEEDE7;display:flex;justify-content:space-between;">
    <span>{{leg.match_date}} - {{cyrillic(leg.home_team)}} - {{cyrillic(leg.away_team)}}: {{leg.pick_label}}</span>
    <span class="{{leg.status}}">{{ {'won':'✅','lost':'❌','pending':'⏳'}[leg.status] }}</span>
  </div>
  {% endfor %}
  <div style="margin-top:8px;font-weight:500;">Комбинирана вероятност: {{"%.1f"|format(c.combined_pct)}}%</div>
</div>
{% endfor %}'''

if old_table not in content:
    print("ГРЕШКА: не намерих старата таблица.")
else:
    content = content.replace(old_table, new_table)
    print("Таблицата е обновена успешно.")

with open("match_predictor_app.py", "w", encoding="utf-8") as f:
    f.write(content)
