import requests

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

url = f"{BASE_URL}/leagues"
params = {"id": 39}
r = requests.get(url, headers=headers, params=params)
data = r.json()

seasons = data["response"][0]["seasons"]
print("Всички сезони за Premier League (ID 39):\n")
for s in seasons:
    coverage = s.get("coverage", {})
    print(f"  Сезон {s['year']} | fixtures: {coverage.get('fixtures', {}).get('events', 'N/A')} | статистики: {coverage.get('fixtures', {}).get('statistics_fixtures', 'N/A')}")

print("\nПробвам реална заявка за 2023, за да видя дали безплатният план го позволява...")
url2 = f"{BASE_URL}/fixtures"
params2 = {"league": 39, "season": 2023, "status": "FT"}
r2 = requests.get(url2, headers=headers, params=params2)
data2 = r2.json()
print("errors:", data2.get("errors"))
print("results:", data2.get("results"))
