import sys
import numpy as np
from scipy.stats import poisson
import football_lib as fl
from production_pipeline import fit_ht_2h_models, predict_ht_ft

HOME_TEAM = sys.argv[1] if len(sys.argv) > 2 else "CSKA Sofia"
AWAY_TEAM = sys.argv[2] if len(sys.argv) > 2 else "Dunav Ruse"
LEAGUE = "bulgaria"

print(f"Зареждам и тренирам моделите ({LEAGUE})...")
df = fl.load_league_data(LEAGUE)
teams, n, team_idx = fl.get_team_index(df)

if HOME_TEAM not in team_idx or AWAY_TEAM not in team_idx:
    print(f"ГРЕШКА: отбор не е намерен.")
    print(f"Налични: {', '.join(teams)}")
    sys.exit(1)

ref_date = df["date"].max()
ft_model = fl.fit_goals_model(df, ref_date, team_idx, n)
ht_model, h2_model = fit_ht_2h_models(df, team_idx, n)
print("Готово.\n")

lam, mu = fl.get_lambdas(ft_model, team_idx, HOME_TEAM, AWAY_TEAM)
lam_ht, mu_ht = fl.get_lambdas(ht_model, team_idx, HOME_TEAM, AWAY_TEAM)
lam_2h, mu_2h = fl.get_lambdas(h2_model, team_idx, HOME_TEAM, AWAY_TEAM)

max_g = 10
pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
home_win = np.sum(np.tril(pm, -1))
draw = np.sum(np.diag(pm))
away_win = np.sum(np.triu(pm, 1))

btts_p, ou_p = fl.btts_ou_probs(lam, mu)
extra = fl.extra_markets_probs(lam, mu)
ht_ft_probs = predict_ht_ft(lam_ht, mu_ht, lam_2h, mu_2h)
best_htft = max(ht_ft_probs.items(), key=lambda x: x[1])

all_markets = [
    (f"{HOME_TEAM} печели", home_win * 100, "✅"),
    ("Равен", draw * 100, "✅"),
    (f"{AWAY_TEAM} печели", away_win * 100, "✅"),
    (f"Двоен шанс 1X", (home_win + draw) * 100, "✅"),
    (f"Двоен шанс X2", (draw + away_win) * 100, "✅"),
    (f"Двоен шанс 12", (home_win + away_win) * 100, "✅"),
    ("Над 2.5 гола", ou_p * 100, "✅"),
    ("Под 2.5 гола", (1 - ou_p) * 100, "✅"),
    (f"{HOME_TEAM} над 1.5 гола", extra["home_over15"] * 100, "✅"),
    (f"{HOME_TEAM} под 1.5 гола", (1 - extra["home_over15"]) * 100, "✅"),
    (f"Резултат почивка/край: {best_htft[0]}", best_htft[1] * 100, "✅"),
    ("BTTS - Да", btts_p * 100, "⚠️"),
    ("BTTS - Не", (1 - btts_p) * 100, "⚠️"),
    (f"{AWAY_TEAM} над 1.5 гола", extra["away_over15"] * 100, "⚠️"),
    (f"{AWAY_TEAM} под 1.5 гола", (1 - extra["away_over15"]) * 100, "⚠️"),
    (f"{HOME_TEAM} чиста мрежа", extra["home_clean_sheet"] * 100, "⚠️"),
    (f"{AWAY_TEAM} чиста мрежа", extra["away_clean_sheet"] * 100, "⚠️"),
    (f"{HOME_TEAM} печели без допуснат гол", extra["home_win_to_nil"] * 100, "⚠️"),
    (f"{AWAY_TEAM} печели без допуснат гол", extra["away_win_to_nil"] * 100, "⚠️"),
    (f"{HOME_TEAM} хандикап -1 (+2 разлика)", extra["home_handicap_minus1"] * 100, "⚠️"),
    (f"{AWAY_TEAM} хандикап -1 (+2 разлика)", extra["away_handicap_minus1"] * 100, "⚠️"),
]

all_markets.sort(key=lambda x: -x[1])

print("=" * 65)
print(f"  ВСИЧКИ ПАЗАРИ: {HOME_TEAM} vs {AWAY_TEAM}")
print(f"  (очаквани голове: {HOME_TEAM} ~{lam:.2f} | {AWAY_TEAM} ~{mu:.2f})")
print("=" * 65)
print(f"\n{'Пазар':<45} {'%':>8}  Статус")
print("-" * 65)
for label, pct, status in all_markets:
    print(f"{label:<45} {pct:>7.1f}%  {status}")

print("\n✅ = доказано бие случайното гадаене (production-готово)")
print("⚠️ = не е потвърдено кросс-лигово, публикувай с внимание")
