import pandas as pd
import numpy as np
import os

PRIOR_MATCHES = 8
DEFAULT_EXPECTED_MINUTES = 75

_player_rates_cache = {}


def compute_player_rates(league):
    """Изчислява shrinkage ставки (голове/90, картони/90) за всеки играч в лигата, на база цялата налична история."""
    stats_path = f"{league}_player_stats.csv"
    if not os.path.exists(stats_path):
        return {}
    players = pd.read_csv(stats_path)
    players = players.drop_duplicates(subset=["fixture_id", "player_id"])
    players["minutes"] = players["minutes"].fillna(0)
    players["goals"] = players["goals"].fillna(0)
    players["yellow_cards"] = players["yellow_cards"].fillna(0)

    total_minutes = players["minutes"].sum()
    league_goal_rate = players["goals"].sum() / (total_minutes / 90) if total_minutes > 0 else 0.05
    league_card_rate = players["yellow_cards"].sum() / (total_minutes / 90) if total_minutes > 0 else 0.2

    grouped = players.groupby("player_id").agg(
        name=("player_name", "last"),
        team=("team", "last"),
        total_minutes=("minutes", "sum"),
        total_goals=("goals", "sum"),
        total_cards=("yellow_cards", "sum"),
        matches=("fixture_id", "nunique"),
    ).reset_index()

    grouped["goal_rate"] = (grouped["total_goals"] + PRIOR_MATCHES * league_goal_rate) / (grouped["total_minutes"] / 90 + PRIOR_MATCHES)
    grouped["card_rate"] = (grouped["total_cards"] + PRIOR_MATCHES * league_card_rate) / (grouped["total_minutes"] / 90 + PRIOR_MATCHES)

    result = {}
    for _, row in grouped.iterrows():
        result[int(row["player_id"])] = {
            "name": row["name"], "team": row["team"],
            "goal_rate": float(row["goal_rate"]), "card_rate": float(row["card_rate"]),
            "minutes": float(row["total_minutes"]), "matches": int(row["matches"]),
        }
    return result


def get_player_rates(league):
    if league not in _player_rates_cache:
        _player_rates_cache[league] = compute_player_rates(league)
    return _player_rates_cache[league]


def predict_player_props(league, lineup_full, p_at_least_one_goal=None):
    """lineup_full: резултат от fetch_fixture_lineups_full().
    Връща dict team_name -> списък от играчи с anytime_scorer_pct, card_pct, first_scorer_pct."""
    rates = get_player_rates(league)
    raw = {}
    all_lam_goal = []

    for team_name, block in lineup_full.items():
        team_players = []
        for p in block["starters"]:
            pid = p["player_id"]
            info = rates.get(pid)
            if info is None:
                continue
            lam_goal = info["goal_rate"] * (DEFAULT_EXPECTED_MINUTES / 90)
            lam_card = info["card_rate"] * (DEFAULT_EXPECTED_MINUTES / 90)
            entry = {
                "player_id": pid, "name": info["name"], "pos": p.get("pos"),
                "anytime_scorer_pct": (1 - np.exp(-lam_goal)) * 100,
                "card_pct": (1 - np.exp(-lam_card)) * 100,
                "lam_goal": lam_goal,
                "sample_matches": info["matches"],
            }
            team_players.append(entry)
            all_lam_goal.append(lam_goal)
        raw[team_name] = team_players

    total_lam = sum(all_lam_goal) if all_lam_goal else 0
    if total_lam > 0 and p_at_least_one_goal is not None:
        for team_name, team_players in raw.items():
            for entry in team_players:
                entry["first_scorer_pct"] = (entry["lam_goal"] / total_lam) * p_at_least_one_goal * 100

    return raw
