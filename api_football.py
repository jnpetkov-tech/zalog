"""
api_football.py — API-Football HTTP клиент, изваден от match_predictor_app.py
(ARCHITECTURE.md, Граница 4, втора част, 22.08.2026).

Чисто преместване, не пренаписване: всяка функция тук е преместена бит-по-бит
(сигнатура, timeout-и, параметри) от match_predictor_app.py, без промяна в
поведението. match_predictor_app.py импортира оттук вместо да дефинира
локално - вижте validation/ за преди/след доказателство на всяка стъпка.
"""
import requests

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
API_HEADERS = {"x-apisports-key": API_KEY}
