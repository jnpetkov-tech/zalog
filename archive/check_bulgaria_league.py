"""
Проверка: има ли Първа лига България в API-Football?
"""

import requests
import json

API_KEY = "ae492089a88c8668057a60b30eee49e0"

BASE_URL = "https://v3.football.api-sports.io"

headers = {
    "x-apisports-key": API_KEY
}

def search_leagues(query):
    url = f"{BASE_URL}/leagues"
    params = {"search": query}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def main():
    print("Търсене на 'Bulgaria'...\n")
    data = search_leagues("Bulgaria")

    results = data.get("response", [])
    if not results:
        print("Няма намерени лиги с търсене 'Bulgaria'.")
    else:
        print(f"Намерени {len(results)} резултата:\n")
        for item in results:
            league = item["league"]
            country = item["country"]
            print(f"League ID: {league['id']}")
            print(f"Име: {league['name']}")
            print(f"Тип: {league['type']}")
            print(f"Държава: {country['name']}")
            print("-" * 50)

    with open("bulgaria_leagues_response.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("\nПълният JSON отговор е записан в bulgaria_leagues_response.json")

if __name__ == "__main__":
    main()
