"""features/core_lam_mu_hist.py - ядрото, удължено НАЗАД (ZADACHA_RAZVITIE т.3, 02.10.2026).

Същото като features/core_lam_mu.py (validation/final_b_20260924.run - walk-forward, седмично префитване само от мачове преди
понеделника), но:
  - към живите {лига}_merged_full.csv се добавят мачовете от hist/ (сезони 2019-2021, fetch_history.py) - в паметта, нищо на диска
    не се пипа; редовете се сглобяват в същия формат като incremental_refresh.py (само статус FT, голове = goals, полувреме,
    статистика от /fixtures?ids=, контузии = брой записи в /injuries за мача и отбора, като fetch_fixture_injuries);
  - данните се режат преди HIST_END (така тестовите мачове са само < HIST_END - за тях резултатът е същият, все едно данните
    продължават, защото всяко фитване вижда само миналото);
  - тестовият прозорец е HIST_START..HIST_END. От HIST_END нататък lam/mu остават сегашните (features/core_lam_mu.csv).
  - общият евро модел вижда вътрешните първенства от 2019-07-01 (живият: от 2022-01-01 = от началото на тогавашните данни).
Изход: features/core_lam_mu_hist.csv (същите колони). Настройки: validation/istoriya_nastroyki_20261002.md.
Употреба: nice -n 19 venv/bin/python3 features/core_lam_mu_hist.py [--procs 8]
"""
import os
import sys

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
from multiprocessing import Pool  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

HIST_DIR = os.path.join(ROOT, "hist")
HIST_START = pd.Timestamp("2020-08-01")
HIST_END = pd.Timestamp("2023-08-01")        # = START в core_lam_mu.py
EURO_HIST_FROM = pd.Timestamp("2019-07-01")
OUT = os.path.join(ROOT, "features", "core_lam_mu_hist.csv")

# колона в {лига}_stats_full.csv -> суфикс в merged_full
STAT_MAP = {"Corner_Kicks": "corners", "Yellow_Cards": "yellow", "Red_Cards": "red", "Total_Shots": "shots",
            "Shots_on_Goal": "shots_on_goal", "Shots_insidebox": "shots_insidebox", "Ball_Possession": "possession",
            "Fouls": "fouls", "Offsides": "offsides", "Goalkeeper_Saves": "saves", "Total_passes": "passes",
            "Passes_accurate": "passes_accurate", "expected_goals": "xg"}


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace("%", "", regex=False), errors="coerce")


def hist_merged(league):
    """Мачовете от hist/ във формата на {лига}_merged_full.csv (без пипане на диска)."""
    fp = os.path.join(HIST_DIR, f"{league}_fixtures.csv")
    if not os.path.exists(fp):
        return pd.DataFrame()
    fx = pd.read_csv(fp, low_memory=False).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["status"] == "FT"].copy()
    out = pd.DataFrame({"fixture_id": fx["fixture_id"].astype(int), "season": fx["season"].astype(int),
                        "date": fx["date_utc"].astype(str).str[:10], "home_team": fx["home"], "away_team": fx["away"],
                        "home_goals": pd.to_numeric(fx["home_goals"], errors="coerce"),
                        "away_goals": pd.to_numeric(fx["away_goals"], errors="coerce"),
                        "home_ht_goals": pd.to_numeric(fx["ht_home"], errors="coerce"),
                        "away_ht_goals": pd.to_numeric(fx["ht_away"], errors="coerce")})
    home_id = dict(zip(fx["fixture_id"].astype(int), fx["home_id"].astype(int)))
    sp = os.path.join(HIST_DIR, f"{league}_stats_full.csv")
    if os.path.exists(sp) and os.path.getsize(sp) > 0:
        st = pd.read_csv(sp, low_memory=False).drop_duplicates(["fixture_id", "team_id"])
        st = st[st["fixture_id"].isin(home_id)]
        st["side"] = np.where(st["team_id"].astype(int) == st["fixture_id"].map(home_id), "home", "away")
        for col, suf in STAT_MAP.items():
            if col in st.columns:
                v = st.assign(v=_num(st[col])).pivot_table(index="fixture_id", columns="side", values="v", aggfunc="first")
                for side in ("home", "away"):
                    if side in v.columns:
                        out[f"{side}_{suf}"] = out["fixture_id"].map(v[side])
    ip = os.path.join(HIST_DIR, f"{league}_injuries.csv")
    if os.path.exists(ip) and os.path.getsize(ip) > 0:
        inj = pd.read_csv(ip, low_memory=False).drop(columns=["fetched_at"], errors="ignore").drop_duplicates()
        inj = inj[inj["fixture_id"].isin(home_id)]
        inj["side"] = np.where(inj["team_id"].astype(int) == inj["fixture_id"].map(home_id), "home", "away")
        cnt = inj.groupby(["fixture_id", "side"]).size().unstack(fill_value=0)
        covered = set(inj["season"].astype(int))
        for side in ("home", "away"):
            c = out["fixture_id"].map(cnt[side]) if side in cnt.columns else pd.Series(np.nan, index=out.index)
            # мач без записи в лига-сезон с покритие = 0 контузени; без покритие = NaN (ядрото го брои като 0, като живото)
            out[f"{side}_injuries"] = np.where(out["season"].isin(covered), c.fillna(0.0), np.nan)
    return out


def patched_loader(orig):
    def load(league):
        live = orig(league)
        h = hist_merged(league)
        if len(h):
            h = h[~h["fixture_id"].isin(set(live["fixture_id"].astype(int)))]
            h["date"] = pd.to_datetime(h["date"])
            df = pd.concat([h, live], ignore_index=True, sort=False)
        else:
            df = live
        df = df[df["date"] < HIST_END]
        return df.sort_values("date").reset_index(drop=True)
    return load


def job(league):
    import backtest_full as bf
    import final_b_20260924 as fb
    import football_lib as fl
    import tri_v_euro as E
    fl.load_league_data = patched_loader(fl.load_league_data)
    E.HIST_FROM = EURO_HIST_FROM
    df = fl.load_league_data(league)
    fin = df.dropna(subset=["home_goals", "away_goals"])
    bf.PERIOD_DAYS = int((fin["date"].max() - HIST_START).days)
    t, _ = fb.run((league, 1.0))
    t = t.drop(columns=["xi_mult", "week"])
    return t[(pd.to_datetime(t["date"]) >= HIST_START) & (pd.to_datetime(t["date"]) < HIST_END)]


def main():
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 8
    import backtest_full as bf
    with Pool(procs) as pool:
        parts = pool.map(job, list(bf.LEAGUES), chunksize=1)
    core = pd.concat(parts, ignore_index=True)
    core.to_csv(OUT, index=False)
    print(len(core), "мача ->", OUT)


if __name__ == "__main__":
    main()
