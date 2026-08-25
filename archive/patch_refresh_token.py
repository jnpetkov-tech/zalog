import ast

PATH = "match_predictor_app.py"

with open(PATH, encoding="utf-8") as f:
    content = f.read()

old_secret_block = '''app.permanent_session_lifetime = timedelta(days=30)
LOGIN_PASSWORD = os.environ.get("LOGIN_PASSWORD", "")'''
assert content.count(old_secret_block) == 1, "secret block anchor not found or not unique"

new_secret_block = '''app.permanent_session_lifetime = timedelta(days=30)
LOGIN_PASSWORD = os.environ.get("LOGIN_PASSWORD", "")
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN", "")'''

content = content.replace(old_secret_block, new_secret_block)

old_require_auth = '''@app.before_request
def require_auth():
    from flask import session
    if request.endpoint == "login" or request.path.startswith("/static"):
        return
    if not session.get("authed"):
        return redirect(url_for("login", next=request.path))'''
assert content.count(old_require_auth) == 1, "require_auth anchor not found or not unique"

new_require_auth = '''@app.before_request
def require_auth():
    from flask import session
    if request.endpoint == "login" or request.path.startswith("/static"):
        return
    if request.path == "/refresh_odds_cache":
        if request.headers.get("X-Refresh-Token") == REFRESH_TOKEN:
            return
        return redirect(url_for("login", next=request.path))
    if not session.get("authed"):
        return redirect(url_for("login", next=request.path))'''

content = content.replace(old_require_auth, new_require_auth)

ast.parse(content)

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("OK - written, syntax valid.")
