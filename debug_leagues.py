import requests

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

for name in ["Bundesliga", "Serie A", "La Liga"]:
    url = f"{BASE_URL}/leagues"
    params = {"search": name}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()
    print(f"\n--- Търсене: '{name}' ---")
    print("errors:", data.get("errors"))
    print("results:", data.get("results"))
    for item in data.get("response", [])[:5]:
        print(f"  ID: {item['league']['id']} | {item['league']['name']} | {item['country']['name']} | type: {item['league']['type']}")
