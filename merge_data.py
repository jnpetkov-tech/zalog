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
    })

merged = pd.DataFrame(merged_rows)
merged["home_xg"] = pd.to_numeric(merged["home_xg"], errors="coerce")
merged["away_xg"] = pd.to_numeric(merged["away_xg"], errors="coerce")

before = len(merged)
merged_with_xg = merged.dropna(subset=["home_xg", "away_xg"])
print(f"Общо обединени мачове: {before}")
print(f"От тях с валидно xG: {len(merged_with_xg)}")

merged.to_csv("bulgaria_merged_full.csv", index=False)
print(f"\nЗаписано в bulgaria_merged_full.csv")
