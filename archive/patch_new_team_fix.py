import ast

PATH = "match_predictor_app.py"

with open(PATH, encoding="utf-8") as f:
    content = f.read()

# 1. Python loop: don't silently skip fixtures with unknown teams
old1 = '''    for f in fixtures:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        if home not in team_idx or away not in team_idx:
            continue
        match_date = f["fixture"]["date"][:16].replace("T", " ")
        fixture_id = f["fixture"]["id"]
        status_short = f["fixture"]["status"].get("short", "NS")
        elapsed = f["fixture"]["status"].get("elapsed")
        goals_home = f["goals"]["home"]
        goals_away = f["goals"]["away"]

        home_inj, away_inj = 0, 0'''
assert content.count(old1) == 1, "1: loop header anchor not found or not unique"

new1 = '''    for f in fixtures:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        match_date = f["fixture"]["date"][:16].replace("T", " ")
        fixture_id = f["fixture"]["id"]
        status_short = f["fixture"]["status"].get("short", "NS")
        elapsed = f["fixture"]["status"].get("elapsed")
        goals_home = f["goals"]["home"]
        goals_away = f["goals"]["away"]
        if home not in team_idx or away not in team_idx:
            matches.append({
                "date": match_date, "home": home, "away": away,
                "home_cy": to_cyrillic(home, league), "away_cy": to_cyrillic(away, league),
                "home_logo": f["teams"]["home"].get("logo"), "away_logo": f["teams"]["away"].get("logo"),
                "pick": "Няма прогноза (нов отбор)", "pct": None, "code": None, "odds": None,
                "fixture_id": fixture_id, "inj_note": None,
                "lineups_confirmed": False,
                "league": league, "league_name": ALL_LEAGUES[league]["name"],
                "used_market": None, "odds_updated_at": None,
                "status_short": status_short, "elapsed": elapsed,
                "goals_home": goals_home, "goals_away": goals_away, "live_result": None,
            })
            continue

        home_inj, away_inj = 0, 0'''

content = content.replace(old1, new1)

# 2. Live tab template block
old2 = '''    <div class="match-pick-row">
      {% if m.live_result %}
      <span>{{m.home_cy}} {{"%.0f"|format(m.live_result.home_win*100)}}% · Равен {{"%.0f"|format(m.live_result.draw*100)}}% · {{m.away_cy}} {{"%.0f"|format(m.live_result.away_win*100)}}%</span>
      {% else %}
      <span style="color:var(--sub);">{{m.pick}} <b>{{"%.1f"|format(m.pct)}}%</b> <span style="font-size:11px;">(предмачова прогноза)</span></span>
      {% endif %}
      <span>
        <a href="/match_detail?league={{m.league}}&fixture_id={{m.fixture_id}}&home={{m.home}}&away={{m.away}}&date={{m.date}}" style="font-size:12px;color:var(--accent);text-decoration:none;margin-right:10px;">Пълна прогноза →</a>
        <a href="/live?league={{m.league}}&home={{m.home}}&away={{m.away}}&minute={{m.elapsed if m.elapsed is not none else 0}}&hg={{m.goals_home}}&ag={{m.goals_away}}" style="font-size:12px;color:var(--sub);text-decoration:none;">Персонализирай →</a>
      </span>
    </div>'''
assert content.count(old2) == 1, "2: live tab anchor not found or not unique"

new2 = '''    <div class="match-pick-row">
      {% if m.pct is none %}
      <span style="color:var(--sub);">{{m.pick}}</span>
      <span>
        <a href="/live?league={{m.league}}&home={{m.home}}&away={{m.away}}&minute={{m.elapsed if m.elapsed is not none else 0}}&hg={{m.goals_home}}&ag={{m.goals_away}}" style="font-size:12px;color:var(--sub);text-decoration:none;">Персонализирай →</a>
      </span>
      {% elif m.live_result %}
      <span>{{m.home_cy}} {{"%.0f"|format(m.live_result.home_win*100)}}% · Равен {{"%.0f"|format(m.live_result.draw*100)}}% · {{m.away_cy}} {{"%.0f"|format(m.live_result.away_win*100)}}%</span>
      <span>
        <a href="/match_detail?league={{m.league}}&fixture_id={{m.fixture_id}}&home={{m.home}}&away={{m.away}}&date={{m.date}}" style="font-size:12px;color:var(--accent);text-decoration:none;margin-right:10px;">Пълна прогноза →</a>
        <a href="/live?league={{m.league}}&home={{m.home}}&away={{m.away}}&minute={{m.elapsed if m.elapsed is not none else 0}}&hg={{m.goals_home}}&ag={{m.goals_away}}" style="font-size:12px;color:var(--sub);text-decoration:none;">Персонализирай →</a>
      </span>
      {% else %}
      <span style="color:var(--sub);">{{m.pick}} <b>{{"%.1f"|format(m.pct)}}%</b> <span style="font-size:11px;">(предмачова прогноза)</span></span>
      <span>
        <a href="/match_detail?league={{m.league}}&fixture_id={{m.fixture_id}}&home={{m.home}}&away={{m.away}}&date={{m.date}}" style="font-size:12px;color:var(--accent);text-decoration:none;margin-right:10px;">Пълна прогноза →</a>
        <a href="/live?league={{m.league}}&home={{m.home}}&away={{m.away}}&minute={{m.elapsed if m.elapsed is not none else 0}}&hg={{m.goals_home}}&ag={{m.goals_away}}" style="font-size:12px;color:var(--sub);text-decoration:none;">Персонализирай →</a>
      </span>
      {% endif %}
    </div>'''

content = content.replace(old2, new2)

# 3. Upcoming tab template block
old3 = '''    <div class="match-pick-row">
      <span>{{m.pick}} <b>{{"%.1f"|format(m.pct)}}%</b>{% if m.odds %} <span style="color:var(--sub);">(~{{m.odds}})</span>{% endif %}
        {% if m.used_market %}<span style="font-size:11px;background:var(--green-bg);color:var(--green);padding:2px 6px;border-radius:6px;margin-left:6px;">🎯 с пазарни коеф.</span>{% else %}<span style="font-size:11px;background:var(--panel2);color:var(--sub);padding:2px 6px;border-radius:6px;margin-left:6px;">⏳ чисто моделна</span>{% endif %}
      </span>
      <span>
        <a href="/match_detail?league={{m.league}}&fixture_id={{m.fixture_id}}&home={{m.home}}&away={{m.away}}&date={{m.date}}" style="font-size:12px;color:var(--accent);text-decoration:none;margin-right:10px;">Влез в мача →</a>
        <button type="submit" formaction="/place_bet_single/{{m.idx}}" class="small green">Направи залог</button>
      </span>
    </div>
    {% if m.inj_note %}<div class="inj-note">{{m.inj_note}}</div>{% endif %}
    <div class="checkbox-row">
      <input type="checkbox" name="sel_{{m.idx}}" id="sel_{{m.idx}}">
      <label for="sel_{{m.idx}}" style="font-size:12px;color:var(--sub);">Добави в комбинирана колонка</label>
      <input type="hidden" name="league_{{m.idx}}" value="{{m.league}}">
      <input type="hidden" name="fixture_id_{{m.idx}}" value="{{m.fixture_id}}">
      <input type="hidden" name="date_{{m.idx}}" value="{{m.date}}">
      <input type="hidden" name="home_{{m.idx}}" value="{{m.home}}">
      <input type="hidden" name="away_{{m.idx}}" value="{{m.away}}">
      <input type="hidden" name="code_{{m.idx}}" value="{{m.code}}">
      <input type="hidden" name="pick_{{m.idx}}" value="{{m.pick}}">
      <input type="hidden" name="pct_{{m.idx}}" value="{{m.pct}}">
    </div>'''
assert content.count(old3) == 1, "3: upcoming tab anchor not found or not unique"

new3 = '''    <div class="match-pick-row">
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
    </div>
    {% if m.inj_note %}<div class="inj-note">{{m.inj_note}}</div>{% endif %}
    {% if m.pct is not none %}
    <div class="checkbox-row">
      <input type="checkbox" name="sel_{{m.idx}}" id="sel_{{m.idx}}">
      <label for="sel_{{m.idx}}" style="font-size:12px;color:var(--sub);">Добави в комбинирана колонка</label>
      <input type="hidden" name="league_{{m.idx}}" value="{{m.league}}">
      <input type="hidden" name="fixture_id_{{m.idx}}" value="{{m.fixture_id}}">
      <input type="hidden" name="date_{{m.idx}}" value="{{m.date}}">
      <input type="hidden" name="home_{{m.idx}}" value="{{m.home}}">
      <input type="hidden" name="away_{{m.idx}}" value="{{m.away}}">
      <input type="hidden" name="code_{{m.idx}}" value="{{m.code}}">
      <input type="hidden" name="pick_{{m.idx}}" value="{{m.pick}}">
      <input type="hidden" name="pct_{{m.idx}}" value="{{m.pct}}">
    </div>
    {% endif %}'''

content = content.replace(old3, new3)

# 4. Finished tab template block
old4 = '''    <div class="match-pick-row">
      <span style="color:var(--sub);">Наша прогноза: {{m.pick}} ({{"%.1f"|format(m.pct)}}%)</span>
      <a href="/match_detail?league={{m.league}}&fixture_id={{m.fixture_id}}&home={{m.home}}&away={{m.away}}&date={{m.date}}" style="font-size:12px;color:var(--accent);text-decoration:none;">Детайли →</a>
    </div>'''
assert content.count(old4) == 1, "4: finished tab anchor not found or not unique"

new4 = '''    <div class="match-pick-row">
      {% if m.pct is not none %}
      <span style="color:var(--sub);">Наша прогноза: {{m.pick}} ({{"%.1f"|format(m.pct)}}%)</span>
      {% else %}
      <span style="color:var(--sub);">{{m.pick}}</span>
      {% endif %}
      <a href="/match_detail?league={{m.league}}&fixture_id={{m.fixture_id}}&home={{m.home}}&away={{m.away}}&date={{m.date}}" style="font-size:12px;color:var(--accent);text-decoration:none;">Детайли →</a>
    </div>'''

content = content.replace(old4, new4)

ast.parse(content)

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("OK - all 4 replacements applied, written.")
