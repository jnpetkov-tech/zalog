import signal
import time
import sys
sys.path.insert(0, '.')
import football_lib as fl
from production_pipeline import fit_ht_2h_models


class TimeoutErr(Exception):
    pass


def handler(signum, frame):
    raise TimeoutErr()


def timed_fit(name, func, timeout=90):
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(timeout)
    start = time.time()
    try:
        func()
        elapsed = time.time() - start
        print(f"  {name}: OK за {elapsed:.1f} сек")
    except TimeoutErr:
        print(f"  {name}: ПРЕВИШИ {timeout} сек лимит - ТУК Е ПРОБЛЕМЪТ")
    except Exception as e:
        print(f"  {name}: ГРЕШКА - {e}")
    finally:
        signal.alarm(0)


league = "conference_league"
print(f"Зареждам данните за {league}...")
df = fl.load_league_data(league)
teams, n, team_idx = fl.get_team_index(df)
print(f"Брой мачове: {len(df)}, БРОЙ УНИКАЛНИ ОТБОРИ: {n}\n")

ref_date = df["date"].max()
league_xi = fl.LEAGUE_XI.get(league, fl.XI)
has_injuries = "home_injuries" in df.columns
print(f"Има данни за контузии: {has_injuries}\n")

if has_injuries:
    timed_fit("ft_model (injuries)", lambda: fl.fit_goals_direct_covariate(
        df, ref_date, team_idx, n, "home_injuries", "away_injuries", xi=league_xi))
else:
    timed_fit("ft_model (basic)", lambda: fl.fit_goals_model(df, ref_date, team_idx, n, xi=league_xi))

timed_fit("ht_2h_model", lambda: fit_ht_2h_models(df, team_idx, n))

if "home_corners" in df.columns:
    timed_fit("corners_model", lambda: fl.fit_total_model(
        df, ref_date, team_idx, n, "home_corners", "away_corners", xi=league_xi))

if "home_yellow" in df.columns:
    df["home_cards_total"] = df["home_yellow"].fillna(0) + df.get("home_red", 0)
    df["away_cards_total"] = df["away_yellow"].fillna(0) + df.get("away_red", 0)
    timed_fit("cards_model", lambda: fl.fit_total_model(
        df, ref_date, team_idx, n, "home_cards_total", "away_cards_total", xi=league_xi))

if "home_offsides" in df.columns:
    timed_fit("offsides_model", lambda: fl.fit_total_model(
        df, ref_date, team_idx, n, "home_offsides", "away_offsides", xi=league_xi))

print("\nГотово с диагностиката.")
