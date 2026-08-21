with open("match_predictor_app.py", encoding="utf-8") as f:
    content = f.read()

old_fetch = '''def fetch_upcoming_fixtures(league):
    today = date.today()
    to_date = today + timedelta(days=DAYS_AHEAD)
    params = {
        "league": LEAGUE_IDS[league],
        "season": today.year if today.month >= 7 else today.year - 1,
        "from": today.isoformat(),
        "to": to_date.isoformat(),
        "timezone": "Europe/Sofia",
    }
    r = requests.get(f"{BASE_URL}/fixtures", headers=API_HEADERS, params=params)
    data = r.json()
    return data.get("response", [])'''

new_fetch = '''def fetch_upcoming_fixtures(league):
    today = date.today()
    to_date = today + timedelta(days=DAYS_AHEAD)
    params = {
        "league": LEAGUE_IDS[league],
        "season": today.year if today.month >= 7 else today.year - 1,
        "from": today.isoformat(),
        "to": to_date.isoformat(),
        "timezone": "Europe/Sofia",
    }
    try:
        r = requests.get(f"{BASE_URL}/fixtures", headers=API_HEADERS, params=params, timeout=15)
        data = r.json()
    except Exception as e:
        return [], f"Мрежова грешка при връзка с API-то: {e}"

    if data.get("errors"):
        errors = data["errors"]
        if isinstance(errors, dict) and "plan" in errors:
            return [], (f"Ограничение на абонаментния план: {errors['plan']} "
                         "Провери плана си в dashboard.api-football.com.")
        return [], f"Грешка от API-то: {errors}"

    return data.get("response", []), None'''

if old_fetch not in content:
    print("ГРЕШКА: не намерих fetch_upcoming_fixtures функцията в очаквания вид.")
else:
    content = content.replace(old_fetch, new_fetch)
    print("fetch_upcoming_fixtures е обновена успешно.")

old_daily_route = '''@app.route("/daily")
def daily():
    league = request.args.get("league", "bulgaria")
    fixtures = fetch_upcoming_fixtures(league)
    teams, team_idx, ft_model, ht_model, h2_model = get_models(league)[:5]'''

new_daily_route = '''@app.route("/daily")
def daily():
    league = request.args.get("league", "bulgaria")
    fixtures, api_error = fetch_upcoming_fixtures(league)
    teams, team_idx, ft_model, ht_model, h2_model = get_models(league)[:5]'''

if old_daily_route not in content:
    print("ГРЕШКА: не намерих daily route началото.")
else:
    content = content.replace(old_daily_route, new_daily_route)
    print("daily route началото е обновено успешно.")

old_render = '''    return render_template_string(DAILY_TEMPLATE, leagues=LEAGUES, selected_league=league,
                                    league_name=LEAGUES[league], matches=matches, days_ahead=DAYS_AHEAD)'''

new_render = '''    return render_template_string(DAILY_TEMPLATE, leagues=LEAGUES, selected_league=league,
                                    league_name=LEAGUES[league], matches=matches, days_ahead=DAYS_AHEAD,
                                    api_error=api_error)'''

if old_render not in content:
    print("ГРЕШКА: не намерих render_template_string реда за daily.")
else:
    content = content.replace(old_render, new_render)
    print("render_template_string извикването е обновено успешно.")

old_banner_anchor = '''<form class="filter" method="get">
  <select name="league" onchange="this.form.submit()">{% for key, name in leagues.items() %}<option value="{{key}}" {% if key==selected_league %}selected{% endif %}>{{name}}</option>{% endfor %}</select>
</form>

{% if matches %}'''

new_banner_anchor = '''<form class="filter" method="get">
  <select name="league" onchange="this.form.submit()">{% for key, name in leagues.items() %}<option value="{{key}}" {% if key==selected_league %}selected{% endif %}>{{name}}</option>{% endfor %}</select>
</form>

{% if api_error %}
<div style="background:#B23B3B15;border:1px solid #B23B3B40;border-radius:12px;padding:16px 20px;margin-bottom:20px;color:#B23B3B;font-size:13px;">
  ⚠️ {{api_error}}
</div>
{% endif %}

{% if matches %}'''

if old_banner_anchor not in content:
    print("ГРЕШКА: не намерих мястото за банера в шаблона.")
else:
    content = content.replace(old_banner_anchor, new_banner_anchor)
    print("Банерът за грешка е добавен успешно.")

with open("match_predictor_app.py", "w", encoding="utf-8") as f:
    f.write(content)
