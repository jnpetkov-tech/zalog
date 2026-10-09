"""features/extract_ratings.py - рейтингите на играчите по мач от суровите отговори /fixtures?ids= (api_raw/*/*.jsonl.gz, ключ "players")
-> features/player_ratings.csv (ZADACHA_VSICHKO_OT_API, етап 1, 09.10.2026). Нула заявки към API-то. Никой жив код не чете файла.

Колони: fixture_id, ts, team_id, player_id, minutes, rating, substitute, position. Последният срещнат отговор за мача печели.
"""
import glob
import gzip
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "features", "player_ratings.csv")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "api_raw", "**", "*.jsonl.gz"), recursive=True))
    rows = {}
    seen_files = 0
    for path in files:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for line in f:
                    if '"players"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    resp = (rec.get("data") or {}).get("response") or []
                    fetched = rec.get("fetched_at", "")
                    if resp and isinstance(resp[0], dict) and "fixture" not in resp[0] and "players" in resp[0]:
                        # /fixtures/players?fixture=X: response = [{team, players}] за един мач
                        fx_id = (rec.get("params") or {}).get("fixture")
                        if not fx_id:
                            continue
                        resp = [{"fixture": {"id": int(fx_id), "timestamp": None}, "players": resp}]
                    for fx in resp:
                        if not isinstance(fx, dict) or not fx.get("players") or "fixture" not in fx:
                            continue
                        fid = fx["fixture"]["id"]
                        ts = fx["fixture"].get("timestamp")
                        out = []
                        for team in fx["players"]:
                            tid = team["team"]["id"]
                            for p in team.get("players", []):
                                st = (p.get("statistics") or [{}])[0]
                                g = st.get("games") or {}
                                out.append((fid, ts, tid, p["player"]["id"], _num(g.get("minutes")), _num(g.get("rating")),
                                            bool(g.get("substitute")), g.get("position")))
                        if out and (fid not in rows or fetched >= rows[fid][0]):
                            rows[fid] = (fetched, out)
            seen_files += 1
        except (OSError, EOFError) as e:
            print(f"пропуснат {path}: {e}", file=sys.stderr)
    flat = [r for _f, out in rows.values() for r in out]
    df = pd.DataFrame(flat, columns=["fixture_id", "ts", "team_id", "player_id", "minutes", "rating", "substitute", "position"])
    df.to_csv(OUT, index=False)
    print(f"{seen_files} файла, {len(rows)} мача, {len(df)} реда, с рейтинг {df['rating'].notna().sum()} -> {OUT}")


if __name__ == "__main__":
    main()
