import sqlite3
import requests

conn = sqlite3.connect("bets.db")
conn.row_factory = sqlite3.Row
pending = conn.execute("SELECT * FROM bets WHERE status='pending'").fetchall()

print(f"Общо чакащи: {len(pending)}\n")

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

seen_fixtures = {}
for row in pending:
    fid = row["fixture_id"]
    if fid not in seen_fixtures:
        r = requests.get(f"{BASE_URL}/fixtures", headers=headers, params={"id": fid})
        data = r.json()
        if data.get("response"):
            fixture = data["response"][0]
            seen_fixtures[fid] = fixture["fixture"]["status"]["short"]
        else:
            seen_fixtures[fid] = f"НЯМА ОТГОВОР: {data.get('errors')}"

    print(f"ID={row['id']} | market_code='{row['market_code']}' | fixture_id={fid} | статус на мача: {seen_fixtures[fid]}")

conn.close()
