"""validation/novi_ligi_20261009.py - етап 2 (ZADACHA_VSICHKO_OT_API): купи и нови първенства - бие ли ядрото отправната точка?

1. novi/{ключ}_merged_full.csv от novi/{ключ}_fixtures.csv + _stats_full.csv (същите колони като клубните merged_full; 90-минутният
   резултат). Само в novi/ - живият код и web/admin (glob в корена) не ги виждат.
2. Ядрото: validation/final_b_20260924.run_domestic - ТОЧНО живото ядро (Dixon-Coles, свито темпо, без контузии/xG за нови лиги -
   настройките по подразбиране), walk-forward с префитване всяка седмица само от мачове преди понеделника; последните 730 дни.
   Купите - същото, само с мачовете на купата (смесени нива на отборите - отчита се отделно).
3. Отправна точка: честотите на 11-те изхода в същото състезание за мачовете ПРЕДИ седмицата (последните 365 дни; минимум 50 мача).
4. Мерки: Brier (11 изхода, като мерилото) ядро − отправна точка, 95% интервал (bootstrap по мач, 2000, seed 42); калибрация a по група.
   За сравнение - същото за 17-те живи лиги от features/core_lam_mu.csv (същото ядро, същата дефиниция).
Изход: validation/novi_ligi_20261009.md, validation/novi_ligi_20261009.csv (по състезание), validation/novi_ligi_20261009_matches.csv.
Употреба: nice -n 19 venv/bin/python3 validation/novi_ligi_20261009.py [--procs 12]
"""
import os
import sys
from multiprocessing import Pool

os.environ["OMP_NUM_THREADS"] = "1"
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = "/home/inkas/sportbg-predictor"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

KEYS = ["netherlands", "netherlands2", "turkey", "turkey2", "belgium", "belgium2", "scotland", "greece", "romania",
        "cup_bulgaria", "cup_fa", "cup_league", "cup_copa_del_rey", "cup_dfb", "cup_coppa_italia", "cup_coupe_de_france", "cup_taca_portugal"]
NAMES = {"netherlands": "Холандия 1", "netherlands2": "Холандия 2", "turkey": "Турция 1", "turkey2": "Турция 2", "belgium": "Белгия 1",
         "belgium2": "Белгия 2", "scotland": "Шотландия 1", "greece": "Гърция 1", "romania": "Румъния 1", "cup_bulgaria": "Купа на България",
         "cup_fa": "FA Cup", "cup_league": "League Cup (Англия)", "cup_copa_del_rey": "Copa del Rey", "cup_dfb": "DFB Pokal",
         "cup_coppa_italia": "Coppa Italia", "cup_coupe_de_france": "Coupe de France", "cup_taca_portugal": "Taça de Portugal"}
BASE_DAYS, BASE_MIN = 365, 50
TAG = "20261009"
STAT_MAP = {"corners": "Corner_Kicks", "yellow": "Yellow_Cards", "red": "Red_Cards", "offsides": "Offsides", "possession": "Ball_Possession",
            "shots": "Total_Shots", "shots_on_goal": "Shots_on_Goal", "fouls": "Fouls", "xg": "expected_goals"}


def build_merged(key):
    fx = pd.read_csv(f"novi/{key}_fixtures.csv", low_memory=False).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["status"].isin(["FT", "AET", "PEN"])].copy()
    hg = pd.to_numeric(fx["ft_home"], errors="coerce")
    ag = pd.to_numeric(fx["ft_away"], errors="coerce")
    fx["home_goals"] = hg.where(hg.notna(), pd.to_numeric(fx["home_goals"], errors="coerce"))
    fx["away_goals"] = ag.where(ag.notna(), pd.to_numeric(fx["away_goals"], errors="coerce"))
    out = pd.DataFrame({"fixture_id": fx["fixture_id"], "season": fx["season"], "date": fx["date_utc"].str[:10],
                        "home_team": fx["home"], "away_team": fx["away"], "home_goals": fx["home_goals"], "away_goals": fx["away_goals"],
                        "home_ht_goals": fx["ht_home"], "away_ht_goals": fx["ht_away"], "_h": fx["home_id"], "_a": fx["away_id"]})
    sp = f"novi/{key}_stats_full.csv"
    if os.path.exists(sp) and os.path.getsize(sp):
        st = pd.read_csv(sp, low_memory=False).drop_duplicates(["fixture_id", "team_id"])
        for c in STAT_MAP.values():
            st[c] = pd.to_numeric(st[c].astype(str).str.replace("%", ""), errors="coerce")
        st = st.set_index(["fixture_id", "team_id"])
        for side, col in (("home", "_h"), ("away", "_a")):
            idx = list(zip(out["fixture_id"], out[col]))
            sub = st.reindex(idx)
            for name, c in STAT_MAP.items():
                out[f"{side}_{name}"] = sub[c].to_numpy()
    out = out.dropna(subset=["home_goals", "away_goals"]).drop(columns=["_h", "_a"]).sort_values("date")
    out.to_csv(f"novi/{key}_merged_full.csv", index=False)
    return len(out)


def run_core(key):
    import backtest_full as bf
    import final_b_20260924 as fb
    bf.PERIOD_DAYS = 730
    t, _ = fb.run_domestic(f"novi/{key}")
    t["league"] = key
    return t


def base_probs(t, hist_by_key):
    """Отправна точка: за всеки мач - честотите на изходите в същото състезание през последните 365 дни преди седмицата."""
    import backtest_full as bf
    rows = []
    for key, g in t.groupby("league"):
        h = hist_by_key[key]
        for week, blk in g.groupby("week"):
            past = h[(h["date"] < week) & (h["date"] >= week - pd.Timedelta(days=BASE_DAYS))]
            if len(past) < BASE_MIN:
                continue
            y = y_matrix(past["home_goals"].to_numpy(), past["away_goals"].to_numpy()).mean(0)
            for i in blk.index:
                rows.append((i, *y))
    df = pd.DataFrame(rows, columns=["i"] + list(bf.CODES)).set_index("i")
    return df


def y_matrix(hg, ag):
    from features import layer_lib as L
    return L.y_matrix(hg, ag)


def measure(t, P, B):
    from features import layer_lib as L
    keep = B.index
    t2 = t.loc[keep]
    Y = L.y_matrix(t2["hg"].to_numpy(), t2["ag"].to_numpy())
    P2 = P.loc[keep]
    bm = L.brier_match(P2, Y)
    bb = L.brier_match(B[P2.columns], Y)
    d = L.boot_ci(bm - bb)
    a = L.calib_coef(P2.reset_index(drop=True), Y, {c: B[c].mean() for c in P2.columns})
    return len(t2), float(bm.mean()), float(bb.mean()), d, a


def main():
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 12
    from features import layer_lib as L
    sizes = {k: build_merged(k) for k in KEYS}
    with Pool(procs) as pool:
        parts = pool.map(run_core, KEYS, chunksize=1)
    t = pd.concat(parts, ignore_index=True)
    t["week"] = pd.to_datetime(t["week"])
    hist = {k: pd.read_csv(f"novi/{k}_merged_full.csv", parse_dates=["date"]) for k in KEYS}
    P = L.probs(t["lam"], t["mu"], t["rho"])
    P.index = t.index
    B = base_probs(t, hist)
    t.join(P).to_csv(f"validation/novi_ligi_{TAG}_matches.csv", index=False)
    # 17-те живи лиги - същото ядро (features/core_lam_mu.csv), последните 730 дни
    core = pd.read_csv("features/core_lam_mu.csv", parse_dates=["date"])
    core = core[core["date"] >= core["date"].max() - pd.Timedelta(days=730)].reset_index(drop=True)
    core["week"] = core["date"] - pd.to_timedelta(core["date"].dt.weekday, unit="D")
    Pc = L.probs(core["lam"], core["mu"], core["rho"])
    Pc.index = core.index
    allc = pd.read_csv("features/core_lam_mu.csv", parse_dates=["date"]).rename(columns={"hg": "home_goals", "ag": "away_goals"})
    Bc = base_probs(core, {k: g for k, g in allc.groupby("league")})
    rows = []
    for key, g in list(t.groupby("league")) + [("__" + k, g) for k, g in core.groupby("league")]:
        live = key.startswith("__")
        k = key[2:] if live else key
        PP, BB = (Pc, Bc) if live else (P, B)
        BBk = BB[BB.index.isin(g.index)]
        if len(BBk) < 30:
            rows.append({"key": k, "live": live, "n": len(BBk)})
            continue
        n, bm, bb, d, a = measure(g, PP.loc[g.index], BBk)
        rows.append({"key": k, "live": live, "n": n, "brier_core": bm, "brier_base": bb, "d": d[0], "lo": d[1], "hi": d[2],
                     **{f"a_{x}": a[x] for x in L.GROUPS}})
    res = pd.DataFrame(rows)
    res.to_csv(f"validation/novi_ligi_{TAG}.csv", index=False)
    write_md(res, sizes)


def write_md(res, sizes):
    def verdict(r):
        if pd.isna(r.get("d")):
            return "малко мачове"
        if r["hi"] < 0:
            return "🟢 бие отправната точка"
        if r["lo"] > 0:
            return "🔴 по-лошо от отправната точка"
        return "🟡 в шума"
    L_ = [f"# Купи и нови първенства — бие ли ядрото отправната точка — 09.10.2026", "",
          "ZADACHA_VSICHKO_OT_API, етап 2. Скрипт: `validation/novi_ligi_20261009.py`. Данни: `novi/` (`fetch_novi.py`, 2022–2026; ID-та от `/leagues`).",
          "", "**Метод.** Живото ядро (Dixon-Coles, свито темпо; за новите — настройките по подразбиране, без контузии/xG), walk-forward с "
          "префитване всяка седмица само от мачове преди понеделника, последните 730 дни. Отправна точка: честотите на 11-те изхода в "
          "същото състезание през 365-те дни преди седмицата (≥ 50 мача). Brier — средно по 11-те изхода (като мерилото); разлика "
          "ядро − отправна точка с 95% интервал (bootstrap по мач). Калибрация a: 1 = точно, < 1 прекалено уверен. "
          "Същото за 17-те живи лиги — за сравнение (каква разлика е „нормална“).", "",
          "Слоят (LightGBM) за новите НЕ е мерен тук: признаците му изискват `features/build_features.py` с новите лиги в общата история "
          "— отделна стъпка, ако Дака реши някоя да влезе (виж бележката по-долу).", ""]
    for title, cond in (("Нови първенства", lambda k: not k.startswith("cup_")), ("Купи (смесени нива на отборите — ядрото знае само мачовете в купата)", lambda k: k.startswith("cup_"))):
        L_ += [f"## {title}", "", "| състезание | мачове в историята | тествани | Brier ядро | Brier отправна | разлика [95%] | калибрация 1X2 / над-под / двата / отборни | присъда |",
               "|---|---|---|---|---|---|---|---|"]
        for r in res[(~res["live"]) & res["key"].map(cond)].to_dict("records"):
            if pd.isna(r.get("d")):
                L_.append(f"| {NAMES[r['key']]} | {sizes.get(r['key'], 0)} | {r['n']} | — | — | — | — | малко мачове |")
                continue
            L_.append(f"| {NAMES[r['key']]} | {sizes.get(r['key'], 0)} | {r['n']} | {r['brier_core']:.4f} | {r['brier_base']:.4f} | "
                      f"{r['d']:+.4f} [{r['lo']:+.4f}; {r['hi']:+.4f}] | {r['a_1x2']:.2f} / {r['a_ou25']:.2f} / {r['a_btts']:.2f} / {r['a_team_total']:.2f} | {verdict(r)} |")
        L_.append("")
    L_ += ["## За сравнение — 17-те живи лиги (същото ядро, същата мярка)", "",
           "| лига | тествани | Brier ядро | Brier отправна | разлика [95%] | калибрация 1X2 / над-под / двата / отборни |", "|---|---|---|---|---|---|"]
    for r in res[res["live"]].to_dict("records"):
        if pd.isna(r.get("d")):
            continue
        L_.append(f"| {r['key']} | {r['n']} | {r['brier_core']:.4f} | {r['brier_base']:.4f} | {r['d']:+.4f} [{r['lo']:+.4f}; {r['hi']:+.4f}] | "
                  f"{r['a_1x2']:.2f} / {r['a_ou25']:.2f} / {r['a_btts']:.2f} / {r['a_team_total']:.2f} |")
    L_ += ["", "## Какво следва (решение на Дака)",
           "- Влизане в `ALL_LEAGUES` = решение на Дака + рестарт от него. Преди това: доверието започва НЕПРОВЕРЕНО (показва се, не се препоръчва).",
           "- За слоя: новите лиги трябва да влязат в `features/build_features.py` (обща история на отборите) и слоят да се мери наново.",
           "- Купите: при смесени нива ядрото на една купа почти не познава отборите от по-ниските дивизии — разумният път е общ модел "
           "(като евромодела), не отделна купа."]
    open(f"validation/novi_ligi_{TAG}.md", "w", encoding="utf-8").write("\n".join(L_) + "\n")
    print("\n".join(L_))


if __name__ == "__main__":
    main()
