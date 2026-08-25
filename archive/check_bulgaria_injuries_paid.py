import requests

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

for season in [2022, 2023, 2024, 2025]:
    r = requests.get(f"{BASE_URL}/injuries", headers=headers, params={"league": 172, "season": season})
    data = r.json()
    print(f"Сезон {season}: errors={data.get('errors')}, results={data.get('results')}")
