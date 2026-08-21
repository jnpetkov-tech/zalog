import requests
import csv
import time
import sys
import os

API_KEY = "ae492089a88c8668057a60b30eee49e0"
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}


def fetch_fixture_stats(fixture_id):
    r = requests.get(f"{BASE_URL}/fixtures/statistics", headers=headers,
                      params={"fixture": fixture_id})
    data = r.json()
    if not data.get("response") or len(data["response"]) < 2:
        return None

    def get_stat(team_stats, type_name):
        for s in team_stats.get("statistics", []):
            if s["type"] == type_name:
                return s["value"]
        return None

    result = {}
    for i, side in enumerate(["home", "away"]):
        team_data = data["response"][i]
        result[f"{side}_corners"] = get_stat(team_data, "Corner Kicks")
        result[f"{side}_yellow"] = get_stat(team_data, "Yellow Cards")
        result[f"{side}_red"] = get_stat(team_data, "Red Cards")
        result[f"{side}_offsides"] = get_stat(team_data, "Offsides")
        result[f"{side}_possession"] = get_stat(team_data, "Ball Possession")
        result[f"{side}_shots"] = get_stat(team_data, "Total Shots")
        result[f"{side}_shots_on_goal"] = get_stat(team_data, "Shots on Goal")
        result[f"{side}_fouls"] = get_stat(team_data, "Fouls")
        result[f"{side}_expected_goals"] = get_stat(team_data, "expected_goals")

    return result


def main(country_name):
    progress_file = f"{country_name}_stats_progress.txt"
    done_ids = set()
    if os.path.exists(progress_file):
        with open(progress_file) as f:
            done_ids = set(line.strip() for line in f)

    with open(f"{country_name}_full_history.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fixtures = list(reader)

    out_path = f"{country_name}_match_statistics.csv"
    file_exists = os.path.exists(out_path)
    fieldnames = ["fixture_id", "home_corners", "away_corners", "home_yellow", "away_yellow",
                  "home_red", "away_red", "home_offsides", "away_offsides",
                  "home_possession", "away_possession", "home_shots", "away_shots",
                  "home_shots_on_goal", "away_shots_on_goal", "home_fouls", "away_fouls",
                  "home_expected_goals", "away_expected_goals"]

    with open(out_path, "a", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for i, fix in enumerate(fixtures):
            fid = fix["fixture_id"]
            if fid in done_ids:
                continue

            stats = fetch_fixture_stats(fid)
            if stats:
                stats["fixture_id"] = fid
                writer.writerow(stats)

            with open(progress_file, "a") as pf:
                pf.write(fid + "\n")

            if i % 50 == 0:
                print(f"  {i}/{len(fixtures)} обработени...")
            time.sleep(0.25)

    print(f"Готово - {country_name}_match_statistics.csv")


if __name__ == "__main__":
    main(sys.argv[1])
