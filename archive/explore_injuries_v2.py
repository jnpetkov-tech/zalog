import requests
import json

FREE_API_KEY = "88b7314ada2fe7d4e7327b55d6d3e1bd"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": FREE_API_KEY}

print("=== Търсене на реалния ID на Лудогорец ===")
r0 = requests.get(f"{BASE_URL}/teams", headers=headers, params={"search": "Ludogorets"})
data0 = r0.json()
print("errors:", data0.get("errors"))
for item in data0.get("response", []):
    print(f"  ID: {item['team']['id']} | {item['team']['name']} | {item['team']['country']}")

print("\n=== /injuries тест на Англия (League 39), сезон 2023 - проверка дали ендпойнтът изобщо работи ===")
r = requests.get(f"{BASE_URL}/injuries", headers=headers, params={"league": 39, "season": 2023})
data = r.json()
print("errors:", data.get("errors"))
print("results:", data.get("results"))
if data.get("response"):
    print(json.dumps(data["response"][0], ensure_ascii=False, indent=2)[:1200])
