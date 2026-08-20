import pandas as pd
import sys

COMP_NAME = sys.argv[1]

history = pd.read_csv(f"{COMP_NAME.lower()}_full_history.csv")
stats = pd.read_csv(f"{COMP_NAME.lower()}_match_statistics.csv")

# почистване на possession (идва като "55%" низ)
for col in ["home_possession", "away_possession"]:
    if col in stats.columns:
        stats[col] = stats[col].astype(str).str.replace("%", "", regex=False)
        stats[col] = pd.to_numeric(stats[col], errors="coerce")

merged = history.merge(stats, on="fixture_id", how="left")

# преименуваме expected_goals -> xg, за съвместимост с останалите ни файлове
merged = merged.rename(columns={
    "home_expected_goals": "home_xg",
    "away_expected_goals": "away_xg",
})
merged["home_xg"] = pd.to_numeric(merged["home_xg"], errors="coerce")
merged["away_xg"] = pd.to_numeric(merged["away_xg"], errors="coerce")

output_path = f"{COMP_NAME.lower()}_merged_full.csv"
merged.to_csv(output_path, index=False)

matched = merged["home_corners"].notna().sum()
print(f"{COMP_NAME}: {len(merged)} мача общо, {matched} с пълна статистика, записани в {output_path}")
