import requests

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

# намираме реалния ID на ЦСКА София
r = requests.get(f"{BASE_URL}/teams", headers=headers, params={"search": "CSKA Sofia"})
data = r.json()
print("errors:", data.get("errors"))
for item in data.get("response", []):
    print(f"  ID: {item['team']['id']} | {item['team']['name']} | {item['team']['country']}")

cska_id = None
for item in data.get("response", []):
    if item["team"]["country"] == "Bulgaria" and item["team"]["name"] == "CSKA Sofia":
        cska_id = item["team"]["id"]
        break

if cska_id:
    print(f"\nНамерен ЦСКА София ID: {cska_id}")
    print("\n=== /fixtures/headtohead: Лудогорец (566) vs ЦСКА София ===")
    r2 = requests.get(f"{BASE_URL}/fixtures/headtohead", headers=headers,
                       params={"h2h": f"566-{cska_id}", "last": 10})
    data2 = r2.json()
    print("errors:", data2.get("errors"), "| results:", data2.get("results"))
    for f in data2.get("response", [])[:10]:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        hg = f["goals"]["home"]
        ag = f["goals"]["away"]
        date = f["fixture"]["date"][:10]
        print(f"  {date}: {home} {hg}-{ag} {away}")
else:
    print("Не намерих ЦСКА София ID")
