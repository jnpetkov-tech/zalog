"""
validation/otbrana_features.py - задачата „сила на състава, втори опит“ (27.09.2026).
Ковариатите на настройките А-Д (определенията - PROGRESS_OTBRANA.md т.2, записани
преди резултатите; кандидати/365 дни/отсъстващ = както в validation/golmaistor_20260925.py).

За всеки отбор-мач с протокол по играчи (10-те лиги, и историческите мачове):
- def_abs  (А): колко от отбранителната тройка (вратарят G с най-много минути + двамата
                защитници D с най-много минути, 365 дни, сред кандидатите) не са играли.
- def_w    (Б): сума по отсъстващите от тройката на свития им дял от минутите на отбора:
                (мин_i + 5*90*r̄) / (90*(мачове_365 + 5)); r̄ - средният несвит дял на член
                на тройка във всички отбор-мачове ПРЕДИ датата.
- att_shots(В): сума на свитите удари/90 на отсъстващите от тримата с най-висок свит
                удари/90: (удари + 5*s̄) / (мин_extra/90 + 5); s̄ - общото удари/90 в
                `_extra` преди датата. Мач в `_extra` без стойност за удари = 0 удара.
- def_dev  (Г): def_abs минус средното def_abs на отбора в последните му 10 отбор-мача с
                изчислена стойност (< 3 такива -> 0).
- att_dev  (Д): att_shots минус средното att_shots по същия начин.
Отбор-мач без протокол или с < 5 предишни мача с протокол -> всички 0 (= не се знае).

Изход: /tmp/otbrana_feat.pkl (fixture_id, team, date, status, def_abs, def_w, att_shots,
def_dev, att_dev, def_players, att_players) + validation/otbrana_20260927_features.csv.
Употреба: venv/bin/python3 validation/otbrana_features.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal",
           "champions_league", "europa_league", "conference_league"]
OUT_PKL = "/tmp/otbrana_feat.pkl"
OUT_CSV = "validation/otbrana_20260927_features.csv"
K = 5.0
LAST_N = 10
HIST_DAYS = 365
MIN_PRIOR = 5
USUAL_N = 10
USUAL_MIN = 3
COLS = ["def_abs", "def_w", "att_shots", "def_dev", "att_dev"]


def load():
    pms, exs, dates = [], [], []
    for lg in LEAGUES:
        m = pd.read_csv(f"{lg}_merged_full.csv", usecols=["fixture_id", "date"]).drop_duplicates("fixture_id")
        m["date"] = pd.to_datetime(m["date"].astype(str).str[:10])
        dates.append(m)
        p = pd.read_csv(f"{lg}_player_stats.csv").merge(m, on="fixture_id", how="inner")
        pms.append(p)
        e = pd.read_csv(f"{lg}_player_stats_extra.csv",
                        usecols=["fixture_id", "team", "player_id", "minutes", "shots_total"])
        exs.append(e.merge(m, on="fixture_id", how="inner"))
    PM = pd.concat(pms, ignore_index=True).drop_duplicates(subset=["fixture_id", "player_id"])
    PM["minutes"] = PM["minutes"].fillna(0).clip(lower=0)
    PM = PM[PM.minutes > 0].sort_values("date")
    EX = pd.concat(exs, ignore_index=True).drop_duplicates(subset=["fixture_id", "player_id"])
    EX["minutes"] = EX["minutes"].fillna(0).clip(lower=0)
    EX["shots_total"] = EX["shots_total"].fillna(0)
    EX = EX[EX.minutes > 0].sort_values("date")
    return PM, EX


def cum_rate(df, num, den_min):
    """функция d -> сума(num) / (сума(мин)/90) за редовете СТРОГО преди d."""
    daily = df.groupby("date")[[num, den_min]].sum().sort_index().cumsum()
    idx = daily.index.values

    def rate(d):
        i = np.searchsorted(idx, np.datetime64(d), side="left") - 1
        if i < 0:
            return np.nan
        return daily[num].iloc[i] / (daily[den_min].iloc[i] / 90.0)
    return rate


def build():
    PM, EX = load()
    shot_rate = cum_rate(EX, "shots_total", "minutes")
    ex_by_team = {t: g for t, g in EX.groupby("team")}
    rows = []
    for team, g in PM.groupby("team"):
        fx = g.drop_duplicates("fixture_id")[["fixture_id", "date"]].sort_values("date")
        played = g.groupby("fixture_id")["player_id"].apply(set).to_dict()
        ex_t = ex_by_team.get(team)
        for f, d in zip(fx.fixture_id, fx.date):
            base = {"fixture_id": int(f), "team": team, "date": d}
            prev = g[g.date < d]
            prev_fx = prev.drop_duplicates("fixture_id")[["fixture_id", "date"]]
            if len(prev_fx) < MIN_PRIOR:
                rows.append({**base, "status": "малко история"})
                continue
            now = played[f]
            last = set(prev_fx.fixture_id.iloc[-LAST_N:])
            cand = set(prev[prev.fixture_id.isin(last)].player_id)
            d0 = d - pd.Timedelta(days=HIST_DAYS)
            hist = prev[(prev.date >= d0) & prev.player_id.isin(cand)]
            n365 = prev_fx[prev_fx.date >= d0].shape[0]
            agg = hist.groupby("player_id").agg(mins=("minutes", "sum"), pos=("position", "last"),
                                                name=("player_name", "last"))
            gk = agg[agg.pos == "G"].sort_values("mins", ascending=False).head(1)
            df = agg[agg.pos == "D"].sort_values("mins", ascending=False).head(2)
            trio = pd.concat([gk, df])
            absent = [pid not in now for pid in trio.index]
            # удари - от _extra, същите кандидати и 365 дни
            s_bar = shot_rate(d)
            if ex_t is not None and not np.isnan(s_bar):
                eh = ex_t[(ex_t.date < d) & (ex_t.date >= d0) & ex_t.player_id.isin(cand)]
                ea = eh.groupby("player_id").agg(sh=("shots_total", "sum"), m=("minutes", "sum"))
            else:
                ea = pd.DataFrame(columns=["sh", "m"])
            if np.isnan(s_bar):
                s_bar = 0.0
            sc = pd.DataFrame(index=sorted(cand))
            sc = sc.join(ea).fillna(0.0)
            sc["rate"] = (sc.sh + K * s_bar) / (sc.m / 90.0 + K)
            sc = sc.join(agg[["mins", "name"]]).fillna({"mins": 0.0})
            top = sc.sort_values(["rate", "mins"], ascending=False).head(3)
            rows.append({**base, "status": "ok", "n365": n365,
                         "def_abs": int(sum(absent)),
                         "trio_share": list(trio.mins / (90.0 * max(n365, 1))),
                         "trio_mins": list(trio.mins), "trio_absent": absent,
                         "att_shots": float(sum(r for pid, r in zip(top.index, top.rate) if pid not in now)),
                         "def_players": "; ".join(str(x) for x in trio["name"]),
                         "att_players": "; ".join(str(x) for x in top["name"])})
    F = pd.DataFrame(rows)
    # Б: r̄ - средният несвит дял на член на тройка в отбор-мачовете ПРЕДИ датата
    ok = F[F.status == "ok"].sort_values("date")
    per_day = ok.groupby("date")["trio_share"].agg(lambda s: (sum(sum(x) for x in s), sum(len(x) for x in s)))
    cs = np.cumsum([v[0] for v in per_day]), np.cumsum([v[1] for v in per_day])
    days = per_day.index.values
    fallback = cs[0][-1] / cs[1][-1]

    def rbar(d):
        i = np.searchsorted(days, np.datetime64(d), side="left") - 1
        return fallback if i < 0 or cs[1][i] == 0 else cs[0][i] / cs[1][i]

    def def_w(r):
        if r.status != "ok":
            return 0.0
        rb = rbar(r.date)
        return float(sum((m + K * 90.0 * rb) / (90.0 * (r.n365 + K))
                         for m, a in zip(r.trio_mins, r.trio_absent) if a))
    F["def_w"] = [def_w(r) for r in F.itertuples()]
    F[["def_abs", "att_shots"]] = F[["def_abs", "att_shots"]].fillna(0.0)
    # Г, Д: отклонение от обичайното (последните 10 изчислени мача на отбора, само минали)
    F = F.sort_values(["team", "date"]).reset_index(drop=True)
    for src, dst in (("def_abs", "def_dev"), ("att_shots", "att_dev")):
        vals = F[src].where(F.status == "ok")
        prev_mean = vals.groupby(F.team).transform(lambda s: s.shift(1).rolling(USUAL_N, min_periods=USUAL_MIN).mean())
        # rolling върху NaN (мачове „малко история“) - min_periods брои само изчислените
        F[dst] = np.where((F.status == "ok") & prev_mean.notna(), F[src] - prev_mean, 0.0)
    F.loc[F.status != "ok", COLS] = 0.0
    keep = ["fixture_id", "team", "date", "status"] + COLS + ["def_players", "att_players"]
    F = F[keep]
    F.to_pickle(OUT_PKL)
    F.assign(date=F.date.dt.date.astype(str)).round(4).to_csv(OUT_CSV, index=False)
    okF = F[F.status == "ok"]
    print(F.status.value_counts().to_dict())
    print(okF[COLS].describe().round(3).to_string())
    return F


if __name__ == "__main__":
    build()
