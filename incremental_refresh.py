import requests
import pandas as pd
import sys
import time
from datetime import date

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


def main(league_key, league_id):
    merged_path = f"{league_key}_merged_full.csv"
    try:
        existing = pd.read_csv(merged_path)
    except FileNotFoundError:
        print(f"ГРЕШКА: {merged_path} не съществува. Направи първо пълно теглене за тази лига.")
        return

    existing["date"] = pd.to_datetime(existing["date"].astype(str).str[:10])
    last_date = existing["date"].max().date()
    existing_ids = set(existing["fixture_id"].astype(int))

    today = date.today()
    if last_date >= today:
        print(f"{league_key}: вече е актуален (последна дата {last_date}). Няма нужда от опресняване.")
        return

    season = today.year if today.month >= 7 else today.year - 1
    print(f"{league_key}: последна дата в данните {last_date}, тегля от {last_date} до {today} (сезон {season})...")

    r = requests.get(f"{BASE_URL}/fixtures", headers=headers,
                      params={"league": league_id, "season": season,
                              "from": last_date.isoformat(), "to": today.isoformat()})
    data = r.json()
    if data.get("errors"):
        print(f"  Грешка: {data['errors']}")
        return

    fixtures = data.get("response", [])
    new_fixtures = [f for f in fixtures
                     if f["fixture"]["status"]["short"] == "FT"
                     and f["fixture"]["id"] not in existing_ids]

    print(f"  Намерени {len(fixtures)} мача в периода, {len(new_fixtures)} са реално нови и завършени.")

    if not new_fixtures:
        print(f"{league_key}: няма нови завършени мачове за добавяне.")
        return

    new_rows = []
    for f in new_fixtures:
        fid = f["fixture"]["id"]
        print(f"  Тегля статистика за нов мач {fid}...")
        stats = fetch_fixture_stats(fid)

        row = {
            "fixture_id": fid, "season": season, "date": f["fixture"]["date"][:10],
            "home_team": f["teams"]["home"]["name"], "away_team": f["teams"]["away"]["name"],
            "home_goals": f["goals"]["home"], "away_goals": f["goals"]["away"],
            "home_ht_goals": f["score"]["halftime"]["home"], "away_ht_goals": f["score"]["halftime"]["away"],
        }
        if stats:
            for k, v in stats.items():
                if k == "home_expected_goals":
                    row["home_xg"] = v
                elif k == "away_expected_goals":
                    row["away_xg"] = v
                else:
                    row[k] = v

        new_rows.append(row)
        time.sleep(0.25)

    new_df = pd.DataFrame(new_rows)

    for col in ["home_possession", "away_possession"]:
        if col in new_df.columns:
            new_df[col] = new_df[col].astype(str).str.replace("%", "", regex=False)
            new_df[col] = pd.to_numeric(new_df[col], errors="coerce")

    combined = pd.concat([existing, new_df], ignore_index=True, sort=False)
    combined.to_csv(merged_path, index=False)

    print(f"{league_key}: добавени {len(new_rows)} нови мача. Общо сега {len(combined)} мача в {merged_path}.")
    print("ЗАБЕЛЕЖКА: колони като контузии (home_injuries/away_injuries) НЕ се обновяват тук - "
          "нужно е отделно теглене на /injuries, ако искаш и тях актуални.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Употреба: python3 incremental_refresh.py <league_key> <league_id>")
        sys.exit(1)
    main(sys.argv[1], int(sys.argv[2]))
