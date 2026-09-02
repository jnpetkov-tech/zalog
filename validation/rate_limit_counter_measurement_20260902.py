import sys
sys.path.insert(0, "/home/inkas/sportbg-predictor")
import requests
import api_football as af
import config

fixture_id = 1551095  # real pending fixture_id от predictions.db, 02.09.2026

print("--- ПРЕДИ поправката: директен requests.get, заобикаля _api_get ---")
af.reset_call_count()
r = requests.get(f"{af.BASE_URL}/injuries", headers=af.API_HEADERS,
                  params={"fixture": fixture_id}, timeout=10)
print("HTTP статус:", r.status_code, "| _api_get брояч след реална заявка:", af.get_call_count())

print()
print("--- СЛЕД поправката: през fetch_fixture_injuries() -> _api_get() ---")
af.reset_call_count()
home, away, ok = af.fetch_fixture_injuries(fixture_id)
print("home/away/ok:", home, away, ok, "| _api_get брояч след реална заявка:", af.get_call_count())

print()
print("--- system_tracker пътят: /fixtures през _api_get() ---")
af.reset_call_count()
r2 = af._api_get("/fixtures", params={"id": fixture_id})
data = r2.json()
print("response items:", len(data.get("response", [])), "| _api_get брояч:", af.get_call_count())
