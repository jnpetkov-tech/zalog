"""validation/pazar_poluvreme_20261002.py - т.5б: резултат на полувремето (1/X/2) и кой вкарва пръв (домакин/никой/гост).
Настройки: pazari_nastroyki_20261002.md. Изход: validation/pazar_poluvreme_20261002.md.
Употреба: nice -n 19 venv/bin/python3 validation/pazar_poluvreme_20261002.py"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import poisson

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pazar_lib_20261002 as PL  # noqa: E402

LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal", "champions_league", "europa_league",
           "conference_league", "france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
SHARE_DAYS = 730
G = 10


def load_fixtures():
    parts = []
    for lg in LEAGUES:
        f = os.path.join(PL.ROOT, f"{lg}_fixtures.csv")
        if os.path.exists(f):
            parts.append(pd.read_csv(f, low_memory=False))
    fx = pd.concat(parts, ignore_index=True).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["status"].isin(["FT", "AET", "PEN"])].copy()
    for c in ("ht_home", "ht_away", "ft_home", "ft_away", "timestamp"):
        fx[c] = pd.to_numeric(fx[c], errors="coerce")
    return fx.dropna(subset=["ht_home", "ht_away", "ft_home", "ft_away", "timestamp"])


def first_scorer():
    """fixture_id -> 'h'/'a' (първият гол по event_index; автогол за противника) и брой голове по събитията."""
    out = {}
    for lg in LEAGUES:
        for name in (f"{lg}_events.csv", f"{lg}_events_pre2024.csv"):
            f = os.path.join(PL.ROOT, name)
            if not os.path.exists(f):
                continue
            ev = pd.read_csv(f, low_memory=False, usecols=["fixture_id", "event_index", "team_id", "type", "detail"])
            ev = ev[(ev["type"] == "Goal") & (ev["detail"] != "Missed Penalty")].sort_values(["fixture_id", "event_index"])
            for fid, g in ev.groupby("fixture_id"):
                out[int(fid)] = (list(zip(g["team_id"].astype(int), g["detail"])), len(g))
    return out


def ht_shares(fx, week):
    """Дял на головете на полувремето (домакин, гост) в лигата - само от мачове преди седмицата, последните SHARE_DAYS дни."""
    t0 = week.timestamp() - SHARE_DAYS * 86400
    h = fx[(fx["timestamp"] < week.timestamp()) & (fx["timestamp"] >= t0)]
    return {lg: (g["ht_home"].sum() / max(g["ft_home"].sum(), 1), g["ht_away"].sum() / max(g["ft_away"].sum(), 1))
            for lg, g in h.groupby("league")}


def main():
    late = PL.late_ab()
    early = PL.early_table()
    fx = load_fixtures()
    fxi = fx.set_index("fixture_id")
    late = late[late["fixture_id"].isin(fxi.index)].copy()
    late["d"] = pd.to_datetime(late["date"])
    late["week"] = late["d"] - pd.to_timedelta(late["d"].dt.weekday, unit="D")
    # --- полувреме
    sh = np.zeros(len(late))
    sa = np.zeros(len(late))
    for wk, idx in late.groupby("week").groups.items():
        s = ht_shares(fx, pd.Timestamp(wk, tz="UTC"))
        for i in idx:
            lg = late.at[i, "league"]
            sh[late.index.get_loc(i)], sa[late.index.get_loc(i)] = s.get(lg, (0.44, 0.44))
    lh, la = late["lam1"].to_numpy() * sh, late["mu1"].to_numpy() * sa
    ph, pa = poisson.pmf(np.arange(G)[None, :], lh[:, None]), poisson.pmf(np.arange(G)[None, :], la[:, None])
    m = ph[:, :, None] * pa[:, None, :]
    X, Y = np.meshgrid(np.arange(G), np.arange(G), indexing="ij")
    P_ht = np.column_stack([m[:, X > Y].sum(1), m[:, X == Y].sum(1), m[:, X < Y].sum(1)])
    P_ht = P_ht / P_ht.sum(1, keepdims=True)
    hh, ha = fxi.loc[late["fixture_id"], "ht_home"].to_numpy(), fxi.loc[late["fixture_id"], "ht_away"].to_numpy()
    Y_ht = np.column_stack([hh > ha, hh == ha, hh < ha]).astype(float)
    ef = fxi.reindex(early["fixture_id"]).dropna(subset=["ht_home"])
    b_ht = np.array([(ef.ht_home > ef.ht_away).mean(), (ef.ht_home == ef.ht_away).mean(), (ef.ht_home < ef.ht_away).mean()])
    ok1, L1, n1 = PL.verdict("полувреме 1/X/2", P_ht, Y_ht, b_ht)
    # --- кой вкарва пръв
    fs = first_scorer()
    pm = PL.matrix(late["lam1"], late["mu1"], late["rho"])
    p00 = pm[:, 0, 0]
    share = late["lam1"].to_numpy() / (late["lam1"].to_numpy() + late["mu1"].to_numpy())
    P_fs = np.column_stack([(1 - p00) * share, p00, (1 - p00) * (1 - share)])
    keep, Y_fs = [], []
    n_drop_noev = n_drop_mismatch = 0
    for k, r in enumerate(late.itertuples()):
        tot = int(r.hg + r.ag)
        if tot == 0:
            keep.append(k)
            Y_fs.append([0, 1, 0])
            continue
        e = fs.get(int(r.fixture_id))
        if e is None:
            n_drop_noev += 1
            continue
        goals, n = e
        if n != tot:
            n_drop_mismatch += 1
            continue
        hid = int(fxi.at[r.fixture_id, "home_id"])
        team, detail = goals[0]
        home_first = (team == hid) != (detail == "Own Goal")
        keep.append(k)
        Y_fs.append([1, 0, 0] if home_first else [0, 0, 1])
    keep = np.array(keep)
    Y_fs = np.array(Y_fs, float)
    # b: ранната половина, същият метод
    eh = []
    for r in early.itertuples():
        tot = int(r.hg + r.ag)
        if tot == 0:
            eh.append([0, 1, 0])
            continue
        e = fs.get(int(r.fixture_id))
        if e is None or e[1] != tot or r.fixture_id not in fxi.index:
            continue
        team, detail = e[0][0]
        eh.append([1, 0, 0] if (team == int(fxi.at[r.fixture_id, "home_id"])) != (detail == "Own Goal") else [0, 0, 1])
    b_fs = np.array(eh, float).mean(0)
    ok2, L2, n2 = PL.verdict("кой вкарва пръв (Д/никой/Г)", P_fs[keep], Y_fs, b_fs)
    lines = ["# Т.5б — полувреме и кой вкарва пръв (02.10.2026)", "",
             "Настройки и критерии (записани преди резултатите): `validation/pazari_nastroyki_20261002.md`. Ядро+слой AB walk-forward, "
             "късната половина (дата ≥ 2025-09-23).", "",
             f"Полувреме: {len(late)} мача с резултат на полувремето. Кой вкарва пръв: {len(keep)} мача "
             f"(отпаднали: {n_drop_noev} без събития, {n_drop_mismatch} с брой голове в събитията ≠ резултата).", ""] + PL.HEADER + L1 + L2
    lines += ["", f"Реални честоти (късна): полувреме 1/X/2 {Y_ht.mean(0).round(3).tolist()}, модел {P_ht.mean(0).round(3).tolist()}; "
              f"пръв Д/никой/Г {Y_fs.mean(0).round(3).tolist()}, модел {P_fs[keep].mean(0).round(3).tolist()}.", "",
              "## Решение", "", f"- полувреме 1/X/2: **{'влиза' if ok1 else 'не влиза'}** (a = {n1['a']:.3f})",
              f"- кой вкарва пръв: **{'влиза' if ok2 else 'не влиза'}** (a = {n2['a']:.3f})", ""]
    open(os.path.join(PL.ROOT, "validation", "pazar_poluvreme_20261002.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
