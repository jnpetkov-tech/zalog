import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old_nav = '''  <a href="/daily" class="{% if active_page=='daily' %}active{% endif %}">📅 Предстоящи</a>
  <a href="/results" class="{% if active_page=='results' %}active{% endif %}">📋 Резултати и ефективност</a>
  <div class="sidebar-section">Инструменти</div>'''

new_nav = '''  <a href="/daily" class="{% if active_page=='daily' %}active{% endif %}">📅 Предстоящи</a>
  <a href="/value" class="{% if active_page=='value' %}active{% endif %}">💰 Стойност</a>
  <a href="/results" class="{% if active_page=='results' %}active{% endif %}">📋 Резултати и ефективност</a>
  <div class="sidebar-section">Инструменти</div>'''

assert content.count(old_nav) == 1, f"nav anchor count: {content.count(old_nav)}"
content = content.replace(old_nav, new_nav, 1)

old_register = '''from results_view import register_results_view
register_results_view(app, {
    "BASE_STYLE": BASE_STYLE, "SIDEBAR_STYLE": SIDEBAR_STYLE, "SIDEBAR_HTML": SIDEBAR_HTML,
    "ALL_LEAGUES": ALL_LEAGUES, "LEAGUE_FLAGS": LEAGUE_FLAGS, "market_label": market_label,
    "to_cyrillic": to_cyrillic, "st": st, "bt": bt,
})

if __name__ == "__main__":'''

new_register = '''from results_view import register_results_view
register_results_view(app, {
    "BASE_STYLE": BASE_STYLE, "SIDEBAR_STYLE": SIDEBAR_STYLE, "SIDEBAR_HTML": SIDEBAR_HTML,
    "ALL_LEAGUES": ALL_LEAGUES, "LEAGUE_FLAGS": LEAGUE_FLAGS, "market_label": market_label,
    "to_cyrillic": to_cyrillic, "st": st, "bt": bt,
})
from value_view import register_value_view
register_value_view(app, {
    "BASE_STYLE": BASE_STYLE, "SIDEBAR_STYLE": SIDEBAR_STYLE, "SIDEBAR_HTML": SIDEBAR_HTML,
    "ALL_LEAGUES": ALL_LEAGUES, "LEAGUE_FLAGS": LEAGUE_FLAGS, "market_label": market_label,
    "to_cyrillic": to_cyrillic, "st": st, "policy": policy,
})

if __name__ == "__main__":'''

assert content.count(old_register) == 1, f"register anchor count: {content.count(old_register)}"
content = content.replace(old_register, new_register, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - value_view закачен (nav линк + register_value_view)")
