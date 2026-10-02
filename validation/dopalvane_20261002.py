"""validation/dopalvane_20261002.py - ZADACHA_DOPALVANE т.2.3 (02.10.2026): мерилото преди/след попълването на дупките.

Попълнени файлове (archive/dopalvane_build_20261002.py): bulgaria (+636 изиграни мача 2020-2025), france (-1: плейоф на
Лига 2, сложен по грешка там), france2 (+1: същият мач). Старите копия: data_backups/20261002_dopalvane/old/, новите:
data_backups/20261002_dopalvane/new/ (извън git - *.csv).

МЕТОД = мерилото на живия модел (final_v_20260924: повторната сметка final_b_20260924.run() - последните 730 дни на
лигата, седмично префитване само от мачове преди понеделника; свито темпо, контузии, xG смес, общ евро модел; матрица
Dixon-Coles + зависимостта; живата калибрация prediction_policy.calibrate). Пуска се два пъти - fl.load_league_data
чете трите файла от old/ или от new/ (останалите 14 - живите, еднакви и в двата пуска).
Засегнати модели: bulgaria, france, france2 и трите евротурнира (общият евро модел учи и от вътрешните първенства).

СРАВНЕНИЕ - на ЕДНИ И СЪЩИ мачове: тестовите мачове от пуска "преди" (новите мачове в bulgaria не са тест "преди").
- Brier (11-те изхода на мерилото, показваното число) по лига: преди, след, разлика след - преди, 95% интервал
  (bootstrap по мач, 2000, seed 42). "Значимо по-лошо" = интервалът е изцяло над 0.
- Калибрация a по пазарна група (calibration_fit метод, b = честотата на ранната половина < 2025-09-23) на
  показваното число: на късната половина и на всички общи мачове, преди и след. Рамка 0.9-1.1.
- Справка: bulgaria "след" и на всичките си тестови мачове (с новите).
Изход: validation/dopalvane_20261002.md, _leagues.csv, _calib.csv, _matches.csv.
Употреба: nice -n 10 venv/bin/python3 validation/dopalvane_20261002.py
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

import backtest_full as bf  # noqa: E402
import final_v_20260924 as fv  # noqa: E402
import kalibraciq_xg_20260923 as kx  # noqa: E402

TAG = "20261002"
BK = "data_backups/20261002_dopalvane"
FILES = ["bulgaria", "france", "france2"]
LEAGUES = ["bulgaria", "france", "france2", "champions_league", "europa_league", "conference_league"]
GROUPS4 = ["1x2", "ou25", "btts", "team_total"]


def job(args):
    league, which = args
    import final_b_20260924 as fb
    import football_lib as fl
    orig = fl.load_league_data

    def load(name):
        if name.lower() in FILES:
            df = pd.read_csv(os.path.join(BK, which, f"{name.lower()}_merged_full.csv"))
            df["date"] = pd.to_datetime(df["date"].astype(str).str[:10])
            return df.sort_values("date").reset_index(drop=True)
        return orig(name)
    fl.load_league_data = load
    t, _ = fb.run((league, 1.0))
    return which, t.drop(columns=["xi_mult"])


def probs(t):
    P = fv.goal_probs(t.lam.to_numpy(), t.mu.to_numpy(), t.rho.to_numpy())[bf.CODES]
    Y = fv.goal_outcomes(t.hg.to_numpy(), t.ag.to_numpy())[bf.CODES]
    return fv.live_calibrate(P).reset_index(drop=True), Y.reset_index(drop=True)


def brier_rows(P, Y):
    return ((P.to_numpy() - Y.to_numpy()) ** 2).mean(1)


def calib(P, Y, early, mask):
    out = {}
    for g in GROUPS4:
        codes = [c for c in bf.CODES if bf.GROUPS[c] == g]
        out[g] = fv.calib_a(P, Y, early, mask, codes)
    return out


def calib_diff_ci(Po, Yo, Pn, Yn, early, mask, fx, B=1000):
    """95% интервал за a_след - a_преди (bootstrap по мач, seed 42; b - от ранната половина, както calib_a)."""
    idx_all = np.flatnonzero(mask)
    ufx, inv = np.unique(fx[idx_all], return_inverse=True)
    rng = np.random.default_rng(42)
    out = {}
    for g in GROUPS4:
        codes = [c for c in bf.CODES if bf.GROUPS[c] == g]
        parts = []
        for P, Y in ((Po, Yo), (Pn, Yn)):
            num = np.zeros(len(ufx))
            den = np.zeros(len(ufx))
            for c in codes:
                b = Y.loc[early, c].mean()
                d = P[c].to_numpy()[idx_all] - b
                np.add.at(num, inv, d * (Y[c].to_numpy()[idx_all] - b))
                np.add.at(den, inv, d * d)
            parts.append((num, den))
        draws = rng.integers(0, len(ufx), size=(B, len(ufx)))
        a_o = parts[0][0][draws].sum(1) / parts[0][1][draws].sum(1)
        a_n = parts[1][0][draws].sum(1) / parts[1][1][draws].sum(1)
        out[g] = (float(np.percentile(a_n - a_o, 2.5)), float(np.percentile(a_n - a_o, 97.5)))
    return out


def main():
    jobs = [(lg, w) for w in ("old", "new") for lg in LEAGUES]
    jobs.sort(key=lambda j: j[0] not in fv.fb.S["EURO_FIT_SETTINGS"])
    with Pool(min(12, len(jobs)), maxtasksperchild=1) as pool:
        res = pool.map(job, jobs, chunksize=1)
    T = {w: pd.concat([t for ww, t in res if ww == w], ignore_index=True) for w in ("old", "new")}
    key = ["league", "fixture_id"]
    common = T["old"][key + ["date", "hg", "ag"]].merge(T["new"][key], on=key)
    o = common.merge(T["old"], on=key + ["date", "hg", "ag"], how="left").sort_values(key).reset_index(drop=True)
    n = common.merge(T["new"], on=key + ["date", "hg", "ag"], how="left").sort_values(key).reset_index(drop=True)
    assert len(o) == len(n) == len(common) and (o.fixture_id.to_numpy() == n.fixture_id.to_numpy()).all()
    Po, Yo = probs(o)
    Pn, Yn = probs(n)
    bo, bn = brier_rows(Po, Yo), brier_rows(Pn, Yn)
    early = (pd.to_datetime(o.date) < kx.CUT).to_numpy()
    rows, cal = [], []
    for lg in LEAGUES + ["ALL"]:
        sel = np.ones(len(o), bool) if lg == "ALL" else (o.league == lg).to_numpy()
        d, lo, hi = fv.boot_ci(bn[sel] - bo[sel], o.fixture_id.to_numpy()[sel])
        rec = {"league": lg, "n_common": int(sel.sum()), "n_old_test": int((T["old"].league == lg).sum()) if lg != "ALL" else len(T["old"]),
               "n_new_test": int((T["new"].league == lg).sum()) if lg != "ALL" else len(T["new"]),
               "brier_old": float(bo[sel].mean()), "brier_new": float(bn[sel].mean()), "diff": d, "ci_lo": lo, "ci_hi": hi,
               "lam_mean_abs_change": float(np.abs(n.lam.to_numpy()[sel] - o.lam.to_numpy()[sel]).mean()),
               "mu_mean_abs_change": float(np.abs(n.mu.to_numpy()[sel] - o.mu.to_numpy()[sel]).mean())}
        rec["verdict"] = ("значимо по-лошо" if lo > 0 else "значимо по-добро" if hi < 0 else
                          "без промяна" if d == 0 and lo == 0 and hi == 0 else "в шума")
        rows.append(rec)
        late = sel & ~early
        for scope, mask in (("късна", late), ("всички", sel)):
            if mask.sum() < 30:
                continue
            ca_o, ca_n = calib(Po, Yo, early & sel if (early & sel).sum() >= 30 else early, mask), \
                calib(Pn, Yn, early & sel if (early & sel).sum() >= 30 else early, mask)
            e_ref = early & sel if (early & sel).sum() >= 30 else early
            ci = calib_diff_ci(Po, Yo, Pn, Yn, e_ref, mask, o.fixture_id.to_numpy())
            for g in GROUPS4:
                cal.append({"league": lg, "scope": scope, "n": int(mask.sum()), "group": g, "a_old": ca_o[g], "a_new": ca_n[g],
                            "d_lo": ci[g][0], "d_hi": ci[g][1]})
    lgs, cal = pd.DataFrame(rows), pd.DataFrame(cal)
    # справка: bulgaria след - всички тестови мачове (с новите)
    bn_all = T["new"][T["new"].league == "bulgaria"].reset_index(drop=True)
    Pa, Ya = probs(bn_all)
    is_new = ~bn_all.fixture_id.isin(T["old"][T["old"].league == "bulgaria"].fixture_id).to_numpy()
    ref = {"n_all": len(bn_all), "brier_all": float(brier_rows(Pa, Ya).mean()), "n_added": int(is_new.sum()),
           "brier_added": float(brier_rows(Pa, Ya)[is_new].mean()) if is_new.any() else float("nan")}
    lgs.round(6).to_csv(f"validation/dopalvane_{TAG}_leagues.csv", index=False)
    cal.round(4).to_csv(f"validation/dopalvane_{TAG}_calib.csv", index=False)
    m = o[key + ["date", "hg", "ag"]].copy()
    m["lam_old"], m["mu_old"], m["lam_new"], m["mu_new"] = o.lam.round(5), o.mu.round(5), n.lam.round(5), n.mu.round(5)
    m["brier_old"], m["brier_new"] = bo.round(6), bn.round(6)
    m.to_csv(f"validation/dopalvane_{TAG}_matches.csv", index=False)
    write_md(lgs, cal, ref)
    print(lgs.to_string(index=False))
    print(cal.to_string(index=False))
    print(ref)


def write_md(lgs, cal, ref):
    L = ["# ДОПЪЛВАНЕ 02.10.2026 - мерилото преди/след попълването на дупките (т.2.3)", "",
         "Скрипт: `validation/dopalvane_20261002.py` (методът - в докстринга). Данни: `data_backups/20261002_dopalvane/old|new/`.",
         "Сравнение на едни и същи мачове (тестовите мачове от пуска \"преди\"); Brier - 11-те изхода на мерилото, показваното число",
         "(след калибрацията). Разлика = след - преди (отрицателно = по-добре); 95% интервал - bootstrap по мач.", "",
         "## Brier по лига", "",
         "| лига | общи мачове | тест преди / след | Brier преди | Brier след | разлика | 95% интервал | средна промяна на λ / μ | извод |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in lgs.itertuples():
        L.append(f"| {r.league} | {r.n_common} | {r.n_old_test} / {r.n_new_test} | {r.brier_old:.5f} | {r.brier_new:.5f} | "
                 f"{r.diff:+.5f} | [{r.ci_lo:+.5f}; {r.ci_hi:+.5f}] | {r.lam_mean_abs_change:.4f} / {r.mu_mean_abs_change:.4f} | {r.verdict} |")
    L += ["", f"Справка: bulgaria \"след\" на всичките си тестови мачове ({ref['n_all']}, с {ref['n_added']} нови, които \"преди\" "
          f"ги нямаше изобщо): Brier {ref['brier_all']:.5f}; само новите: {ref['brier_added']:.5f}.", "",
          "## Калибрация a (показваното число; рамка 0.9-1.1)", "",
          "Интервал - 95% за (a след - a преди), bootstrap по мач (1000, seed 42).", "",
          "| лига | обхват | n | група | a преди | a след | интервал на разликата |", "|---|---|---|---|---|---|---|"]
    for r in cal.itertuples():
        L.append(f"| {r.league} | {r.scope} | {r.n} | {r.group} | {r.a_old:.3f} | {r.a_new:.3f} | [{r.d_lo:+.3f}; {r.d_hi:+.3f}] |")
    open(f"validation/dopalvane_{TAG}.md", "w", encoding="utf-8").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
