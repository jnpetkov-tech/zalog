import sqlite3
import requests

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

conn = sqlite3.connect("bets.db")
conn.row_factory = sqlite3.Row
pending = conn.execute(
    "SELECT * FROM bets WHERE status='pending' AND (market_code LIKE 'corners_%' OR market_code LIKE 'cards_%' OR market_code LIKE 'offsides_%')"
).fetchall()

print(f"Намерени {len(pending)} чакащи статистически залога\n")

for row in pending:
    print(f"--- ID={row['id']} | market_code='{row['market_code']}' | fixture_id={row['fixture_id']} ---")
    print(f"    Съхранено home_team='{row['home_team']}' away_team='{row['away_team']}'")

    r = requests.get(f"{BASE_URL}/fixtures/statistics", headers=headers, params={"fixture": row["fixture_id"]})
    data = r.json()
    print(f"    errors={data.get('errors')} results={data.get('results')}")

    for team_data in data.get("response", []):
        api_name = team_data["team"]["name"]
        match = "✅ СЪВПАДА" if api_name in (row["home_team"], row["away_team"]) else "❌ НЕ СЪВПАДА"
        print(f"    API име: '{api_name}' {match}")
    print()

conn.close()
