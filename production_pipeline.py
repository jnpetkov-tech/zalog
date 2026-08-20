import sys
import numpy as np
import pandas as pd
from scipy.stats import poisson
import football_lib as fl


def fit_ht_2h_models(df, team_idx, n):
    df = df.copy()
    df["home_2h_goals"] = df["home_goals"] - df["home_ht_goals"]
    df["away_2h_goals"] = df["away_goals"] - df["away_ht_goals"]

    ref_date = df["date"].max()

    ht_df = df.dropna(subset=["home_ht_goals", "away_ht_goals"]).copy()
    ht_df["home_goals_orig"] = ht_df["home_goals"]
    ht_df["away_goals_orig"] = ht_df["away_goals"]
    ht_df["home_goals"] = ht_df["home_ht_goals"]
    ht_df["away_goals"] = ht_df["away_ht_goals"]
    ht_model = fl.fit_goals_model(ht_df, ref_date, team_idx, n)

    h2_df = df.dropna(subset=["home_2h_goals", "away_2h_goals"]).copy()
    h2_df["home_goals_orig"] = h2_df["home_goals"]
    h2_df["away_goals_orig"] = h2_df["away_goals"]
    h2_df["home_goals"] = h2_df["home_2h_goals"]
    h2_df["away_goals"] = h2_df["away_2h_goals"]
    h2_model = fl.fit_goals_model(h2_df, ref_date, team_idx, n)

    return ht_model, h2_model


def ht_ft_outcome(ht_h, ht_a, ft_h, ft_a):
    def result(h, a):
        if h > a: return "1"
        elif h == a: return "X"
        else: return "2"
    return f"{result(ht_h, ht_a)}/{result(ft_h, ft_a)}"


def predict_ht_ft(lam_ht_h, lam_ht_a, lam_2h_h, lam_2h_a, max_goals=6):
    outcomes = {}
    for hh in range(max_goals):
        for ha in range(max_goals):
            p_ht = poisson.pmf(hh, lam_ht_h) * poisson.pmf(ha, lam_ht_a)
            for h2 in range(max_goals):
                for a2 in range(max_goals):
                    p_2h = poisson.pmf(h2, lam_2h_h) * poisson.pmf(a2, lam_2h_a)
                    outcome = ht_ft_outcome(hh, ha, hh + h2, ha + a2)
                    outcomes[outcome] = outcomes.get(outcome, 0) + p_ht * p_2h
    total = sum(outcomes.values())
    return {k: v / total for k, v in outcomes.items()}


def main():
    if len(sys.argv) != 4:
        print("Употреба: python3 production_pipeline.py <лига> \"<домакин>\" \"<гост>\"")
        sys.exit(1)

    league = sys.argv[1]
    home_team = sys.argv[2]
    away_team = sys.argv[3]

    df = fl.load_league_data(league)
    teams, n, team_idx = fl.get_team_index(df)

    if home_team not in team_idx or away_team not in team_idx:
        print(f"ГРЕШКА: отбор не е намерен.")
        print(f"Налични отбори: {', '.join(teams)}")
        sys.exit(1)

    ref_date = df["date"].max()

    print(f"Тренирам моделите на {len(df)} мача (лига: {league}, до {ref_date.date()})...")
    ft_model = fl.fit_goals_model(df, ref_date, team_idx, n)
    ht_model, h2_model = fit_ht_2h_models(df, team_idx, n)
    print("Готово.\n")

    lam, mu = fl.get_lambdas(ft_model, team_idx, home_team, away_team)
    lam_ht, mu_ht = fl.get_lambdas(ht_model, team_idx, home_team, away_team)
    lam_2h, mu_2h = fl.get_lambdas(h2_model, team_idx, home_team, away_team)

    btts_p, ou_p = fl.btts_ou_probs(lam, mu)
    extra = fl.extra_markets_probs(lam, mu)
    ht_ft_probs = predict_ht_ft(lam_ht, mu_ht, lam_2h, mu_2h)

    max_g = 10
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    home_win = np.sum(np.tril(pm, -1))
    draw = np.sum(np.diag(pm))
    away_win = np.sum(np.triu(pm, 1))

    print("=" * 55)
    print(f"  ПРОГНОЗА: {home_team} vs {away_team}  ({league.upper()})")
    print("=" * 55)

    print("\n✅ 1X2 (production):")
    print(f"  {home_team} печели: {home_win*100:.1f}%")
    print(f"  Равен:                {draw*100:.1f}%")
    print(f"  {away_team} печели: {away_win*100:.1f}%")

    print("\n✅ Over/Under 2.5 (production):")
    print(f"  Over:  {ou_p*100:.1f}%")
    print(f"  Under: {(1-ou_p)*100:.1f}%")

    print(f"\n✅ Team Total - {home_team} над 1.5 гола (production, най-силен пазар):")
    print(f"  Над 1.5:  {extra['home_over15']*100:.1f}%")
    print(f"  Под 1.5:  {(1-extra['home_over15'])*100:.1f}%")

    print("\n✅ HT/FT (production, топ 3 най-вероятни комбинации):")
    sorted_htft = sorted(ht_ft_probs.items(), key=lambda x: -x[1])
    for outcome, prob in sorted_htft[:3]:
        print(f"  {outcome}: {prob*100:.1f}%")

    print("\n⚠️  Информативно (не бие baseline последователно, публикувай с внимание):")
    print(f"  BTTS Да: {btts_p*100:.1f}%")
    print(f"  {away_team} над 1.5: {extra['away_over15']*100:.1f}%")


if __name__ == "__main__":
    main()
