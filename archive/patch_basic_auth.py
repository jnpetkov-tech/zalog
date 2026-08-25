with open("match_predictor_app.py", encoding="utf-8") as f:
    content = f.read()

old = '''app = Flask(__name__)

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")'''

new = '''app = Flask(__name__)

BASIC_AUTH_USERNAME = "sportbg"
BASIC_AUTH_PASSWORD = os.environ.get("LOGIN_PASSWORD", "")


def check_auth(username, password):
    return username == BASIC_AUTH_USERNAME and password == BASIC_AUTH_PASSWORD


@app.before_request
def require_auth():
    from flask import Response
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return Response(
            "Достъп отказан - нужна е парола.", 401,
            {"WWW-Authenticate": 'Basic realm="Sportbg Zalozi"'}
        )


API_KEY = os.environ.get("API_FOOTBALL_KEY", "")'''

if old not in content:
    print("ГРЕШКА: не намерих реда.")
else:
    content = content.replace(old, new)
    with open("match_predictor_app.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Basic Auth добавена успешно.")
