import pandas as pd

history = pd.read_csv("bulgaria_full_history.csv")
stats = pd.read_csv("bulgaria_match_statistics.csv")

stats["possession"] = stats["possession"].astype(str).str.replace("%", "", regex=False)
stats["possession"] = pd.to_numeric(stats["possession"], errors="coerce")

merged_rows = []
for fixture_id, group in stats.groupby("fixture_id"):
    if len(group) != 2:
        continue
    hist_row = history[history["fixture_id"] == fixture_id]
    if hist_row.empty:
        continue
    hist_row = hist_row.iloc[0]

    home_team = hist_row["home_team"]
    away_team = hist_row["away_team"]

    home_stats = group[group["team"] == home_team]
    away_stats = group[group["team"] == away_team]
    if home_stats.empty or away_stats.empty:
        continue
    home_stats = home_stats.iloc[0]
    away_stats = away_stats.iloc[0]

    merged_rows.append({
        "fixture_id": fixture_id,
        "season": hist_row["season"],
        "date": hist_row["date"],
        "home_team": home_team,
        "away_team": away_team,
        "home_goals": hist_row["home_goals"],
        "away_goals": hist_row["away_goals"],
        "home_ht_goals": hist_row["home_ht_goals"],
        "away_ht_goals": hist_row["away_ht_goals"],
        "home_xg": home_stats["expected_goals"],
        "away_xg": away_stats["expected_goals"],
        "home_corners": home_stats["corners"],
        "away_corners": away_stats["corners"],
        "home_yellow": home_stats["yellow_cards"],
        "away_yellow": away_stats["yellow_cards"],
        "home_red": home_stats["red_cards"],
        "away_red": away_stats["red_cards"],
        "home_shots": home_stats["total_shots"],
        "away_shots": away_stats["total_shots"],
        "home_shots_on_goal": home_stats["shots_on_goal"],
        "away_shots_on_goal": away_stats["shots_on_goal"],
        "home_shots_insidebox": home_stats["shots_insidebox"],
        "away_shots_insidebox": away_stats["shots_insidebox"],
        "home_possession": home_stats["possession"],
        "away_possession": away_stats["possession"],
        "home_fouls": home_stats["fouls"],
        "away_fouls": away_stats["fouls"],
        "home_offsides": home_stats["offsides"],
        "away_offsides": away_stats["offsides"],
        "home_saves": home_stats["saves"],
        "away_saves": away_stats["saves"],
        "home_passes": home_stats["total_passes"],
        "away_passes": away_stats["total_passes"],
        "home_passes_accurate": home_stats["passes_accurate"],
        "away_passes_accurate": away_stats["passes_accurate"],
    })

merged = pd.DataFrame(merged_rows)
merged["home_xg"] = pd.to_numeric(merged["home_xg"], errors="coerce")
merged["away_xg"] = pd.to_numeric(merged["away_xg"], errors="coerce")

merged.to_csv("bulgaria_merged_full.csv", index=False)
print(f"Общо мачове: {len(merged)}")
print(f"Колони: {list(merged.columns)}")
