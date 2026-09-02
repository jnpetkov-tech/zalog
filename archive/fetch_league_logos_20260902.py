"""
archive/fetch_league_logos_20260902.py

Еднократен скрипт (НОЩ 02.09.2026, задача 2, NOSHT2.md): дърпа logo URL за
всяка от 17-те лиги в ALL_LEAGUES през /leagues?id=<id>, ЕДИН път за всяка
(17 заявки общо, не на цикъл). Резултатът се хардкоднат ръчно като "logo"
ключ в ALL_LEAGUES (match_predictor_app.py) - този скрипт не пише в живия
код автоматично, само отпечатва точните низове за копиране, за да остане
ясно кой ред идва оттук (по образец на другите еднократни fetch скриптове
в archive/).

Употреба: python3 archive/fetch_league_logos_20260902.py (от корена на
проекта, за да намери .env/config.py).
"""
import sys
sys.path.insert(0, ".")

from api_football import _api_get

LEAGUE_IDS = {
    "bulgaria": 172, "england": 39, "germany": 78, "spain": 140, "france": 61,
    "champions_league": 2, "europa_league": 3, "conference_league": 848,
    "italy": 135, "portugal": 94, "france2": 62, "spain2": 141, "italy2": 136,
    "portugal2": 95, "bulgaria2": 173, "england2": 40, "germany2": 79,
}

if __name__ == "__main__":
    for key, league_id in LEAGUE_IDS.items():
        r = _api_get("/leagues", {"id": league_id})
        data = r.json()
        resp = data.get("response", []) if data else []
        logo = None
        if resp:
            logo = resp[0].get("league", {}).get("logo")
        print(f'    "{key}": {logo!r},')
