import ast

PATH = "match_predictor_app.py"

with open(PATH, encoding="utf-8") as f:
    content = f.read()

# 1. Add helper + make /refresh_all wait briefly and show short confirmation
old1 = '''@app.route("/refresh_all", methods=["POST"])
def refresh_all_route():
    thread = threading.Thread(target=run_refresh_all, daemon=True)
    thread.start()
    return redirect(url_for("refresh_status"))


def run_refresh_odds_cache():'''
assert content.count(old1) == 1, "1: refresh_all route anchor not found or not unique"

new1 = '''def render_refresh_confirmation(done, label):
    message = f"✅ {label}" if done else "🔄 Стартирано, продължава на фон"
    return f"""<!DOCTYPE html><html lang="bg"><head><meta charset="UTF-8"><title>Опресняване</title>
<style>{BASE_STYLE}</style></head><body><div class="container" style="max-width:400px;text-align:center;padding-top:80px;">
<div style="font-size:20px;color:var(--text);margin-bottom:20px;">{message}</div>
<a href="/" style="color:var(--accent);text-decoration:none;font-size:14px;">← Начало</a>
<span style="color:var(--sub);margin:0 8px;">·</span>
<a href="/refresh_status" style="color:var(--sub);text-decoration:none;font-size:14px;">Пълен лог →</a>
</div></body></html>"""


@app.route("/refresh_all", methods=["POST"])
def refresh_all_route():
    thread = threading.Thread(target=run_refresh_all, daemon=True)
    thread.start()
    thread.join(timeout=6)
    return render_refresh_confirmation(not thread.is_alive(), "Опреснени всички лиги")


def run_refresh_odds_cache():'''

content = content.replace(old1, new1)

# 2. Make /refresh_odds_cache_manual wait briefly and show short confirmation
old2 = '''@app.route("/refresh_odds_cache_manual", methods=["POST"])
def refresh_odds_cache_manual_route():
    thread = threading.Thread(target=run_refresh_odds_cache, daemon=True)
    thread.start()
    return redirect(url_for("refresh_status"))'''
assert content.count(old2) == 1, "2: refresh_odds_cache_manual anchor not found or not unique"

new2 = '''@app.route("/refresh_odds_cache_manual", methods=["POST"])
def refresh_odds_cache_manual_route():
    thread = threading.Thread(target=run_refresh_odds_cache, daemon=True)
    thread.start()
    thread.join(timeout=6)
    return render_refresh_confirmation(not thread.is_alive(), "Готово")'''

content = content.replace(old2, new2)

ast.parse(content)

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("OK - both replacements applied, written.")
