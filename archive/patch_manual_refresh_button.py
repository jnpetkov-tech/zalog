
import ast

PATH = "match_predictor_app.py"

with open(PATH, encoding="utf-8") as f:
    content = f.read()

# 1. New manual-trigger route (session-authed, redirects to /refresh_status for nicer UX)
old1 = '''@app.route("/refresh_odds_cache", methods=["POST"])
def refresh_odds_cache_route():
    thread = threading.Thread(target=run_refresh_odds_cache, daemon=True)
    thread.start()
    return "OK", 200


@app.route("/refresh_status")'''
assert content.count(old1) == 1, "1: refresh_odds_cache route anchor not found or not unique"

new1 = '''@app.route("/refresh_odds_cache", methods=["POST"])
def refresh_odds_cache_route():
    thread = threading.Thread(target=run_refresh_odds_cache, daemon=True)
    thread.start()
    return "OK", 200


@app.route("/refresh_odds_cache_manual", methods=["POST"])
def refresh_odds_cache_manual_route():
    thread = threading.Thread(target=run_refresh_odds_cache, daemon=True)
    thread.start()
    return redirect(url_for("refresh_status"))


@app.route("/refresh_status")'''

content = content.replace(old1, new1)

# 2. Second button on the home page next to the existing refresh button
old2 = '''<div class="home-refresh-row">
  <form method="post" action="/refresh_all" style="margin:0;">
    <button type="submit" class="home-refresh-btn">🔄 Опресни всички данни</button>
  </form>
  <a href="/refresh_status" style="font-size:13px;color:var(--accent);">Виж прогрес →</a>
</div>'''
assert content.count(old2) == 1, "2: home-refresh-row anchor not found or not unique"

new2 = '''<div class="home-refresh-row">
  <form method="post" action="/refresh_all" style="margin:0;">
    <button type="submit" class="home-refresh-btn">🔄 Опресни всички данни</button>
  </form>
  <form method="post" action="/refresh_odds_cache_manual" style="margin:0;">
    <button type="submit" class="home-refresh-btn">💰 Опресни пазарни коефициенти</button>
  </form>
  <a href="/refresh_status" style="font-size:13px;color:var(--accent);">Виж прогрес →</a>
</div>'''

content = content.replace(old2, new2)

ast.parse(content)

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("OK - both replacements applied, written.")
