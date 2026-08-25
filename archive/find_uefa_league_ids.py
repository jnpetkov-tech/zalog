import requests

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

for name in ["Champions League", "Europa League", "Conference League"]:
    r = requests.get(f"{BASE_URL}/leagues", headers=headers, params={"search": name})
    data = r.json()
    print(f"\n=== Търсене: '{name}' ===")
    for item in data.get("response", []):
        league = item["league"]
        country = item["country"]["name"]
        if league["type"] == "Cup" and ("UEFA" in country or country == "World"):
            print(f"  ID: {league['id']} | {league['name']} | {country} | type: {league['type']}")
