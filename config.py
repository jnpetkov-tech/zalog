"""
config.py — единственото място, което чете тайните (API-Football ключ,
парола за вход, refresh token за нощните задачи, Flask session ключ) от
диска. Останалият код ги вика оттук (`import config`), никой файл не
дефинира собствено копие -
25.08.2026, по искане на Дака: "извади ключа и паролата от кода... сегашният
ключ и сегашната парола остават, само мястото им се променя."

Стойностите живеят в `.env` (един ред до този файл, извън git - вижте
.gitignore и .env.example за формата). Systemd услугите/cron скриптовете
НЕ се нуждаят от собствена конфигурация (EnvironmentFile= и т.н. в unit
файловете) - този модул чете `.env` директно от диска по АБСОЛЮТЕН път
(извлечен от __file__, не от cwd), затова работи еднакво независимо дали
процесът е стартиран от gunicorn, systemd (oneshot units), cron скрипт
или ръчно от терминала.

Ако липсва .env или в него липсва някоя от трите стойности - гръмва
веднага при import, с ясно съобщение къде да се провери. Предпочетено
пред тихо продължаване с None (би счупило API извикванията много по-
трудно за диагностициране).
"""
import os

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load_env(path):
    values = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


try:
    _values = _load_env(_ENV_PATH)
except FileNotFoundError:
    raise RuntimeError(
        f"Липсва {_ENV_PATH} — тайните (API ключ/парола/refresh token) не могат да се заредят. "
        "Виж .env.example в същата папка за очаквания формат."
    )


def _require(name):
    value = _values.get(name)
    if not value:
        raise RuntimeError(f"{name} липсва или е празен в {_ENV_PATH}")
    return value


API_KEY = _require("API_FOOTBALL_KEY")
LOGIN_PASSWORD = _require("LOGIN_PASSWORD")
REFRESH_TOKEN = _require("REFRESH_TOKEN")
FLASK_SECRET_KEY = _require("FLASK_SECRET_KEY")
