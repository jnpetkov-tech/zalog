import pandas as pd

injuries = pd.read_csv("injuries_all_leagues.csv")

LEAGUES = ["england", "germany", "spain", "france"]

for league in LEAGUES:
    try:
        df = pd.read_csv(f"{league}_merged_full.csv")
    except FileNotFoundError:
        print(f"Пропускам {league} - файлът не съществува")
        continue

    league_injuries = injuries[injuries["country"] == league]

    injury_counts = league_injuries.groupby(["fixture_id", "team_name"]).size().reset_index(name="count")
    injury_dict = {(row.fixture_id, row.team_name): row.count for row in injury_counts.itertuples()}

    df["home_injuries"] = df.apply(
        lambda r: injury_dict.get((r["fixture_id"], r["home_team"]), 0), axis=1
    )
    df["away_injuries"] = df.apply(
        lambda r: injury_dict.get((r["fixture_id"], r["away_team"]), 0), axis=1
    )

    matched = ((df["home_injuries"] > 0) | (df["away_injuries"] > 0)).sum()
    print(f"{league}: {matched} от {len(df)} мача имат поне 1 отбелязана контузия")

    df.to_csv(f"{league}_merged_full.csv", index=False)

print("\nГотово - injury колоните са добавени към всички merged файлове.")
