import re

with open("match_predictor_app.py", encoding="utf-8") as f:
    content = f.read()

old_block = '''  <div class="match-pick-row">
    <span>{{m.pick}} <b>{{"%.1f"|format(m.pct)}}%</b></span>
    <form method="post" action="/place_bet" style="display:inline;">
      <input type="hidden" name="league" value="{{selected_league}}">
      <input type="hidden" name="fixture_id" value="{{m.fixture_id}}">
      <input type="hidden" name="date" value="{{m.date}}">
      <input type="hidden" name="home" value="{{m.home}}">
      <input type="hidden" name="away" value="{{m.away}}">
      <input type="hidden" name="market_code" value="{{m.code}}">
      <input type="hidden" name="pick_label" value="{{m.pick}}">
      <input type="hidden" name="pick_pct" value="{{m.pct}}">
      <button type="submit" class="small green">Направи залог</button>
    </form>
  </div>'''

new_block = '''  <div class="match-pick-row">
    <span>{{m.pick}} <b>{{"%.1f"|format(m.pct)}}%</b></span>
    <button type="submit" formaction="/place_bet_single/{{loop.index0}}" class="small green">Направи залог</button>
  </div>'''

if old_block not in content:
    print("ГРЕШКА: не намерих стария блок - файлът вероятно е бил редактиран другояче.")
else:
    content = content.replace(old_block, new_block)
    print("Блокът е заменен успешно.")

    new_route = '''

@app.route("/place_bet_single/<int:idx>", methods=["POST"])
def place_bet_single_route(idx):
    bt.place_bet(
        request.form[f"league_{idx}"], int(request.form[f"fixture_id_{idx}"]),
        request.form[f"date_{idx}"], request.form[f"home_{idx}"], request.form[f"away_{idx}"],
        request.form[f"code_{idx}"], request.form[f"pick_{idx}"], float(request.form[f"pct_{idx}"]),
    )
    league = request.form.get(f"league_{idx}", "bulgaria")
    return redirect(url_for("daily", league=league))
'''
    marker = '@app.route("/place_combo", methods=["POST"])'
    if marker in content:
        content = content.replace(marker, new_route.strip() + "\n\n\n" + marker)
        print("Новият route е добавен успешно.")
    else:
        print("ГРЕШКА: не намерих мястото за новия route.")

    with open("match_predictor_app.py", "w", encoding="utf-8") as f:
        f.write(content)
