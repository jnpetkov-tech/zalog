import requests
import csv
import time
import os
import sys

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

SECOND_DIVISIONS = {
    "england2": ("England", "Championship"),
    "germany2": ("Germany", "2. Bundesliga"),
    "france2": ("France", "Ligue 2"),
    "spain2": ("Spain", "Segunda División"),
    "italy2": ("Italy", "Serie B"),
    "portugal2": ("Portugal", "Segunda Liga"),
    "bulgaria2": ("Bulgaria", "Second League"),
}

SEASONS = [2022, 2023, 2024, 2025]
SAFETY_BUFFER = 300


def check_quota():
    r = requests.get(f"{BASE_URL}/status", headers=headers)
    data = r.json()
    if data.get("response"):
        current = data["response"]["requests"]["current"]
        limit = data["response"]["requests"]["limit_day"]
        return limit - current
    print(f"  [check_quota предупреждение] неочакван отговор от /status: {data}")
    return None


def find_league_id(country, name_search):
    r = requests.get(f"{BASE_URL}/leagues", headers=headers, params={"country": country})
    data = r.json()
    for item in data.get("response", []):
        league = item["league"]
        if league["name"] == name_search:
            return league["id"]
    return None


def fetch_season(league_id, season):
    r = requests.get(f"{BASE_URL}/fixtures", headers=headers,
                      params={"league": league_id, "season": season})
    data = r.json()
    if data.get("errors"):
        print(f"    Грешка: {data['errors']}")
        return []
    return data.get("response", [])


def fetch_history(league_id, name):
    all_rows = []
    for season in SEASONS:
        print(f"  Тегля {name} сезон {season}...")
        fixtures = fetch_season(league_id, season)
        print(f"    -> {len(fixtures)} мача")
        for f in fixtures:
            if f["fixture"]["status"]["short"] != "FT":
                continue
            all_rows.append({
                "fixture_id": f["fixture"]["id"], "season": season,
                "date": f["fixture"]["date"][:10],
                "home_team": f["teams"]["home"]["name"], "away_team": f["teams"]["away"]["name"],
                "home_goals": f["goals"]["home"], "away_goals": f["goals"]["away"],
                "home_ht_goals": f["score"]["halftime"]["home"], "away_ht_goals": f["score"]["halftime"]["away"],
            })
        time.sleep(0.3)

    with open(f"{name}_full_history.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "fixture_id", "season", "date", "home_team", "away_team",
            "home_goals", "away_goals", "home_ht_goals", "away_ht_goals"
        ])
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"  Общо {len(all_rows)} мача записани в {name}_full_history.csv")
    return len(all_rows)


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


def fetch_stats(name):
    progress_file = f"{name}_stats_progress.txt"
    done_ids = set()
    if os.path.exists(progress_file):
        with open(progress_file) as f:
            done_ids = set(line.strip() for line in f)

    with open(f"{name}_full_history.csv", encoding="utf-8") as f:
        fixtures = list(csv.DictReader(f))

    out_path = f"{name}_match_statistics.csv"
    file_exists = os.path.exists(out_path) and os.path.getsize(out_path) > 0
    fieldnames = ["fixture_id", "home_corners", "away_corners", "home_yellow", "away_yellow",
                  "home_red", "away_red", "home_offsides", "away_offsides",
                  "home_possession", "away_possession", "home_shots", "away_shots",
                  "home_shots_on_goal", "away_shots_on_goal", "home_fouls", "away_fouls",
                  "home_expected_goals", "away_expected_goals"]

    with open(out_path, "a", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        remaining = None
        for i, fix in enumerate(fixtures):
            fid = fix["fixture_id"]
            if fid in done_ids:
                continue

            if remaining is None or i % 50 == 0:
                checked = check_quota()
                if checked is not None:
                    remaining = checked
                    if remaining < SAFETY_BUFFER:
                        print(f"  СПИРАМ - остават само {remaining} заявки. Пусни отново утре за продължение.")
                        return False

            stats = fetch_fixture_stats(fid)
            if stats:
                stats["fixture_id"] = fid
                writer.writerow(stats)

            with open(progress_file, "a") as pf:
                pf.write(fid + "\n")

            if i % 100 == 0:
                print(f"    {i}/{len(fixtures)} обработени... (остават {remaining} заявки общо)")
            time.sleep(0.2)

    print(f"  Готово - {name}_match_statistics.csv")
    return True


def merge(name):
    import pandas as pd
    history = pd.read_csv(f"{name}_full_history.csv")
    stats = pd.read_csv(f"{name}_match_statistics.csv")

    for col in ["home_possession", "away_possession"]:
        if col in stats.columns:
            stats[col] = stats[col].astype(str).str.replace("%", "", regex=False)
            stats[col] = pd.to_numeric(stats[col], errors="coerce")

    merged = history.merge(stats, on="fixture_id", how="left")
    merged = merged.rename(columns={"home_expected_goals": "home_xg", "away_expected_goals": "away_xg"})
    merged["home_xg"] = pd.to_numeric(merged["home_xg"], errors="coerce")
    merged["away_xg"] = pd.to_numeric(merged["away_xg"], errors="coerce")

    merged.to_csv(f"{name}_merged_full.csv", index=False)
    matched = merged["home_corners"].notna().sum()
    print(f"  {name}: {len(merged)} мача общо, {matched} с пълна статистика")


def main():
    for name, (country, league_name) in SECOND_DIVISIONS.items():
        print(f"\n{'='*60}\n{name.upper()} ({league_name}, {country})\n{'='*60}")

        remaining = check_quota()
        print(f"Оставащ дневен лимит: {remaining}")
        if remaining < SAFETY_BUFFER:
            print(f"НЕДОСТАТЪЧЕН ЛИМИТ ({remaining}) - спирам напълно. Пусни скрипта пак утре.")
            sys.exit(0)

        league_id = find_league_id(country, league_name)
        if league_id is None:
            print(f"НЕ намерих ID за {league_name} в {country} - пропускам.")
            continue
        print(f"Намерен ID: {league_id}")

        if not os.path.exists(f"{name}_full_history.csv"):
            fetch_history(league_id, name)
        else:
            print(f"  {name}_full_history.csv вече съществува, пропускам тегленето на история.")

        success = fetch_stats(name)
        if not success:
            print(f"Спрях по средата на {name} заради лимита. Скриптът е resumable - пусни го пак утре.")
            sys.exit(0)

        merge(name)

    print("\n\nВСИЧКИ ВТОРИ ДИВИЗИИ ГОТОВИ.")


if __name__ == "__main__":
    main()
