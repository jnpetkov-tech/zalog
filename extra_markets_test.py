import football_lib as fl

COUNTRIES = ["bulgaria", "england", "germany", "spain", "france"]

for country in COUNTRIES:
    print(f"\n{'='*70}\n{country.upper()}\n{'='*70}")
    df = fl.load_league_data(country)
    teams, n, team_idx = fl.get_team_index(df)
    results, total = fl.backtest_extra_markets(df, team_idx, n)

    for market, r in results.items():
        beats = "ДА" if r["acc"] > r["baseline"] else "не"
        print(f"{market:<25} {r['acc']:>6.1f}%  (baseline {r['baseline']:>5.1f}%)  бие baseline: {beats}")
    print(f"(n={total})")
