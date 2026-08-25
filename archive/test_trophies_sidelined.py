import requests

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

# взимаме реален играч от Лудогорец (team_id=566), сезон 2025
r = requests.get(f"{BASE_URL}/players", headers=headers, params={"team": 566, "season": 2025})
data = r.json()
print("errors:", data.get("errors"), "| results:", data.get("results"))

if data.get("response"):
    player = data["response"][0]["player"]
    player_id = player["id"]
    print(f"Тестов играч: {player['name']} (ID: {player_id})\n")

    print("=== /trophies с player ID ===")
    r2 = requests.get(f"{BASE_URL}/trophies", headers=headers, params={"player": player_id})
    data2 = r2.json()
    print("errors:", data2.get("errors"), "| results:", data2.get("results"))
    if data2.get("response"):
        print(data2["response"][:2])

    print("\n=== /sidelined с player ID ===")
    r3 = requests.get(f"{BASE_URL}/sidelined", headers=headers, params={"player": player_id})
    data3 = r3.json()
    print("errors:", data3.get("errors"), "| results:", data3.get("results"))
    if data3.get("response"):
        print(data3["response"][:2])
