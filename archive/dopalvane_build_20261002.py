"""archive/dopalvane_build_20261002.py - ZADACHA_DOPALVANE т.2.1-2.2 (02.10.2026), еднократно.

2.1 Таблица на дупките: за всяка от 17-те лиги и всеки сезон от 2020 - мачове в {лига}_merged_full.csv срещу изиграните
    мачове по API-то (вече изтеглени: hist/{лига}_fixtures.csv за 2019-2021, {лига}_fixtures.csv за 2022+).
    "Изигран" = статус FT - както incremental_refresh.py (AET/PEN/AWD/WO не влизат никъде в живите файлове).
    -> validation/dopalvane_dupki_20261002.csv
2.2 Нови файлове (САМО в --out папката, живите не се пипат): дупка = изигран мач от сезон >= 2020, който липсва във файла,
    в сезон, който файлът по замисъл покрива (сезон >= първия сезон във файла). Ред от друга лига (fixture_id го няма в
    мачовете на лигата, но го има в мачовете на друга) се мести там.
    Ред във формата на incremental_refresh.py / features/core_lam_mu_hist.hist_merged(): дата = UTC дата на мача,
    голове = goals, полувреме = ht; статистиката от {лига}_stats_full.csv (hist/ и живата), иначе от суровите
    отговори /fixtures?ids= (api_raw/fixtures_full), иначе празна (API-то няма статистика за мача).
    Същите колони в същия ред като живия файл, дати "YYYY-MM-DD 00:00:00" (както повечето редове), подредено по дата и
    fixture_id, без дубликати по fixture_id. Проверки преди запис - виж check().
Употреба: venv/bin/python3 archive/dopalvane_build_20261002.py --out <папка>
"""
import glob
import gzip
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "champions_league", "europa_league", "conference_league",
           "italy", "portugal", "france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
FROM_SEASON = 2020
DUPKI_CSV = "validation/dopalvane_dupki_20261002.csv"
# колона в {лига}_stats_full.csv / тип в суровия /fixtures -> суфикс в merged_full (= core_lam_mu_hist.STAT_MAP)
STAT_MAP = {"Corner_Kicks": "corners", "Yellow_Cards": "yellow", "Red_Cards": "red", "Total_Shots": "shots",
            "Shots_on_Goal": "shots_on_goal", "Shots_insidebox": "shots_insidebox", "Ball_Possession": "possession",
            "Fouls": "fouls", "Offsides": "offsides", "Goalkeeper_Saves": "saves", "Total_passes": "passes",
            "Passes_accurate": "passes_accurate", "expected_goals": "xg"}
RAW_TYPE = {"Corner Kicks": "Corner_Kicks", "Yellow Cards": "Yellow_Cards", "Red Cards": "Red_Cards",
            "Total Shots": "Total_Shots", "Shots on Goal": "Shots_on_Goal", "Shots insidebox": "Shots_insidebox",
            "Ball Possession": "Ball_Possession", "Fouls": "Fouls", "Offsides": "Offsides",
            "Goalkeeper Saves": "Goalkeeper_Saves", "Total passes": "Total_passes",
            "Passes accurate": "Passes_accurate", "expected_goals": "expected_goals"}


def num(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    try:
        return float(str(v).replace("%", ""))
    except ValueError:
        return np.nan


def fixtures(league):
    parts = [pd.read_csv(p, low_memory=False) for p in (f"hist/{league}_fixtures.csv", f"{league}_fixtures.csv")
             if os.path.exists(p)]
    fx = pd.concat(parts, ignore_index=True).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx["fixture_id"] = fx["fixture_id"].astype(int)
    return fx


def stats_lookup(league, ids, home_id):
    """fixture_id -> {колона в merged: стойност}."""
    out = {}
    for p in (f"hist/{league}_stats_full.csv", f"{league}_stats_full.csv"):
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            continue
        st = pd.read_csv(p, low_memory=False)
        st = st[st["fixture_id"].isin(ids)].sort_values("fetched_at").drop_duplicates(["fixture_id", "team_id"], keep="last")
        for r in st.to_dict("records"):
            fid = int(r["fixture_id"])
            side = "home" if int(r["team_id"]) == home_id[fid] else "away"
            d = out.setdefault(fid, {})
            for col, suf in STAT_MAP.items():
                if col in r and not pd.isna(r[col]):
                    d[f"{side}_{suf}"] = num(r[col])
    for p in sorted(glob.glob(f"api_raw/fixtures_full/{league}_*.jsonl.gz")):
        for line in gzip.open(p, "rt", encoding="utf-8"):
            for x in json.loads(line)["data"].get("response") or []:
                fid = x["fixture"]["id"]
                if fid not in ids or fid in out or not x.get("statistics"):
                    continue
                d = out.setdefault(fid, {})
                for t in x["statistics"]:
                    side = "home" if t["team"]["id"] == home_id[fid] else "away"
                    for s in t.get("statistics") or []:
                        col = RAW_TYPE.get(s["type"])
                        if col and s["value"] is not None:
                            d[f"{side}_{STAT_MAP[col]}"] = num(s["value"])
    return out


def new_rows(league, fx_new, cols):
    home_id = dict(zip(fx_new["fixture_id"], fx_new["home_id"].astype(int)))
    st = stats_lookup(league, set(fx_new["fixture_id"]), home_id)
    rows = []
    for r in fx_new.to_dict("records"):
        row = {c: np.nan for c in cols}
        row.update({"fixture_id": int(r["fixture_id"]), "season": int(r["season"]),
                    "date": str(r["date_utc"])[:10] + " 00:00:00", "home_team": r["home"], "away_team": r["away"],
                    "home_goals": int(r["home_goals"]), "away_goals": int(r["away_goals"]),
                    "home_ht_goals": num(r["ht_home"]), "away_ht_goals": num(r["ht_away"])})
        for k, v in st.get(int(r["fixture_id"]), {}).items():
            if k in row:
                row[k] = v
        rows.append(row)
    return pd.DataFrame(rows, columns=cols)


def normalize(df):
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"].astype(str).str[:10]).dt.strftime("%Y-%m-%d") + " 00:00:00"
    return df.sort_values(["date", "fixture_id"], kind="mergesort").reset_index(drop=True)


def check(league, old, new, added_ids, removed_ids):
    assert list(new.columns) == list(old.columns), "колоните"
    assert not new["fixture_id"].duplicated().any(), "дубликати"
    assert len(new) == len(old) + len(added_ids) - len(removed_ids), "брой"
    assert pd.to_datetime(new["date"], format="%Y-%m-%d %H:%M:%S").notna().all(), "дати"
    assert new[["home_goals", "away_goals"]].notna().all().all(), "голове"
    # старите редове - същите стойности (освен датата - нормализирана)
    o = old[~old["fixture_id"].isin(removed_ids)].set_index("fixture_id").sort_index()
    n = new[new["fixture_id"].isin(o.index)].set_index("fixture_id").sort_index()
    for c in o.columns:
        if c == "date":
            assert (o[c].astype(str).str[:10] == n[c].astype(str).str[:10]).all(), "дата се е сменила"
            continue
        a, b = o[c], n[c]
        if pd.api.types.is_numeric_dtype(a):
            ok = (a.isna() & b.isna()) | np.isclose(a.astype(float), b.astype(float), equal_nan=True)
        else:
            ok = (a.astype(str) == b.astype(str))
        assert ok.all(), f"колона {c} се е сменила"
    # новите редове - голове = API
    return True


def main():
    out_dir = sys.argv[sys.argv.index("--out") + 1]
    os.makedirs(out_dir, exist_ok=True)
    fxs = {lg: fixtures(lg) for lg in LEAGUES}
    owner = {}
    for lg, fx in fxs.items():
        for fid in fx["fixture_id"]:
            owner.setdefault(int(fid), lg)
    olds = {lg: pd.read_csv(f"{lg}_merged_full.csv", low_memory=False) for lg in LEAGUES}
    table, moves = [], {}
    for lg in LEAGUES:
        m, fx = olds[lg], fxs[lg]
        ft = fx[fx["status"] == "FT"]
        first_season = int(m["season"].min())
        wrong = m[~m["fixture_id"].isin(fx["fixture_id"])]
        for fid in wrong["fixture_id"]:
            if owner.get(int(fid)) not in (None, lg):     # без fixtures за сезона (напр. 2018) - не е чужд
                moves[int(fid)] = (lg, owner[int(fid)])
        # проверка: головете на редовете във файла = API
        j = m.merge(ft[["fixture_id", "home_goals", "away_goals"]], on="fixture_id", suffixes=("", "_api"))
        bad_goals = int(((j["home_goals"] != j["home_goals_api"]) | (j["away_goals"] != j["away_goals_api"])).sum())
        for s in sorted(set(ft["season"]) | set(m["season"])):
            if s < FROM_SEASON:
                continue
            fs = ft[ft["season"] == s]
            ms = m[m["season"] == s]
            miss = int((~fs["fixture_id"].isin(m["fixture_id"])).sum())
            table.append({"league": lg, "season": int(s), "csv": len(ms), "api_ft": len(fs), "missing": miss,
                          "csv_other_league": int(ms["fixture_id"].isin([f for f, v in moves.items() if v[0] == lg]).sum()),
                          "in_scope": bool(s >= first_season), "goals_mismatch_league": bad_goals})
    tab = pd.DataFrame(table)
    tab.to_csv(DUPKI_CSV, index=False)
    print(tab[(tab.missing > 0) | (tab.csv_other_league > 0)].to_string(index=False))
    print("местене:", moves)

    changed = {}
    for lg in LEAGUES:
        m, fx = olds[lg], fxs[lg]
        first_season = int(m["season"].min())
        ft = fx[(fx["status"] == "FT") & (fx["season"] >= max(FROM_SEASON, first_season))]
        fx_new = ft[~ft["fixture_id"].isin(m["fixture_id"])]
        moved_in = [fid for fid, (src, dst) in moves.items() if dst == lg]
        fx_new = fx_new[~fx_new["fixture_id"].isin(moved_in)]
        removed = [fid for fid, (src, dst) in moves.items() if src == lg]
        if not len(fx_new) and not moved_in and not removed:
            continue
        add = new_rows(lg, fx_new, list(m.columns))
        for fid in moved_in:
            src = olds[moves[fid][0]]
            r = src[src["fixture_id"] == fid].reindex(columns=m.columns)
            add = pd.concat([add, r], ignore_index=True)
        new = normalize(pd.concat([m[~m["fixture_id"].isin(removed)], add], ignore_index=True))
        for c in m.columns:                    # целите колони остават цели
            if pd.api.types.is_integer_dtype(m[c]) and new[c].notna().all():
                new[c] = new[c].astype("int64")
        added_ids = list(add["fixture_id"].astype(int))
        check(lg, m, new, added_ids, removed)
        # новите редове: голове = API (FT)
        api = fx.set_index("fixture_id")
        nn = new[new["fixture_id"].isin(added_ids)].set_index("fixture_id")
        assert (nn["home_goals"].astype(int) == api.loc[nn.index, "home_goals"].astype(int)).all()
        assert (nn["away_goals"].astype(int) == api.loc[nn.index, "away_goals"].astype(int)).all()
        new.to_csv(os.path.join(out_dir, f"{lg}_merged_full.csv"), index=False)
        stat_cols = [c for c in m.columns if c.startswith("home_") and c not in ("home_team", "home_goals", "home_ht_goals")]
        with_stats = int(nn[stat_cols].notna().any(axis=1).sum()) if stat_cols else 0
        changed[lg] = {"old": len(m), "new": len(new), "added": len(added_ids), "removed": len(removed),
                       "added_with_stats": with_stats,
                       "added_by_season": {int(k): int(v) for k, v in nn.groupby("season").size().items()}}
        print(lg, changed[lg])
    json.dump(changed, open(os.path.join(out_dir, "changed.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
