"""
validation/sila_features.py - ZADACHA_GOLQMA.md, Етап 4 (24.09.2026). Силата на играч
и на конкретните единайсет - САМО от обективното (минути, голове, асистенции; удари -
виж бележката долу), без рейтинга на доставчика.

Данни: {лига}_player_stats.csv (10 лиги) + {лига}_merged_full.csv (дата, отбори, голове)
+ очакваните голове на СЕГАШНИЯ модел за всеки мач от мерилото (walk-forward,
/tmp/final_b_20260924.pkl, xi_mult=1 - повторната сметка на живия модел от
validation/final_b_20260924.py; контрол там: разлика с живия <1e-6).

1) Сила на играч "с него / без него" (принципът от задачата): за всеки мач на отбора
   остатъкът r = (голова разлика) - (очаквана голова разлика от модела) - колко по-добре
   от очакваното е изиграл отборът. Делът на играча в мача s = минути/90 (таван 1).
   С него = средният r, претеглен с s; без него = средният r, претеглен с (1-s), върху
   мачовете на отбора между първата и последната му поява в протокола (в мачове, в
   които не е в протокола - s = 0). Разликата се свива към 0:
       сила = (с - без) * n / (n + K),   n = n_с * n_без / (n_с + n_без)  (в "мачове по 90 мин")
   Играч с малко минути (или винаги на терена - няма "без него") -> около 0.
2) Производителност: (голове + асистенции) на 90 мин, свити към средното за поста
   (G/D/M/F) с K2 въображаеми мача: (GA + K2 * ср) / (мин/90 + K2) - ср.
3) Сила на единайсетте в мача: сума на силата на 11-те с най-много минути (изгонен играч
   се брои като изиграл 90 - иначе изгонването, което се случва В мача, би изглеждало
   като "по-слаб състав" - изтичане). Ковариатата = силата на ТЕЗИ единайсет минус
   обичайната за отбора (средното от последните N_USUAL мача му, със същите сили) -
   моделът вече знае колко е силен отборът; ковариатата казва колко е по-силен/слаб
   съставът днес от обичайния му. Вариант "сума": суровата сила на единайсетте (без
   изваждане на обичайната) - носи и сведение за отбора изобщо.

Всичко за мач от седмица W (понеделник) е смятано САМО от мачове преди W - и за
тестовите мачове, и за историята, от която се учи моделът.

Бележка за изтичане: единайсетте се определят от минутите в самия мач (кой е играл) -
това е информацията, която се знае ~1 час преди мача (обявените състави); дребното
изтичане: играч, сменен рано заради контузия, губи място от смяната си.
Удари: старите CSV-та нямат удари (скриптът не ги е пазел); новите мачове ги имат в
{лига}_player_stats_extra.csv - при повторна сметка след догонването влизат.
"""
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal",
           "champions_league", "europa_league", "conference_league"]
PKL = "/tmp/final_b_20260924.pkl"


def monday(d):
    d = pd.to_datetime(d)
    return d - pd.to_timedelta(d.dt.weekday, unit="D")


def load_tables():
    """PM - играч в мач; TM - отбор в мач (с остатъка r, ако мачът е в мерилото)."""
    allt, _ = pd.read_pickle(PKL)
    pred = allt[allt.xi_mult == 1.0][["league", "fixture_id", "lam", "mu"]]
    pms, tms = [], []
    for lg in LEAGUES:
        p = pd.read_csv(os.path.join(ROOT, f"{lg}_player_stats.csv"))
        p = p.drop_duplicates(subset=["fixture_id", "player_id"])
        m = pd.read_csv(os.path.join(ROOT, f"{lg}_merged_full.csv"),
                        usecols=["fixture_id", "date", "home_team", "away_team", "home_goals", "away_goals"])
        m = m.dropna(subset=["home_goals", "away_goals"])
        m["date"] = pd.to_datetime(m["date"].astype(str).str[:10])
        m = m[m.fixture_id.isin(set(p.fixture_id))].merge(pred[pred.league == lg][["fixture_id", "lam", "mu"]],
                                                           on="fixture_id", how="left")
        home = pd.DataFrame({"fixture_id": m.fixture_id, "date": m.date, "team": m.home_team, "side": "home",
                             "gf": m.home_goals, "ga": m.away_goals, "xf": m.lam, "xa": m.mu})
        away = pd.DataFrame({"fixture_id": m.fixture_id, "date": m.date, "team": m.away_team, "side": "away",
                             "gf": m.away_goals, "ga": m.home_goals, "xf": m.mu, "xa": m.lam})
        tm = pd.concat([home, away], ignore_index=True).assign(league=lg)
        tm["r"] = (tm.gf - tm.ga) - (tm.xf - tm.xa)
        tms.append(tm)
        p = p.merge(tm[["fixture_id", "team", "date"]], on=["fixture_id", "team"], how="inner")
        p["league"] = lg
        pms.append(p)
    PM = pd.concat(pms, ignore_index=True)
    TM = pd.concat(tms, ignore_index=True).drop_duplicates(subset=["fixture_id", "team"])
    PM = PM.drop_duplicates(subset=["fixture_id", "player_id"])
    PM["minutes"] = PM["minutes"].fillna(0).clip(lower=0)
    PM["s"] = (PM["minutes"] / 90.0).clip(upper=1.0)
    PM["ga_cnt"] = PM["goals"].fillna(0) + PM["assists"].fillna(0)
    PM["red"] = PM["red_cards"].fillna(0) > 0
    PM["pos"] = PM["position"].fillna("M")
    PM["week"] = monday(PM["date"])
    TM["week"] = monday(TM["date"])
    # единайсетте: 11-те с най-много минути; изгонен = 90
    PM["xi_key"] = np.where(PM["red"], 90.0, PM["minutes"])
    PM = PM.sort_values(["fixture_id", "team", "xi_key"], ascending=[True, True, False])
    PM["xi_rank"] = PM.groupby(["fixture_id", "team"]).cumcount()
    PM["in_xi"] = (PM["xi_rank"] < 11) & (PM["xi_key"] > 0)
    return PM, TM


def player_ratings(PM, TM, before, K, K2, half_life=None):
    """Сили на играчите от мачовете с дата < before. Връща (onoff: Series, prod: Series)."""
    tm = TM[(TM.date < before)]
    pm = PM[(PM.date < before)]
    if pm.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    wt = (np.exp(-np.log(2) / half_life * (before - tm.date).dt.days.to_numpy())
          if half_life else np.ones(len(tm)))
    tm = tm.assign(w=wt)
    # --- с него / без него ---
    tmr = tm.dropna(subset=["r"])
    span = pm.groupby(["player_id", "team"])["date"].agg(["min", "max"]).reset_index()
    # всички мачове на отбора в периода на играча
    x = span.merge(tmr[["team", "fixture_id", "date", "r", "w"]], on="team")
    x = x[(x.date >= x["min"]) & (x.date <= x["max"])]
    x = x.merge(pm[["player_id", "fixture_id", "s"]], on=["player_id", "fixture_id"], how="left")
    x["s"] = x["s"].fillna(0.0)
    x["won"] = x.w * x.s
    x["woff"] = x.w * (1 - x.s)
    x["ron"] = x.won * x.r
    x["roff"] = x.woff * x.r
    g = x.groupby("player_id")[["won", "woff", "ron", "roff"]].sum()
    ok = (g.won > 0) & (g.woff > 0)
    diff = pd.Series(0.0, index=g.index)
    diff[ok] = g.ron[ok] / g.won[ok] - g.roff[ok] / g.woff[ok]
    n = pd.Series(0.0, index=g.index)
    n[ok] = g.won[ok] * g.woff[ok] / (g.won[ok] + g.woff[ok])
    onoff = diff * n / (n + K)
    # --- производителност ---
    pw = pm.merge(tm[["fixture_id", "team", "w"]], on=["fixture_id", "team"], how="left")
    pw["w"] = pw["w"].fillna(1.0)
    pw["n90"] = pw.w * pw.minutes / 90.0
    pw["gaw"] = pw.w * pw.ga_cnt
    pos_rate = pw.groupby("pos")[["gaw", "n90"]].sum()
    pos_rate = (pos_rate.gaw / pos_rate.n90.clip(lower=1e-9)).to_dict()
    gp = pw.groupby("player_id").agg(gaw=("gaw", "sum"), n90=("n90", "sum"), pos=("pos", "last"))
    prior = gp.pos.map(pos_rate).fillna(0.0)
    prod = (gp.gaw + K2 * prior) / (gp.n90 + K2) - prior
    return onoff, prod


def lineup_features(PM, TM, K=30.0, K2=10.0, half_life=None, n_usual=10):
    """За всеки (fixture_id, team): сила на единайсетте минус обичайната - две колони
    x_onoff, x_prod; смятано седмица по седмица само от мачове преди седмицата."""
    weeks = np.sort(TM["week"].unique())
    xi = PM[PM.in_xi][["fixture_id", "team", "player_id", "week", "date"]]
    team_hist = TM.sort_values("date")[["fixture_id", "team", "date", "week"]]
    out = []
    for w in weeks:
        w = pd.Timestamp(w)
        onoff, prod = player_ratings(PM, TM, w, K, K2, half_life)
        # мачовете от тази седмица + предишните n_usual на всеки отбор (за "обичайната")
        cur = team_hist[team_hist.week == w]
        if cur.empty:
            continue
        prev = team_hist[(team_hist.date < w) & team_hist.team.isin(set(cur.team))]
        prev = prev.groupby("team").tail(n_usual)
        rows = pd.concat([cur.assign(cur=True), prev.assign(cur=False)])
        xr = xi.merge(rows[["fixture_id", "team", "cur"]], on=["fixture_id", "team"])
        xr["onoff"] = xr.player_id.map(onoff).fillna(0.0)
        xr["prod"] = xr.player_id.map(prod).fillna(0.0)
        st = xr.groupby(["fixture_id", "team", "cur"])[["onoff", "prod"]].sum().reset_index()
        usual = st[~st.cur].groupby("team")[["onoff", "prod"]].mean()
        c = st[st.cur].merge(usual, left_on="team", right_index=True, how="left", suffixes=("", "_usual"))
        c["x_onoff"] = (c.onoff - c.onoff_usual).fillna(0.0)
        c["x_prod"] = (c["prod"] - c.prod_usual).fillna(0.0)
        # и суровата сила на единайсетте (без "минус обичайната") - включва и
        # колко силен е отборът изобщо, отвъд това, което моделът знае
        c["x_onoff_raw"] = c.onoff
        c["x_prod_raw"] = c["prod"]
        out.append(c[["fixture_id", "team", "x_onoff", "x_prod", "x_onoff_raw", "x_prod_raw", "onoff", "prod"]])
    F = pd.concat(out, ignore_index=True)
    return F
