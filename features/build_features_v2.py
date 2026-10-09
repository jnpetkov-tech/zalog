"""features/build_features_v2.py - таблица с признаци v2 (ZADACHA_VSICHKO_OT_API, етап 1, 09.10.2026).

= features/features_table.csv.gz (непроменена, ползва я живият слой) + нови колони h_*/a_* от изтеглените на 01.10 данни. Пише
features/features_table_v2.csv.gz. Никой жив код не чете v2.

ПРАВИЛОТО НА ВРЕМЕТО (както в build_features.py): признакът на мач M (начало ts) - само от мачове/записи със ts < ts на M, плюс
предмачовата информация за самия M (състав). Рейтингите на самия M и на по-късни мачове - никога.

Нови блокове (имена без h_/a_; "ранно" = известно дни преди мача, "късно" = след съставите):
 E - рейтинг (features/player_ratings.csv от суровите /fixtures?ids=; features/extract_ratings.py)
     rat_usual     ранно  среден рейтинг на обичайните титуляри (>= 50% стартове в последните 10 мача със състав); рейтинг на играч =
                          средно от последните му 10 мача с рейтинг преди M (всякакъв отбор), поне 3
     rat_team5     ранно  средният рейтинг на титулярите на отбора в последните му 5 мача с рейтинги
     rat_xi        късно  същото като rat_usual, но за днешните 11 титуляри
     rat_xi_gap    късно  rat_xi - rat_usual (колко по-слаб/силен е днешният състав от обичайния)
     rat_absent    късно  среден рейтинг на отсъстващите обичайни титуляри (NaN, ако няма отсъстващи)
 F - извън игра (api_sidelined.csv) - към датата D на мача; "отбор" = играчите в групите на отбора в последните 10 мача със състав
     sid_n, sid_usual_w          start <= D и (end >= D или празно)                          (вариант с края - риск от изтичане)
     sidS_n, sidS_usual_w        start в [D-21, D], краят не се гледа                       (вариант само със start)
     ВНИМАНИЕ: api_sidelined.csv няма записи от 10.2025 до 05.2026 (виж validation/sloy_v2_20261009.md) - блокът е само за справка.
 G - трансфери (api_transfers.csv)
     tr_in60       ранно  играчи, дошли в отбора през последните 60 дни (дата в (D-60, D])
     tr_out_usual60 ранно играчи, напуснали отбора през последните 60 дни, които преди напускането са били обичайни титуляри
 H - възраст (api_profiles.csv, birth_date)
     age_usual     ранно  средна възраст (години към D) на обичайните титуляри
     age_xi        късно  средна възраст на днешните титуляри

Употреба: nice -n 19 venv/bin/python3 features/build_features_v2.py [--only id1,id2]   (--only - за leak_check_v2)
"""
import bisect
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from features import build_features as bf  # noqa: E402

BASE = os.path.join(ROOT, "features", "features_table.csv.gz")
OUT = os.path.join(ROOT, "features", "features_table_v2.csv.gz")
RATINGS = os.path.join(ROOT, "features", "player_ratings.csv")
N_PLAYER = 10          # рейтинг на играч: последните 10 мача с рейтинг
MIN_PLAYER = 3
N_TEAM = 5
TR_DAYS = 60
SID_START_DAYS = 21
DAY = 86400

NEW_COLS = ["rat_usual", "rat_team5", "rat_xi", "rat_xi_gap", "rat_absent",
            "sid_n", "sid_usual_w", "sidS_n", "sidS_usual_w",
            "tr_in60", "tr_out_usual60",
            "age_usual", "age_xi"]
BLOCK_COLS = {"E": ["rat_usual", "rat_team5", "rat_xi", "rat_xi_gap", "rat_absent"],
              "F": ["sid_n", "sid_usual_w", "sidS_n", "sidS_usual_w"],
              "G": ["tr_in60", "tr_out_usual60"],
              "H": ["age_usual", "age_xi"]}


def _ts(s):
    return pd.to_datetime(s, errors="coerce", utc=True).map(lambda x: x.timestamp() if pd.notna(x) else np.nan)


class Sources:
    def __init__(self, raw=None):
        self.raw = raw if raw is not None else bf.index_raw(bf.load_raw())
        self.recs = bf.team_match_records(self.raw)
        self.hist = bf.History(self.recs)
        fx = self.raw["fx"]
        self.fx_by_id = fx.set_index("fixture_id")
        ts_of = dict(zip(fx["fixture_id"], fx["ts"]))
        # --- рейтинги
        r = pd.read_csv(RATINGS)
        r["ts"] = r["fixture_id"].map(ts_of).fillna(r["ts"])
        r = r[r["ts"].notna() & r["rating"].notna() & (r["rating"] > 0)]
        self.p_ts, self.p_cs = {}, {}
        for pid, g in r.sort_values(["ts", "fixture_id"]).groupby("player_id"):
            self.p_ts[int(pid)] = g["ts"].to_numpy(float)
            self.p_cs[int(pid)] = np.concatenate([[0.0], np.cumsum(g["rating"].to_numpy(float))])
        st = r[~r["substitute"].astype(bool)].groupby(["fixture_id", "team_id"]).agg(ts=("ts", "first"), v=("rating", "mean"))
        self.t_ts, self.t_v = {}, {}
        for tid, g in st.reset_index().sort_values("ts").groupby("team_id"):
            self.t_ts[int(tid)] = g["ts"].to_numpy(float)
            self.t_v[int(tid)] = g["v"].to_numpy(float)
        # --- извън игра
        s = pd.read_csv(os.path.join(ROOT, "api_sidelined.csv")).drop_duplicates(["player_id", "type", "start", "end"])
        s["s"] = _ts(s["start"])
        s["e"] = _ts(s["end"]) + DAY - 1          # краят включително (до края на деня)
        self.sid = {}
        for pid, g in s[s["s"].notna()].groupby("player_id"):
            self.sid[int(pid)] = list(zip(g["s"].to_numpy(float), g["e"].to_numpy(float)))
        # --- трансфери (уникални по играч, дата, от, към)
        t = pd.read_csv(os.path.join(ROOT, "api_transfers.csv")).drop_duplicates(["player_id", "date", "in_team_id", "out_team_id"])
        t["d"] = _ts(t["date"])
        t = t[t["d"].notna()]
        self.tr_in, self.tr_out = {}, {}
        for r_ in t.itertuples(index=False):
            if r_.in_team_id == r_.in_team_id:
                self.tr_in.setdefault(int(r_.in_team_id), []).append((r_.d, int(r_.player_id)))
            if r_.out_team_id == r_.out_team_id:
                self.tr_out.setdefault(int(r_.out_team_id), []).append((r_.d, int(r_.player_id)))
        for dct in (self.tr_in, self.tr_out):
            for k in dct:
                dct[k].sort()
        self._usual_cache = {}
        # --- възраст
        p = pd.read_csv(os.path.join(ROOT, "api_profiles.csv")).drop_duplicates("player_id", keep="last")
        p["b"] = _ts(p["birth_date"])
        self.birth = {int(a): b for a, b in zip(p["player_id"], p["b"]) if b == b}

    # ------------------------------------------------------------------------------------------- помощни
    def p_avg(self, pid, ts):
        arr = self.p_ts.get(int(pid))
        if arr is None:
            return np.nan
        i = bisect.bisect_left(arr, ts)
        lo = max(0, i - N_PLAYER)
        if i - lo < MIN_PLAYER:
            return np.nan
        cs = self.p_cs[int(pid)]
        return (cs[i] - cs[lo]) / (i - lo)

    def usual(self, tid, ts):
        """(обичайни титуляри {играч: дял}, група от последните 10 мача със състав) към ts."""
        prior = self.hist.prior(int(tid), ts)
        pl = [r for r in prior if r["has_lineup"]][-bf.LINEUP_N:]
        if len(pl) < 3:
            return {}, set()
        starts = {}
        roster = set()
        for r in pl:
            for p in r["starters"]:
                starts[p] = starts.get(p, 0) + 1
            roster |= set(r["squad"])
        n = float(len(pl))
        return {p: c / n for p, c in starts.items() if c / n >= bf.USUAL_SHARE}, roster

    def was_usual(self, tid, pid, ts):
        key = (tid, ts)
        if key not in self._usual_cache:
            self._usual_cache[key] = self.usual(tid, ts)[0]
        return pid in self._usual_cache[key]

    def _mean(self, vals, need):
        v = [x for x in vals if x == x]
        return float(np.mean(v)) if len(v) >= need else np.nan

    # ------------------------------------------------------------------------------------------- признаци на страна
    def side(self, fid, tid, ts):
        out = {c: np.nan for c in NEW_COLS}
        usual, roster = self.usual(tid, ts)
        lu = (self.raw["idx"]["lu"].get(fid) or {}).get(int(tid))
        xi = list(lu["starters"]) if lu is not None and len(lu["starters"]) >= 9 else None
        squad = set(lu["squad"]) if xi is not None else None
        # E
        if usual:
            out["rat_usual"] = self._mean([self.p_avg(p, ts) for p in usual], 5)
        tt = self.t_ts.get(int(tid))
        if tt is not None:
            i = bisect.bisect_left(tt, ts)
            if i >= 3:
                out["rat_team5"] = float(np.mean(self.t_v[int(tid)][max(0, i - N_TEAM):i]))
        if xi is not None:
            out["rat_xi"] = self._mean([self.p_avg(p, ts) for p in xi], 7)
            if out["rat_xi"] == out["rat_xi"] and out["rat_usual"] == out["rat_usual"]:
                out["rat_xi_gap"] = out["rat_xi"] - out["rat_usual"]
            if usual:
                absent = [p for p in usual if p not in squad]
                if absent:
                    out["rat_absent"] = self._mean([self.p_avg(p, ts) for p in absent], 1)
        # F
        if roster:
            n = w = nS = wS = 0.0
            for p in roster:
                iv = self.sid.get(int(p), ())
                cov = any(s <= ts and (e != e or e >= ts) for s, e in iv)
                covS = any(ts - SID_START_DAYS * DAY <= s <= ts for s, _e in iv)
                n += cov
                nS += covS
                if p in usual:
                    w += usual[p] * cov
                    wS += usual[p] * covS
            out.update({"sid_n": n, "sid_usual_w": w, "sidS_n": nS, "sidS_usual_w": wS})
        # G
        lst = self.tr_in.get(int(tid), [])
        lo = bisect.bisect_right(lst, (ts - TR_DAYS * DAY, 10 ** 12))
        hi = bisect.bisect_left(lst, (ts, -1))
        out["tr_in60"] = float(len({p for _d, p in lst[lo:hi]}))
        lst = self.tr_out.get(int(tid), [])
        lo = bisect.bisect_right(lst, (ts - TR_DAYS * DAY, 10 ** 12))
        hi = bisect.bisect_left(lst, (ts, -1))
        out["tr_out_usual60"] = float(len({p for d, p in lst[lo:hi] if self.was_usual(int(tid), p, d)}))
        # H
        if usual:
            out["age_usual"] = self._mean([(ts - self.birth[p]) / (365.25 * DAY) for p in usual if p in self.birth], 5)
        if xi is not None:
            out["age_xi"] = self._mean([(ts - self.birth[p]) / (365.25 * DAY) for p in xi if p in self.birth], 7)
        return out

    def row(self, fid):
        f = self.fx_by_id.loc[fid]
        ts = int(f["ts"])
        res = {}
        for side, tid in (("h", int(f["home_id"])), ("a", int(f["away_id"]))):
            res.update({f"{side}_{k}": v for k, v in self.side(fid, tid, ts).items()})
        return res


def build(base, src):
    rows = []
    for i, fid in enumerate(base["fixture_id"]):
        rows.append(src.row(fid) if fid in src.fx_by_id.index else {})
        if i % 3000 == 0:
            print(i, flush=True)
    new = pd.DataFrame(rows, index=base.index)
    return pd.concat([base, new], axis=1)


def main():
    base = pd.read_csv(BASE, float_precision="round_trip")
    if "--only" in sys.argv:
        ids = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
        base = base[base["fixture_id"].isin(ids)]
    src = Sources()
    out = build(base, src)
    out.to_csv(OUT, index=False)
    cov = {c: round(float(out[f"h_{c}"].notna().mean()), 3) for c in NEW_COLS}
    print(len(out), "реда ->", OUT)
    print("попълнени (домакин):", cov)


if __name__ == "__main__":
    main()
