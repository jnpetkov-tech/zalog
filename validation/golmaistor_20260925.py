"""
validation/golmaistor_20260925.py - ZADACHA_TEGLENE.md т.3 (25.09.2026).
Тест с голмайстора: носи ли съставът информация, която СЕГАШНИЯТ модел не знае?

Мачове: мерилото на Етап 4 (validation/sila_igrach_20260924_matches.csv - 6400 мача,
10 лиги, последните 730 дни, walk-forward; lam_сега/mu_сега = очакваните голове на
сегашния модел, смятани само от мачове преди седмицата).
Играчи: {лига}_player_stats.csv на 10-те лиги (един отбор = едно име и в първенството,
и в евротурнирите - историята му е обща).

ОПРЕДЕЛЕНИЯ (записани и групите - в git - ПРЕДИ да се гледат головете; етап "grupi"):
- "Играл в мача" = минути > 0 в протокола на мача (резерва без минути = не е играл).
- Кандидати на отбора за мач M: играчите, играли за отбора в някой от последните
  10 мача на отбора преди M (всички състезания с данни).
- История за оценката: мачовете на отбора в последните 365 дни преди датата на M
  (строго преди - само от мачовете ПРЕДИ).
- Атака: (голове + асистенции) на 90 мин, свити към средното: (GA + K*p) / (мин/90 + K),
  K = 5 мача по 90 мин, p = средното на всички играчи от всички мачове преди датата.
  Тримата с най-висока свита стойност = "най-полезните в атака".
- Отбрана: вратарят (пост G) с най-много минути и двамата защитници (пост D) с
  най-много минути в историята от 365 дни (сред кандидатите).
- Отсъстващи = колко от тримата НЕ са играли в мача M. Групи: 0, 1, 2+.
- Вън от теста: отбор-мач без протокол за самия мач, или с по-малко от 5 предишни
  мача на отбора с протокол (няма смислена история).

ИЗМЕРВАНЕ (етап "rezultati"): за всяка група - реални голове на отбора срещу
очакваните (атака: вкараните vs lam/mu на отбора; отбрана: допуснатите vs очакваните
за противника). Средна разлика (реални - очаквани) на мач с 95% интервал (нормално
приближение, sd от данните), отношение реални/очаквани, и разликата група - група 0
с 95% интервал.

Употреба: venv/bin/python3 validation/golmaistor_20260925.py grupi|rezultati
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal",
           "champions_league", "europa_league", "conference_league"]
MATCHES = "validation/sila_igrach_20260924_matches.csv"
GRUPI = "validation/golmaistor_20260925_grupi.csv"
OUT_CSV = "validation/golmaistor_20260925.csv"
K = 5.0
LAST_N = 10
HIST_DAYS = 365
MIN_PRIOR = 5


def load_players():
    pms, fx = [], []
    for lg in LEAGUES:
        p = pd.read_csv(f"{lg}_player_stats.csv")
        m = pd.read_csv(f"{lg}_merged_full.csv", usecols=["fixture_id", "date"])
        m["date"] = pd.to_datetime(m["date"].astype(str).str[:10])
        p = p.merge(m.drop_duplicates("fixture_id"), on="fixture_id", how="inner")
        pms.append(p)
    PM = pd.concat(pms, ignore_index=True).drop_duplicates(subset=["fixture_id", "player_id"])
    PM["minutes"] = PM["minutes"].fillna(0).clip(lower=0)
    PM["ga"] = PM["goals"].fillna(0) + PM["assists"].fillna(0)
    PM = PM[PM.minutes > 0].copy()
    return PM.sort_values("date")


def grupi():
    M = pd.read_csv(MATCHES)
    M["date"] = pd.to_datetime(M["date"])
    home = M[["league", "fixture_id", "date"]].copy()
    names = {}
    for lg in LEAGUES:
        m = pd.read_csv(f"{lg}_merged_full.csv", usecols=["fixture_id", "home_team", "away_team"])
        names.update({int(f): (h, a) for f, h, a in zip(m.fixture_id, m.home_team, m.away_team)})
    PM = load_players()
    # общото средно GA на 90 до дата (кумулативно, само минали мачове)
    daily = PM.groupby("date")[["ga", "minutes"]].sum().sort_index()
    cum = daily.cumsum()
    cum_dates = cum.index.values

    def prior_rate(d):
        i = np.searchsorted(cum_dates, np.datetime64(d), side="left") - 1
        if i < 0:
            return np.nan
        return cum["ga"].iloc[i] / (cum["minutes"].iloc[i] / 90.0)

    by_team = {t: g for t, g in PM.groupby("team")}
    played = PM.groupby(["fixture_id", "team"])["player_id"].apply(set).to_dict()
    rows = []
    for lg, f, d in zip(home.league, home.fixture_id, home.date):
        h, a = names[int(f)]
        for side, team in (("home", h), ("away", a)):
            base = {"league": lg, "fixture_id": int(f), "date": d.date().isoformat(), "side": side, "team": team}
            now = played.get((int(f), team))
            g = by_team.get(team)
            if now is None or g is None:
                rows.append({**base, "status": "няма протокол"})
                continue
            prev = g[g.date < d]
            prev_fx = prev.drop_duplicates("fixture_id")[["fixture_id", "date"]]
            if len(prev_fx) < MIN_PRIOR:
                rows.append({**base, "status": "малко история"})
                continue
            last = set(prev_fx.fixture_id.iloc[-LAST_N:])
            cand = set(prev[prev.fixture_id.isin(last)].player_id)
            hist = prev[(prev.date >= d - pd.Timedelta(days=HIST_DAYS)) & prev.player_id.isin(cand)]
            agg = hist.groupby("player_id").agg(ga=("ga", "sum"), mins=("minutes", "sum"),
                                                pos=("position", "last"), name=("player_name", "last"))
            p = prior_rate(d)
            agg["att"] = (agg.ga + K * p) / (agg.mins / 90.0 + K)
            att = agg.sort_values(["att", "mins"], ascending=False).head(3)
            gk = agg[agg.pos == "G"].sort_values("mins", ascending=False).head(1)
            df = agg[agg.pos == "D"].sort_values("mins", ascending=False).head(2)
            dfn = pd.concat([gk, df])
            rows.append({**base, "status": "ok",
                         "att_abs": int(sum(pid not in now for pid in att.index)),
                         "def_abs": int(sum(pid not in now for pid in dfn.index)),
                         "def_n": len(dfn),
                         "att_players": "; ".join(att.name.astype(str)),
                         "def_players": "; ".join(dfn.name.astype(str))})
    G = pd.DataFrame(rows)
    G.to_csv(GRUPI, index=False)
    ok = G[G.status == "ok"]
    print(G.status.value_counts().to_dict())
    print("атака:", ok.att_abs.clip(upper=2).value_counts().sort_index().to_dict())
    print("отбрана:", ok.def_abs.clip(upper=2).value_counts().sort_index().to_dict(),
          "непълни (под 3 души):", int((ok.def_n < 3).sum()))


def ci_mean(x):
    x = np.asarray(x, float)
    m = x.mean()
    se = x.std(ddof=1) / np.sqrt(len(x))
    return m, m - 1.96 * se, m + 1.96 * se, se


def rezultati():
    G = pd.read_csv(GRUPI)
    G = G[G.status == "ok"].copy()
    M = pd.read_csv(MATCHES)
    G = G.merge(M[["fixture_id", "hg", "ag", "lam_сега", "mu_сега"]], on="fixture_id")
    home = G.side == "home"
    G["gf"] = np.where(home, G.hg, G.ag)
    G["ga_"] = np.where(home, G.ag, G.hg)
    G["xf"] = np.where(home, G["lam_сега"], G["mu_сега"])
    G["xa"] = np.where(home, G["mu_сега"], G["lam_сега"])
    G["r_att"] = G.gf - G.xf
    G["r_def"] = G.ga_ - G.xa
    out = []
    for kind, col, r, real, exp in (("атака", "att_abs", "r_att", "gf", "xf"),
                                    ("отбрана", "def_abs", "r_def", "ga_", "xa")):
        grp = G[col].clip(upper=2)
        base = G[grp == 0][r]
        for k in (0, 1, 2):
            s = G[grp == k]
            m, lo, hi, se = ci_mean(s[r])
            if k == 0:
                dm = dlo = dhi = np.nan
            else:
                _, _, _, se0 = ci_mean(base)
                dm = m - base.mean()
                dse = np.sqrt(se ** 2 + se0 ** 2)
                dlo, dhi = dm - 1.96 * dse, dm + 1.96 * dse
            out.append({"вид": kind, "група": ["0", "1", "2+"][k], "мачове": len(s),
                        "реални_ср": s[real].mean(), "очаквани_ср": s[exp].mean(),
                        "разлика_ср": m, "разлика_2.5": lo, "разлика_97.5": hi,
                        "реални/очаквани": s[real].sum() / s[exp].sum(),
                        "спрямо_0": dm, "спрямо_0_2.5": dlo, "спрямо_0_97.5": dhi})
    R = pd.DataFrame(out)
    R.to_csv(OUT_CSV, index=False, float_format="%.4f")
    pd.set_option("display.width", 200)
    print(R.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    # по лига - само атака, разлика 2+ и 1 спрямо 0 (за доклада)
    rows = []
    for lg, s in G.groupby("league"):
        for kind, col, r in (("атака", "att_abs", "r_att"), ("отбрана", "def_abs", "r_def")):
            grp = s[col].clip(upper=2)
            rows.append({"лига": lg, "вид": kind,
                         "n0": int((grp == 0).sum()), "n1": int((grp == 1).sum()), "n2+": int((grp == 2).sum()),
                         "r0": s[grp == 0][r].mean(), "r1": s[grp == 1][r].mean(), "r2+": s[grp == 2][r].mean()})
    L = pd.DataFrame(rows)
    L.to_csv(OUT_CSV.replace(".csv", "_leagues.csv"), index=False, float_format="%.4f")
    print(L.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    # разрез (добавен след първите резултати - проверка за устойчивост, не нова хипотеза):
    # 2+ срещу 0 по половини на мерилото (граница 2025-09-23, както в Етап 4) и първенства/турнири
    G["половина"] = np.where(G.date < "2025-09-23", "ранна", "късна")
    G["вид_лига"] = np.where(G.league.str.contains("league"), "евротурнири", "първенства")
    rows = []
    for by in ("половина", "вид_лига"):
        for key, s in G.groupby(by):
            for kind, col, r in (("атака", "att_abs", "r_att"), ("отбрана", "def_abs", "r_def")):
                grp = s[col].clip(upper=2)
                a, b = s[grp == 0][r], s[grp == 2][r]
                d = b.mean() - a.mean()
                se = np.sqrt(a.var() / len(a) + b.var() / len(b))
                rows.append({"разрез": key, "вид": kind, "n0": len(a), "n2+": len(b),
                             "2+_минус_0": d, "2.5": d - 1.96 * se, "97.5": d + 1.96 * se})
    Z = pd.DataFrame(rows)
    Z.to_csv(OUT_CSV.replace(".csv", "_razrez.csv"), index=False, float_format="%.4f")
    print(Z.to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    {"grupi": grupi, "rezultati": rezultati}[sys.argv[1]]()
