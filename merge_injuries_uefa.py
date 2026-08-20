import pandas as pd

injuries = pd.read_csv("injuries_uefa.csv")

COMPETITIONS = ["champions_league", "europa_league"]

for comp in COMPETITIONS:
    df = pd.read_csv(f"{comp}_merged_full.csv")

    comp_injuries = injuries[injuries["competition"] == comp]

    injury_counts = comp_injuries.groupby(["fixture_id", "team_name"]).size().reset_index(name="count")
    injury_dict = {(row.fixture_id, row.team_name): row.count for row in injury_counts.itertuples()}

    df["home_injuries"] = df.apply(
        lambda r: injury_dict.get((r["fixture_id"], r["home_team"]), 0), axis=1
    )
    df["away_injuries"] = df.apply(
        lambda r: injury_dict.get((r["fixture_id"], r["away_team"]), 0), axis=1
    )

    matched = ((df["home_injuries"] > 0) | (df["away_injuries"] > 0)).sum()
    print(f"{comp}: {matched} от {len(df)} мача имат поне 1 отбелязана контузия")

    df.to_csv(f"{comp}_merged_full.csv", index=False)

print("\nГотово - injury колоните са добавени.")
