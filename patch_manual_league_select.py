with open("match_predictor_app.py", encoding="utf-8") as f:
    content = f.read()

old = '''  <select name="league">{% for key, name in leagues.items() %}<option value="{{key}}" {% if key==selected_league %}selected{% endif %}>{{name}}</option>{% endfor %}</select>
  <select name="home">'''

new = '''  <select name="league" onchange="this.form.submit()">{% for key, name in leagues.items() %}<option value="{{key}}" {% if key==selected_league %}selected{% endif %}>{{name}}</option>{% endfor %}</select>
  <select name="home">'''

if old not in content:
    print("ГРЕШКА: не намерих реда.")
else:
    content = content.replace(old, new)
    with open("match_predictor_app.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Поправено успешно.")
