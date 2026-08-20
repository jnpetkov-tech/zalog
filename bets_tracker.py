import sqlite3
from datetime import datetime

DB_PATH = "bets.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            placed_at TEXT,
            league TEXT,
            fixture_id INTEGER,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            market_code TEXT,
            pick_label TEXT,
            pick_pct REAL,
            status TEXT DEFAULT 'pending',
            actual_home_goals INTEGER,
            actual_away_goals INTEGER,
            combo_id INTEGER
        )
    """)
    conn.commit()
    conn.close()


def place_bet(league, fixture_id, match_date, home, away, market_code, pick_label, pick_pct, combo_id=None):
    conn = get_conn()

    if combo_id is None:
        existing = conn.execute(
            "SELECT id FROM bets WHERE fixture_id=? AND market_code=? AND combo_id IS NULL",
            (fixture_id, market_code)
        ).fetchone()
    else:
        existing = conn.execute(
            "SELECT id FROM bets WHERE fixture_id=? AND market_code=? AND combo_id=?",
            (fixture_id, market_code, combo_id)
        ).fetchone()

    if existing:
        conn.close()
        return existing[0]

    cur = conn.execute(
        """INSERT INTO bets (placed_at, league, fixture_id, match_date, home_team, away_team,
           market_code, pick_label, pick_pct, combo_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(), league, fixture_id, match_date, home, away,
         market_code, pick_label, pick_pct, combo_id)
    )
    conn.commit()
    bet_id = cur.lastrowid
    conn.close()
    return bet_id


def next_combo_id():
    conn = get_conn()
    row = conn.execute("SELECT MAX(combo_id) FROM bets").fetchone()
    conn.close()
    return (row[0] or 0) + 1


def list_bets():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM bets ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def evaluate_market(market_code, hg, ag, ht_hg=None, ht_ag=None):
    if market_code == "home_win":
        return hg > ag
    if market_code == "draw":
        return hg == ag
    if market_code == "away_win":
        return hg < ag
    if market_code == "over25":
        return (hg + ag) > 2.5
    if market_code == "under25":
        return (hg + ag) <= 2.5
    if market_code == "home_over15":
        return hg > 1.5
    if market_code == "home_under15":
        return hg <= 1.5
    if market_code.startswith("htft:") and ht_hg is not None:
        target = market_code.split(":", 1)[1]

        def res(h, a):
            if h > a:
                return "1"
            elif h == a:
                return "X"
            return "2"
        actual = f"{res(ht_hg, ht_ag)}/{res(hg, ag)}"
        return actual == target
    return None


def check_results(api_key, base_url, requests_module):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    pending = conn.execute("SELECT * FROM bets WHERE status='pending' AND fixture_id IS NOT NULL").fetchall()
    updated = 0

    for row in pending:
        fixture_id = row["fixture_id"]
        r = requests_module.get(
            f"{base_url}/fixtures",
            headers={"x-apisports-key": api_key},
            params={"id": fixture_id},
        )
        data = r.json()
        if not data.get("response"):
            continue
        fixture = data["response"][0]
        status_short = fixture["fixture"]["status"]["short"]
        if status_short != "FT":
            continue

        hg = fixture["goals"]["home"]
        ag = fixture["goals"]["away"]
        ht = fixture.get("score", {}).get("halftime", {})
        ht_hg, ht_ag = ht.get("home"), ht.get("away")

        market_code = row["market_code"]
        if market_code.startswith(("corners_", "cards_", "offsides_")):
            stats = fetch_fixture_stats(api_key, base_url, requests_module, fixture_id,
                                          row["home_team"], row["away_team"])
            result = evaluate_stat_market(market_code, stats)
        else:
            result = evaluate_market_v2(market_code, hg, ag, ht_hg, ht_ag)

        if result is None:
            continue

        new_status = "won" if result else "lost"
        conn.execute(
            "UPDATE bets SET status=?, actual_home_goals=?, actual_away_goals=? WHERE id=?",
            (new_status, hg, ag, row["id"]),
        )
        updated += 1

    conn.commit()
    conn.close()
    return updated


def get_stats():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT status, COUNT(*) c FROM bets WHERE combo_id IS NULL GROUP BY status"
    ).fetchall()
    conn.close()
    stats = {r["status"]: r["c"] for r in rows}
    won = stats.get("won", 0)
    lost = stats.get("lost", 0)
    pending = stats.get("pending", 0)
    total_settled = won + lost
    win_rate = (won / total_settled * 100) if total_settled else None
    return {"won": won, "lost": lost, "pending": pending, "win_rate": win_rate}


init_db()


def evaluate_market_v2(market_code, hg, ag, ht_hg=None, ht_ag=None):
    if market_code == "dc_1x":
        return hg >= ag
    if market_code == "dc_x2":
        return hg <= ag
    if market_code == "dc_12":
        return hg != ag
    if market_code == "btts_yes":
        return hg >= 1 and ag >= 1
    if market_code == "btts_no":
        return not (hg >= 1 and ag >= 1)
    if market_code == "away_over15":
        return ag > 1.5
    if market_code == "away_under15":
        return ag <= 1.5
    if market_code == "home_clean_sheet":
        return ag == 0
    if market_code == "away_clean_sheet":
        return hg == 0
    return evaluate_market(market_code, hg, ag, ht_hg, ht_ag)


def evaluate_stat_market(market_code, stats):
    if stats is None:
        return None
    hc, ac = stats.get("home_corners"), stats.get("away_corners")
    hcd, acd = stats.get("home_cards"), stats.get("away_cards")
    ho, ao = stats.get("home_offsides"), stats.get("away_offsides")

    if market_code == "corners_total_over_9.5" and hc is not None and ac is not None:
        return (hc + ac) > 9.5
    if market_code == "corners_total_under_9.5" and hc is not None and ac is not None:
        return (hc + ac) <= 9.5
    if market_code == "corners_home_over_4.5" and hc is not None:
        return hc > 4.5
    if market_code == "corners_away_over_4.5" and ac is not None:
        return ac > 4.5
    if market_code == "cards_total_over_3.5" and hcd is not None and acd is not None:
        return (hcd + acd) > 3.5
    if market_code == "cards_total_under_3.5" and hcd is not None and acd is not None:
        return (hcd + acd) <= 3.5
    if market_code == "offsides_total_over_3.5" and ho is not None and ao is not None:
        return (ho + ao) > 3.5
    if market_code == "offsides_total_under_3.5" and ho is not None and ao is not None:
        return (ho + ao) <= 3.5
    return None


def fetch_fixture_stats(api_key, base_url, requests_module, fixture_id, home_team, away_team):
    r = requests_module.get(f"{base_url}/fixtures/statistics", headers={"x-apisports-key": api_key},
                             params={"fixture": fixture_id})
    data = r.json()
    response = data.get("response", [])
    if not response:
        return None

    def get_stat(team_stats, type_name):
        for s in team_stats.get("statistics", []):
            if s["type"] == type_name:
                return s["value"]
        return None

    stats = {}
    for team_data in response:
        team_name = team_data["team"]["name"]
        corners = get_stat(team_data, "Corner Kicks")
        yellow = get_stat(team_data, "Yellow Cards") or 0
        red = get_stat(team_data, "Red Cards") or 0
        offsides = get_stat(team_data, "Offsides")

        if team_name == home_team:
            stats["home_corners"] = corners
            stats["home_cards"] = (yellow or 0) + (red or 0)
            stats["home_offsides"] = offsides
        elif team_name == away_team:
            stats["away_corners"] = corners
            stats["away_cards"] = (yellow or 0) + (red or 0)
            stats["away_offsides"] = offsides

    return stats if stats else None
