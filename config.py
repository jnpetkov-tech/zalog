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

# ZADACHA_ZHIVO (01.10.2026): превключвател за обучения слой в живата прогноза (layer_live.py). 1 = слоят влиза; 0/липсва = точно старото
# поведение (ядрото). Незадължителен (за разлика от тайните по-горе). Чете се еднократно при старт на процеса (Flask - след рестарт;
# build_predictions_snapshot.py - при всеки пуск).
LAYER_LIVE = _values.get("LAYER_LIVE", "0").strip() == "1"

# ZADACHA_RAZVITIE т.1 (02.10.2026): малък ред с деня ("Нд, 4 окт") над часа на картата на мача. 1 = показва се (по подразбиране);
# 0 = точно старото. Чете се при старт на Flask.
SHOW_MATCH_DAY = _values.get("SHOW_MATCH_DAY", "1").strip() != "0"

# ZADACHA_RAZVITIE т.2 (02.10.2026): история на коефициентите (odds_history_collect.py, само вътрешно мерило). 1 = записва; 0/липсва = нищо.
ODDS_LOG = _values.get("ODDS_LOG", "0").strip() == "1"

# ZADACHA_RAZVITIE т.7 (02.10.2026): фоново загряване на /results малко след старта на Flask (web/results.py). 1 = да (по подразбиране); 0 = не.
RESULTS_WARMUP = _values.get("RESULTS_WARMUP", "1").strip() != "0"

# ZADACHA_RAZVITIE т.4 (02.10.2026): окончателна прогноза по съставите (набор ABC от layer_shadow 'final') в живата прогноза - layer_live.py.
# 1 = да (само ако и LAYER_LIVE=1); 0/липсва = точно старото. Flask - след рестарт; снимката - при следващия цикъл.
LAYER_FINAL_LIVE = _values.get("LAYER_FINAL_LIVE", "0").strip() == "1"

# ZADACHA_RAZVITIE т.5 (02.10.2026): новите пазари на страницата на мача (extra_markets.py; над/под 1.5, точен резултат, полувреме, пръв гол).
# 1 = показват се; 0/липсва = точно старото. Снимката (самостоятелна) - при следващия цикъл; Flask (шаблонът) - след рестарт.
EXTRA_MARKETS = _values.get("EXTRA_MARKETS", "0").strip() == "1"

# ZADACHA_VSICHKO (02.10.2026): страницата на мача показва ВСИЧКИ пазари, които моделът смята, с етикет "проверен"/"експериментален"
# (web/prognozi.py build_all_sections, extra_markets.py). 1 = да; 0/липсва = точно старото. Снимката - при следващия цикъл; Flask - след рестарт.
SHOW_ALL = _values.get("SHOW_ALL", "0").strip() == "1"
