import time
import sys
sys.path.insert(0, '.')

from match_predictor_app import get_models, ALL_LEAGUES

for league in ALL_LEAGUES.keys():
    print(f"Зареждам {league}...")
    start = time.time()
    try:
        get_models(league)
        elapsed = time.time() - start
        print(f"  {league}: OK за {elapsed:.1f} сек\n")
    except Exception as e:
        elapsed = time.time() - start
        print(f"  {league}: ГРЕШКА след {elapsed:.1f} сек - {e}\n")

print("Готово с пълната диагностика.")
