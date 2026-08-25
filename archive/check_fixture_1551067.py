import requests

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

r = requests.get(f"{BASE_URL}/fixtures", headers=headers, params={"id": 1551067})
data = r.json()
if data.get("response"):
    f = data["response"][0]
    print("Домакин:", f["teams"]["home"]["name"])
    print("Гост:", f["teams"]["away"]["name"])
    print("Дата:", f["fixture"]["date"])
    print("Статус:", f["fixture"]["status"]["long"], "(" + f["fixture"]["status"]["short"] + ")")
else:
    print("Няма отговор:", data.get("errors"))
