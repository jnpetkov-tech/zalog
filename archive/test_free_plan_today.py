import requests
from datetime import date, timedelta

FREE_API_KEY = "88b7314ada2fe7d4e7327b55d6d3e1bd"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": FREE_API_KEY}

today = date.today()
to_date = today + timedelta(days=7)

print(f"Днешна дата: {today}\n")

# Тест 1: Първа лига България, текущ сезон
print("=== Тест: Първа лига България (ID 172), сезон 2025 ===")
params = {
    "league": 172,
    "season": 2025,
    "from": today.isoformat(),
    "to": to_date.isoformat(),
}
r = requests.get(f"{BASE_URL}/fixtures", headers=headers, params=params)
data = r.json()
print("errors:", data.get("errors"))
print("results:", data.get("results"))
if data.get("response"):
    print(f"Намерени {len(data['response'])} предстоящи мача!")

# Тест 2: директна проверка на достъпните сезони точно СЕГА
print("\n=== Проверка кои сезони вижда безплатният план в момента ===")
r2 = requests.get(f"{BASE_URL}/leagues", headers=headers, params={"id": 172})
data2 = r2.json()
if data2.get("response"):
    seasons = data2["response"][0]["seasons"]
    for s in seasons[-4:]:
        print(f"  Сезон {s['year']}: fixtures={s.get('coverage',{}).get('fixtures',{}).get('events')}")
