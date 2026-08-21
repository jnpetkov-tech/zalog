import sys
sys.path.insert(0, "/home/inkas/sportbg-predictor")
import sqlite3
import json
import requests
import match_predictor_app as mpa

conn = sqlite3.connect("predictions.db")
row = conn.execute("SELECT fixture_id FROM odds_cache LIMIT 1").fetchone()
conn.close()

if not row:
    print("Няма кеширани fixture_id-та в odds_cache - ще пробвам директно с известен fixture.")
    fixture_id = None
else:
    fixture_id = row[0]

print(f"Използвам fixture_id={fixture_id}")

r = requests.get(f"{mpa.BASE_URL}/odds", headers=mpa.API_HEADERS,
                  params={"fixture": fixture_id}, timeout=10)
data = r.json()

if data.get("errors") or not data.get("response"):
    print("Няма отговор/грешка:", data.get("errors"))
else:
    bookmaker_block = data["response"][0]["bookmakers"][0] if data["response"][0].get("bookmakers") else None
    if not bookmaker_block:
        print("Няма bookmaker данни за този мач.")
    else:
        print(f"Bookmaker: {bookmaker_block.get('name')}")
        print(f"Общо bet типове: {len(bookmaker_block.get('bets', []))}")
        for bet in bookmaker_block.get("bets", []):
            values = [v["value"] for v in bet.get("values", [])]
            print(f"  name={bet['name']!r} id={bet.get('id')} values={values}")
