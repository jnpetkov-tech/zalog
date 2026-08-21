import requests
import json

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

url = f"{BASE_URL}/fixtures"
params = {"league": 172, "season": 2025, "status": "FT"}
r = requests.get(url, headers=headers, params=params)

print("HTTP статус код:", r.status_code)
print("\nRate limit headers:")
for k, v in r.headers.items():
    if "ratelimit" in k.lower() or "requests" in k.lower():
        print(f"  {k}: {v}")

data = r.json()
print("\nresults:", data.get("results"))
print("errors:", data.get("errors"))
print("paging:", data.get("paging"))
