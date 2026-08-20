import pandas as pd
import numpy as np

LEAGUE_CODE = {"england": "E0", "germany": "D1", "spain": "SP1", "france": "F1", "italy": "I1", "portugal": "P1"}
SEASONS = ["2223", "2324", "2425", "2526"]

OUR_CANON = {
    "Bayern München": "Bayern Munich",
    "Borussia Mönchengladbach": "Borussia Monchengladbach",
    "1. FC Heidenheim": "FC Heidenheim",
    "Vfl Bochum": "VfL Bochum",
}

THEIRS_TO_OURS = {
    "england": {"Man City": "Manchester City", "Man United": "Manchester United", "Nott'm Forest": "Nottingham Forest"},
    "germany": {
        "Augsburg": "FC Augsburg", "Dortmund": "Borussia Dortmund", "Ein Frankfurt": "Eintracht Frankfurt",
        "FC Koln": "1. FC Köln", "Freiburg": "SC Freiburg", "Hamburg": "Hamburger SV",
        "Heidenheim": "FC Heidenheim", "Hoffenheim": "1899 Hoffenheim", "Leverkusen": "Bayer Leverkusen",
        "M'gladbach": "Borussia Monchengladbach", "Mainz": "FSV Mainz 05", "St Pauli": "FC St. Pauli",
        "Stuttgart": "VfB Stuttgart", "Wolfsburg": "VfL Wolfsburg", "Hertha": "Hertha Berlin",
        "Schalke 04": "FC Schalke 04", "Bochum": "VfL Bochum", "Darmstadt": "SV Darmstadt 98",
        "Elversberg": "SV Elversberg",
    },
    "spain": {
        "Ath Bilbao": "Athletic Club", "Ath Madrid": "Atletico Madrid", "Betis": "Real Betis",
        "Celta": "Celta Vigo", "Espanol": "Espanyol", "Sociedad": "Real Sociedad",
        "Vallecano": "Rayo Vallecano", "Granada": "Granada CF",
    },
    "france": {
        "Paris SG": "Paris Saint Germain", "Brest": "Stade Brestois 29",
        "St Etienne": "Saint Etienne", "Troyes": "Estac Troyes",
    },
    "italy": {
        "Milan": "AC Milan", "Roma": "AS Roma", "Verona": "Hellas Verona",
    },
    "portugal": {
        "Gil Vicente": "GIL Vicente", "Porto": "FC Porto", "Sp Braga": "SC Braga", "Sp Lisbon": "Sporting CP",
    },
}

ODDS_COLS = ["AvgH", "AvgD", "AvgA", "AvgCH", "AvgCD", "AvgCA",
             "Avg>2.5", "Avg<2.5", "AvgC>2.5", "AvgC<2.5",
             "B365H", "B365D", "B365A", "B365CH", "B365CD", "B365CA"]

for league, code in LEAGUE_CODE.items():
    ours = pd.read_csv(f"{league}_merged_full.csv")
    ours["home_team"] = ours["home_team"].replace(OUR_CANON)
    ours["away_team"] = ours["away_team"].replace(OUR_CANON)
    ours["date_only"] = pd.to_datetime(ours["date"].astype(str).str[:10])

    odds_frames = []
    for season in SEASONS:
        path = f"odds_historical/season_{season}/{code}.csv"
        try:
            o = pd.read_csv(path)
        except Exception:
            continue
        mapping = THEIRS_TO_OURS.get(league, {})
        o = o.copy()
        o["HomeTeam"] = o["HomeTeam"].replace(mapping)
        o["AwayTeam"] = o["AwayTeam"].replace(mapping)
        o["date_only"] = pd.to_datetime(o["Date"], format="%d/%m/%Y", errors="coerce")
        keep_cols = ["date_only", "HomeTeam", "AwayTeam"] + [c for c in ODDS_COLS if c in o.columns]
        odds_frames.append(o[keep_cols])

    if not odds_frames:
        print(f"{league}: няма намерени файлове с коефициенти, пропускам.")
        continue

    all_odds = pd.concat(odds_frames, ignore_index=True)
    merged = ours.merge(all_odds, left_on=["date_only", "home_team", "away_team"],
                         right_on=["date_only", "HomeTeam", "AwayTeam"], how="left")

    total = len(ours)
    matched = merged["AvgH"].notna().sum() if "AvgH" in merged.columns else 0
    print(f"{league}: {matched}/{total} мача с намерени коефициенти ({matched/total*100:.1f}%)")

    merged.to_csv(f"{league}_with_odds.csv", index=False)
