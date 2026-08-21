import pandas as pd

df = pd.read_csv("champions_league_merged_full.csv")

for team_name in ["Aarhus", "Sabah"]:
    mask = (df["home_team"].str.contains(team_name, na=False)) | (df["away_team"].str.contains(team_name, na=False))
    matches = df[mask]
    print(f"\n{team_name}: общо {len(matches)} мача в данните")
    for _, row in matches.iterrows():
        is_home = team_name in row["home_team"]
        print(f"  {row['date']} {row['home_team']} {row['home_goals']}-{row['away_goals']} {row['away_team']}")
