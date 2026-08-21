import ast

PATH = "match_predictor_app.py"

with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

assert lines[1200].strip() == 'SYSTEM_CHECK_TEMPLATE = """', f"Line 1201 mismatch: {lines[1200]!r}"
assert "page=page, total_pages=total_pages, total_matches=total_matches)" in lines[1354], f"Line 1355 mismatch: {lines[1354]!r}"

new_block = '''SYSTEM_CHECK_TEMPLATE = """
<!DOCTYPE html><html lang="bg"><head><meta charset="UTF-8"><title>Проверка на системата</title>
<style>""" + BASE_STYLE + """</style></head><body><div class="container">
<h1>Проверка на системата</h1>
<div class="nav"><a href="/" style="font-weight:500;">🏠 Начало</a><a href="/manual">Ръчна проверка</a><a href="/daily">Днешни/предстоящи мачове</a><a href="/live">На живо</a><a href="/my_bets">Моите залози</a><a href="/system_check">📊 Проверка</a><a href="/leagues_admin">⚙️ Лиги</a></div>

<div class="stats-row">
  <div class="stat-box"><div class="stat-value">{{overall.won}}</div><div class="stat-label">Печеливши</div></div>
  <div class="stat-box"><div class="stat-value">{{overall.lost}}</div><div class="stat-label">Губещи</div></div>
  <div class="stat-box"><div class="stat-value">{{overall.pending}}</div><div class="stat-label">Чакащи</div></div>
  <div class="stat-box"><div class="stat-value">{{ "%.1f%%"|format(overall.win_rate) if overall.win_rate is not none else "—" }}</div><div class="stat-label">Успеваемост</div></div>
</div>

<form method="post" action="/system_check_results" style="margin-bottom:20px;">
  <button type="submit" class="green">Провери резултатите</button>
</form>

<div class="group-title">По тип пазар (сортирано по успеваемост)</div>
<table>
<tr><th>Пазар</th><th>Печ.</th><th>Губ.</th><th>Чак.</th><th>%</th></tr>
{% for m in by_market %}
<tr><td>{{m.market_code}}</td><td>{{m.won}}</td><td>{{m.lost}}</td><td>{{m.pending}}</td>
<td>{{ "%.1f%%"|format(m.win_rate) if m.win_rate is not none else "—" }}</td></tr>
{% endfor %}
</table>

<div class="group-title" style="margin-top:20px;">По лига (сортирано по успеваемост)</div>
<table>
<tr><th>Лига</th><th>Печ.</th><th>Губ.</th><th>Чак.</th><th>%</th></tr>
{% for l in by_league %}
<tr><td>{{l.league}}</td><td>{{l.won}}</td><td>{{l.lost}}</td><td>{{l.pending}}</td>
<td>{{ "%.1f%%"|format(l.win_rate) if l.win_rate is not none else "—" }}</td></tr>
{% endfor %}
</table>

{% macro pred_card(m) %}
<div class="match-card">
  <div class="match-header">
    <span class="match-teams">{{cyrillic(m.home)}} - {{cyrillic(m.away)}} <small style="color:#888780;">({{m.league}})</small></span>
    <span class="match-date">{{m.date}}</span>
  </div>
  {% for p in m.predictions %}
  <div style="font-size:13px;padding:4px 0;border-bottom:1px solid #EEEDE7;display:flex;justify-content:space-between;align-items:center;">
    <span>{{p.pick_label}} <span style="color:#888780;">({{"%.1f"|format(p.pick_pct)}}%)</span></span>
    <span style="font-size:11px;color:#888780;">
      {% if p.our_fair_odds %}наш: {{p.our_fair_odds}}{% endif %}
      {% if p.market_odds %} | пазар: {{p.market_odds}}{% endif %}
    </span>
    <span class="{{p.status}}">{{ {'won':'✅','lost':'❌','pending':'⏳'}[p.status] }}</span>
  </div>
  {% endfor %}
</div>
{% endmacro %}

<div class="group-title" style="margin-top:20px;">🟢 Чакащи ({{pending_matches|length}})</div>
{% for m in pending_matches %}{{ pred_card(m) }}{% endfor %}
{% if not pending_matches %}<p style="color:#888780;font-size:13px;">Няма чакащи мачове.</p>{% endif %}

<div class="group-title" style="margin-top:24px;">⚪ Приключили ({{total_completed}})</div>

<form method="get" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:16px;">
  <div>
    <label style="font-size:11px;color:#5F5E5A;display:block;">Лига</label>
    <select name="f_league" onchange="this.form.submit()">
      <option value="">Всички</option>
      {% for l in league_options %}<option value="{{l}}" {% if l==filter_league %}selected{% endif %}>{{l}}</option>{% endfor %}
    </select>
  </div>
  <div>
    <label style="font-size:11px;color:#5F5E5A;display:block;">Пазар</label>
    <select name="f_market" onchange="this.form.submit()">
      <option value="">Всички</option>
      {% for m in market_options %}<option value="{{m}}" {% if m==filter_market %}selected{% endif %}>{{m}}</option>{% endfor %}
    </select>
  </div>
  <div>
    <label style="font-size:11px;color:#5F5E5A;display:block;">Статус</label>
    <select name="f_status" onchange="this.form.submit()">
      <option value="">Всички</option>
      <option value="won" {% if filter_status=="won" %}selected{% endif %}>✅ Печеливши</option>
      <option value="lost" {% if filter_status=="lost" %}selected{% endif %}>❌ Губещи</option>
    </select>
  </div>
  {% if filter_league or filter_market or filter_status %}
  <a href="/system_check" style="font-size:13px;color:#185FA5;padding-bottom:8px;">Изчисти филтрите</a>
  {% endif %}
</form>

{% for m in completed_matches %}{{ pred_card(m) }}{% endfor %}
{% if not completed_matches %}<p style="color:#888780;font-size:13px;">Няма приключили мачове{% if filter_league or filter_market or filter_status %} за избраните филтри{% endif %}.</p>{% endif %}

<div style="display:flex;justify-content:center;align-items:center;gap:20px;margin:24px 0;font-size:13px;">
  {% if page > 1 %}<a href="?f_league={{filter_league}}&f_market={{filter_market}}&f_status={{filter_status}}&page={{page-1}}" style="color:#185FA5;">← Предишна</a>{% endif %}
  <span style="color:#5F5E5A;">Страница {{page}} от {{total_pages}}</span>
  {% if page < total_pages %}<a href="?f_league={{filter_league}}&f_market={{filter_market}}&f_status={{filter_status}}&page={{page+1}}" style="color:#185FA5;">Следваща →</a>{% endif %}
</div>

</div></body></html>
"""


@app.route("/system_check")
def system_check():
    predictions = st.list_predictions()

    won = sum(1 for p in predictions if p["status"] == "won")
    lost = sum(1 for p in predictions if p["status"] == "lost")
    pending = sum(1 for p in predictions if p["status"] == "pending")
    total_settled = won + lost
    win_rate = (won / total_settled * 100) if total_settled else None
    overall = {"won": won, "lost": lost, "pending": pending, "win_rate": win_rate}

    by_market = st.get_stats_by_market()
    by_market.sort(key=lambda m: (m["win_rate"] is None, -(m["win_rate"] or 0)))
    by_league = st.get_stats_by_league()
    by_league.sort(key=lambda l: (l["win_rate"] is None, -(l["win_rate"] or 0)))

    league_options = sorted({l["league"] for l in by_league})
    market_options = sorted({m["market_code"] for m in by_market})

    filter_league = request.args.get("f_league", "")
    filter_market = request.args.get("f_market", "")
    filter_status = request.args.get("f_status", "")

    filtered = predictions
    if filter_league:
        filtered = [p for p in filtered if p["league"] == filter_league]
    if filter_market:
        filtered = [p for p in filtered if p["market_code"] == filter_market]
    if filter_status:
        filtered = [p for p in filtered if p["status"] == filter_status]

    match_groups = {}
    for p in filtered:
        key = p["fixture_id"]
        match_groups.setdefault(key, {"date": p["match_date"], "home": p["home_team"],
                                        "away": p["away_team"], "league": p["league"], "predictions": []})
        match_groups[key]["predictions"].append(p)

    all_matches = list(match_groups.values())
    for m in all_matches:
        m["pending_count"] = sum(1 for p in m["predictions"] if p["status"] == "pending")

    pending_matches = sorted([m for m in all_matches if m["pending_count"] > 0], key=lambda m: m["date"])
    completed_all = sorted([m for m in all_matches if m["pending_count"] == 0], key=lambda m: m["date"], reverse=True)

    PAGE_SIZE = 25
    total_completed = len(completed_all)
    total_pages = max(1, (total_completed + PAGE_SIZE - 1) // PAGE_SIZE)
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    page = min(page, total_pages)
    start = (page - 1) * PAGE_SIZE
    completed_matches = completed_all[start:start + PAGE_SIZE]

    return render_template_string(SYSTEM_CHECK_TEMPLATE, overall=overall, by_market=by_market,
                                    by_league=by_league, pending_matches=pending_matches,
                                    completed_matches=completed_matches, cyrillic=to_cyrillic,
                                    filter_league=filter_league, filter_market=filter_market, filter_status=filter_status,
                                    league_options=league_options, market_options=market_options,
                                    page=page, total_pages=total_pages, total_completed=total_completed)
'''

new_lines = lines[:1200] + [new_block] + lines[1355:]

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

ast.parse(open(PATH, encoding="utf-8").read())
print("OK - разделянето Чакащи/Приключили е добавено")
