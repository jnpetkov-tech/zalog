import football_lib as fl

COUNTRIES = ["bulgaria", "england", "germany", "spain", "france"]
CANDIDATES = [
    (None, None, "Базов (без covariate)"),
    ("home_fouls", "away_fouls", "Фаулове"),
    ("home_possession", "away_possession", "Притежание"),
    ("home_shots", "away_shots", "Общо удари"),
    ("home_offsides", "away_offsides", "Засади"),
]

for country in COUNTRIES:
    print(f"\n{'='*70}\n{country.upper()}\n{'='*70}")
    df = fl.load_league_data(country)
    teams, n, team_idx = fl.get_team_index(df)

    for cov_h, cov_a, label in CANDIDATES:
        r = fl.backtest_covariate(df, team_idx, n, cov_h, cov_a)
        btts_beats = "ДА" if r["btts_acc"] > r["btts_baseline"] else "не"
        ou_beats = "ДА" if r["ou_acc"] > r["ou_baseline"] else "не"
        print(f"{label:<22} BTTS: {r['btts_acc']:.1f}% ({btts_beats} vs base {r['btts_baseline']:.1f}%)  "
              f"O/U: {r['ou_acc']:.1f}% ({ou_beats} vs base {r['ou_baseline']:.1f}%)")
