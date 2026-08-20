import requests
import pandas as pd
import csv
import time
import os
import sys

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}
SAFETY_BUFFER = 200


def check_quota():
    r = requests.get(f"{BASE_URL}/status", headers=HEADERS)
    data = r.json()
    if data.get("response"):
        return data["response"]["requests"]["limit_day"] - data["response"]["requests"]["current"]
    return 0


def fetch_fixture_players(fixture_id):
    try:
        r = requests.get(f"{BASE_URL}/fixtures/players", headers=HEADERS,
                          params={"fixture": fixture_id}, timeout=15)
        data = r.json()
        if data.get("errors") or not data.get("response"):
            return []
        rows = []
        for team_block in data["response"]:
            team_name = team_block["team"]["name"]
            for p in team_block["players"]:
                stats = p["statistics"][0] if p["statistics"] else {}
                games = stats.get("games", {}) or {}
                goals = stats.get("goals", {}) or {}
                cards = stats.get("cards", {}) or {}
                rows.append({
                    "fixture_id": fixture_id,
                    "team": team_name,
                    "player_name": p["player"]["name"],
                    "player_id": p["player"]["id"],
                    "minutes": games.get("minutes"),
                    "position": games.get("position"),
                    "goals": goals.get("total"),
                    "assists": goals.get("assists"),
                    "yellow_cards": cards.get("yellow"),
                    "red_cards": cards.get("red"),
                })
        return rows
    except Exception as e:
        print(f"    грешка при fixture {fixture_id}: {e}")
        return []


def main(league_key, min_season):
    df = pd.read_csv(f"{league_key}_merged_full.csv")
    df = df[df["season"] >= min_season]
    fixture_ids = df["fixture_id"].tolist()

    progress_file = f"{league_key}_player_stats_progress.txt"
    done_ids = set()
    if os.path.exists(progress_file):
        with open(progress_file) as f:
            done_ids = set(int(line.strip()) for line in f if line.strip())

    out_file = f"{league_key}_player_stats.csv"
    file_exists = os.path.exists(out_file)
    fieldnames = ["fixture_id", "team", "player_name", "player_id", "minutes",
                  "position", "goals", "assists", "yellow_cards", "red_cards"]

    todo = [fid for fid in fixture_ids if fid not in done_ids]
    print(f"{league_key}: общо {len(fixture_ids)} мача, вече готови {len(done_ids)}, остават {len(todo)}")

    with open(out_file, "a", newline="", encoding="utf-8") as out_f, \
         open(progress_file, "a") as pf:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for i, fixture_id in enumerate(todo):
            if i % 50 == 0:
                remaining = check_quota()
                print(f"    {i}/{len(todo)} обработени... (остават {remaining} заявки)")
                if remaining < SAFETY_BUFFER:
                    print(f"НЕДОСТАТЪЧЕН ЛИМИТ ({remaining}) - спирам. Пусни пак утре.")
                    sys.exit(0)

            rows = fetch_fixture_players(fixture_id)
            for row in rows:
                writer.writerow(row)
            out_f.flush()
            pf.write(f"{fixture_id}\n")
            pf.flush()
            time.sleep(0.15)

    print(f"{league_key}: готово.")


if __name__ == "__main__":
    league_key = sys.argv[1] if len(sys.argv) > 1 else "bulgaria"
    min_season = int(sys.argv[2]) if len(sys.argv) > 2 else 2024
    main(league_key, min_season)
