import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

HOME_TEAM = "Levski Sofia"
AWAY_TEAM = "CSKA Sofia"

df = pd.read_csv("bulgaria_first_league_matches.csv")
df = df.dropna(subset=["home_goals", "away_goals"])
df["home_goals"] = df["home_goals"].astype(int)
df["away_goals"] = df["away_goals"].astype(int)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

all_teams = sorted(set(df.home_team) | set(df.away_team))
n = len(all_teams)
team_idx = {t: i for i, t in enumerate(all_teams)}

XI = 0.0018
ref_date = df["date"].max()

h_idx = df["home_team"].map(team_idx).to_numpy()
a_idx = df["away_team"].map(team_idx).to_numpy()
hg = df["home_goals"].to_numpy()
ag = df["away_goals"].to_numpy()
days_ago = (ref_date - df["date"]).dt.days.to_numpy()
weights = np.exp(-XI * np.clip(days_ago, 0, None))

mask00 = (hg == 0) & (ag == 0)
mask01 = (hg == 0) & (ag == 1)
mask10 = (hg == 1) & (ag == 0)
mask11 = (hg == 1) & (ag == 1)


def fit_general():
    def nll(params):
        attack = params[:n]
        defence = params[n:2*n]
        home_adv = params[-2]
        rho = params[-1]
        lam = np.exp(attack[h_idx] - defence[a_idx] + home_adv)
        mu = np.exp(attack[a_idx] - defence[h_idx])
        tau = np.ones(len(hg))
        tau[mask00] = 1 - lam[mask00] * mu[mask00] * rho
        tau[mask01] = 1 + lam[mask01] * rho
        tau[mask10] = 1 + mu[mask10] * rho
        tau[mask11] = 1 - rho
        tau = np.clip(tau, 1e-10, None)
        ll = np.log(tau) + poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)
    x0 = np.zeros(2*n+2)
    bounds = [(None, None)]*(2*n+1) + [(-1, 1)]
    r = minimize(nll, x0, method="L-BFGS-B", bounds=bounds)
    return r.x[:n], r.x[n:2*n], r.x[-2], r.x[-1]


def fit_home_away():
    def nll(params):
        ah = params[0*n:1*n]; dh = params[1*n:2*n]
        aa = params[2*n:3*n]; da = params[3*n:4*n]
        rho = params[-1]
        lam = np.exp(ah[h_idx] - da[a_idx])
        mu = np.exp(aa[a_idx] - dh[h_idx])
        tau = np.ones(len(hg))
        tau[mask00] = 1 - lam[mask00] * mu[mask00] * rho
        tau[mask01] = 1 + lam[mask01] * rho
        tau[mask10] = 1 + mu[mask10] * rho
        tau[mask11] = 1 - rho
        tau = np.clip(tau, 1e-10, None)
        ll = np.log(tau) + poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        return -np.sum(ll * weights)
    x0 = np.zeros(4*n+1)
    bounds = [(None, None)]*(4*n) + [(-1, 1)]
    r = minimize(nll, x0, method="L-BFGS-B", bounds=bounds)
    return r.x[0*n:1*n], r.x[1*n:2*n], r.x[2*n:3*n], r.x[3*n:4*n], r.x[-1]


def prob_matrix_general(attack, defence, home_adv, rho, home, away, max_goals=8):
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(attack[hi] - defence[ai] + home_adv)
    mu = np.exp(attack[ai] - defence[hi])
    pm = np.outer(poisson.pmf(range(max_goals), lam), poisson.pmf(range(max_goals), mu))
    _apply_dc(pm, lam, mu, rho)
    return pm / pm.sum()


def prob_matrix_home_away(ah, dh, aa, da, rho, home, away, max_goals=8):
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(ah[hi] - da[ai])
    mu = np.exp(aa[ai] - dh[hi])
    pm = np.outer(poisson.pmf(range(max_goals), lam), poisson.pmf(range(max_goals), mu))
    _apply_dc(pm, lam, mu, rho)
    return pm / pm.sum()


def _apply_dc(pm, lam, mu, rho):
    pm[0, 0] *= (1 - lam * mu * rho)
    pm[0, 1] *= (1 + lam * rho)
    pm[1, 0] *= (1 + mu * rho)
    pm[1, 1] *= (1 - rho)


def markets(pm):
    max_goals = pm.shape[0]
    btts_yes = over25 = 0.0
    for x in range(max_goals):
        for y in range(max_goals):
            if x >= 1 and y >= 1:
                btts_yes += pm[x, y]
            if x + y > 2.5:
                over25 += pm[x, y]
    return {
        "home_win": np.sum(np.tril(pm, -1)),
        "draw": np.sum(np.diag(pm)),
        "away_win": np.sum(np.triu(pm, 1)),
        "btts_yes": btts_yes, "btts_no": 1 - btts_yes,
        "over25": over25, "under25": 1 - over25,
    }


print(f"Тренирам двата модела на {len(df)} мача (до {ref_date.date()})...")
attack, defence, home_adv, rho_gen = fit_general()
ah, dh, aa, da, rho_ha = fit_home_away()
print("Готово.\n")

if HOME_TEAM not in team_idx or AWAY_TEAM not in team_idx:
    print(f"ГРЕШКА: '{HOME_TEAM}' или '{AWAY_TEAM}' не са намерени в данните.")
    print(f"Налични отбори: {', '.join(all_teams)}")
else:
    pm_general = prob_matrix_general(attack, defence, home_adv, rho_gen, HOME_TEAM, AWAY_TEAM)
    pm_ha = prob_matrix_home_away(ah, dh, aa, da, rho_ha, HOME_TEAM, AWAY_TEAM)

    m_general = markets(pm_general)
    m_ha = markets(pm_ha)

    print("=" * 55)
    print(f"  ПРОГНОЗА: {HOME_TEAM} vs {AWAY_TEAM}")
    print("=" * 55)
    print("\n1X2 (от home/away-специфичния модел):")
    print(f"  {HOME_TEAM} печели: {m_ha['home_win']*100:.1f}%")
    print(f"  Равен:                {m_ha['draw']*100:.1f}%")
    print(f"  {AWAY_TEAM} печели: {m_ha['away_win']*100:.1f}%")
    print("\nBTTS (от общия модел):")
    print(f"  Да:  {m_general['btts_yes']*100:.1f}%")
    print(f"  Не:  {m_general['btts_no']*100:.1f}%")
    print("\nOver/Under 2.5 (от общия модел):")
    print(f"  Over:  {m_general['over25']*100:.1f}%")
    print(f"  Under: {m_general['under25']*100:.1f}%")
