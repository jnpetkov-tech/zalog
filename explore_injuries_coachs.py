import requests
import json

FREE_API_KEY = "88b7314ada2fe7d4e7327b55d6d3e1bd"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": FREE_API_KEY}

print("=== /injuries - структура на данните (сезон 2023, в обхвата на безплатния план) ===")
r = requests.get(f"{BASE_URL}/injuries", headers=headers, params={"league": 172, "season": 2023})
data = r.json()
print("errors:", data.get("errors"))
print("results:", data.get("results"))
if data.get("response"):
    print(json.dumps(data["response"][0], ensure_ascii=False, indent=2))

print("\n=== /coachs - структура на данните ===")
r2 = requests.get(f"{BASE_URL}/coachs", headers=headers, params={"team": 1913})
data2 = r2.json()
print("errors:", data2.get("errors"))
print("results:", data2.get("results"))
if data2.get("response"):
    print(json.dumps(data2["response"][0], ensure_ascii=False, indent=2)[:1500])
