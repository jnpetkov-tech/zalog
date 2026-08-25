import requests

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

r = requests.get(f"{BASE_URL}/leagues", headers=headers, params={"country": "Italy"})
data = r.json()
for item in data.get("response", []):
    league = item["league"]
    if league["type"] == "League":
        print(f"  ID: {league['id']} | {league['name']}")
