import pandas as pd

df = pd.read_csv("champions_league_merged_full.csv")

mask = (df["home_team"].str.contains("Sabah", na=False)) | (df["away_team"].str.contains("Sabah", na=False))
sabah_matches = df[mask]

print(f"Общо мачове на Sabah FA в данните: {len(sabah_matches)}\n")

for _, row in sabah_matches.iterrows():
    is_home = "Sabah" in row["home_team"]
    side = "home" if is_home else "away"
    opponent = row["away_team"] if is_home else row["home_team"]
    yellow = row.get(f"{side}_yellow")
    red = row.get(f"{side}_red")
    corners = row.get(f"{side}_corners")
    print(f"  {row['date']} vs {opponent} ({'у дома' if is_home else 'гост'}): "
          f"жълти={yellow}, червени={red}, корнери={corners}")
