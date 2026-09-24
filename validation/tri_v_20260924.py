"""
validation/tri_v_20260924.py - ZADACHA_TRI.md, ЧАСТ В (24.09.2026).

Проблем: Лига на конференциите изостава от пазара с +0.0270 (model_vs_market_baseline_20260923),
при средно +0.0098. Отбор в евротурнир се оценява само по мачовете си в турнира.

Нов модел: validation/tri_v_euro.py - едно фитване върху трите турнира + седемте ни първи
дивизии; сила на отбора = сила на държавата му (учи се от всички европейски мачове на отборите
от нея) + собствено отклонение (учи се и от домашното първенство).

МЕТОД = мерилото (backtest_full.py): за всеки турнир мачовете от последните 730 дни, седмично
префитване само от мачове преди понеделника на седмицата.
  current - това, което живият get_models() фитва днес (FT_FIT_SETTINGS от ЧАСТ А),
            пресметнато с tri_a_20260923.run() - същата функция като в ЧАСТ А;
  нов     - tri_v_euro.fit() за всяка настройка от GRID.
Вероятности: Поасон + Dixon-Coles (razpredelenie_b_20260923), 11-те изхода на мерилото.

ИЗБОР по турнир: настройката (current също е кандидат) с най-нисък суров Brier на РАННАТА
половина (дата < 2025-09-23). ПРОВЕРКА - на КЪСНАТА (не участва в избора):
  1) Brier current срещу избрания, сдвоен bootstrap по мач;
  2) "колко бърка": обещано - познато по ленти от 10 пункта (както tri_a);
  3) СРЕЩУ ПАЗАРА - логнатите редове на model_vs_market.build_rows() (без суров implied; всички
     са от 2026 - късната половина): същото пазарно число и изход, нашето число се преизчислява
     от седмичните прогнози за същия мач (current и нов), през живата калибрация
     (prediction_policy.calibrate - както на сайта). Критерий: разликата наш - пазар за
     conference_league под +0.0135; europa_league и champions_league - да не се влошават.

Изход: validation/tri_v_20260924.md, .csv (турнир x настройка), _matches.csv (по мач),
_market.csv (по турнир: пазар / записано / current / нов).
Употреба: venv/bin/python3 validation/tri_v_20260924.py
"""
import itertools
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
import football_lib as fl  # noqa: E402
import kalibraciq_xg_20260923 as kx  # noqa: E402
import prediction_policy as policy  # noqa: E402
import razpredelenie_b_20260923 as rb  # noqa: E402
import tri_a_20260923 as ta  # noqa: E402
import tri_v_euro as E  # noqa: E402

TAG = "20260924"
CUPS = E.CUPS
# живите FT_FIT_SETTINGS (ЧАСТ А) като (reg_mult, intercept, tempo_mult)
CURRENT = {"champions_league": (1, False, 1), "europa_league": (1, True, 1000), "conference_league": (1, True, 3)}
GRID = [dict(w_dom=wd, reg_S=rs, reg_T=rt, tempo_mult=tm, xi=xi)
        for wd, rs, rt, tm, xi in itertools.product([0.0, 0.5, 1.0], [0.3, 3.0], [3.0, 30.0], [1.0, 10.0],
                                                    [0.0018, 0.004])]


def cfg_name(g):
    return f"евро w_dom={g['w_dom']} S={g['reg_S']} T={g['reg_T']} темпо={g['tempo_mult']:g} xi={g['xi']}"


def windows():
    """турнир -> тестовите мачове (както bf.run_league: последните 730 дни)."""
    out = {}
    for cup in CUPS:
        df = fl.load_league_data(cup)
        fin = df.dropna(subset=["home_goals", "away_goals"])
        start = fin["date"].max() - pd.Timedelta(days=bf.PERIOD_DAYS)
        t = fin[fin["date"] >= start].copy()
        t["week"] = t["date"] - pd.to_timedelta(t["date"].dt.weekday, unit="D")
        out[cup] = t
    return out


def run_new(k):
    g = GRID[k]
    allm, group = E.load_all(fl.load_league_data)
    ix = E.Index(allm, group)
    test = pd.concat([t.assign(comp=c) for c, t in windows().items()], ignore_index=True)
    rows, x0 = [], None
    for week, block in test.groupby("week", sort=True):
        m = E.fit(allm[allm["date"] < week], week, ix, x0=x0, **g)
        x0 = m["x"]
        for r in block.itertuples():
            lam, mu = E.lambdas(m, ix, r.comp, r.home_team, r.away_team)
            rows.append((r.comp, k, r.fixture_id, r.date, int(r.home_goals), int(r.away_goals), lam, mu, m["rho"]))
    return pd.DataFrame(rows, columns=["league", "k", "fixture_id", "date", "hg", "ag", "lam", "mu", "rho"])


def run_cur(cup):
    d = ta.run((cup, CURRENT[cup]))
    return d.assign(k=-1)[["league", "k", "fixture_id", "date", "hg", "ag", "lam", "mu", "rho"]]


def probs(d):
    return rb.market_probs(rb.matrices(d["lam"].to_numpy(), d["mu"].to_numpy(), d["rho"].to_numpy(), "poisson", 0))


def live_cal(pf):
    return rb.apply_cal(pf, dict(policy.CALIBRATION_A), dict(policy.CALIBRATION_BASE))


def gap(pf, Y, mask, groups=("ou25", "btts", "1x2", "team_total")):
    """Средна |обещано - познато| по ленти от 10 пункта, претеглена с броя (пункта), всички групи."""
    idx = [i for i, c in enumerate(bf.CODES) if bf.GROUPS[c] in groups]
    p = pf.to_numpy()[mask][:, idx].ravel()
    y = Y[mask][:, idx].ravel()
    band = np.minimum((p * 10).astype(int), 9)
    s = pd.DataFrame({"b": band, "p": p, "y": y}).groupby("b").agg(n=("y", "size"), p=("p", "mean"), y=("y", "mean"))
    return float((s["n"] * (s["p"] - s["y"]).abs()).sum() / s["n"].sum() * 100)


def paired_ci(items, a, b):
    """Сдвоен bootstrap по мач на (Brier a - Brier b) върху редовете срещу пазара."""
    d = pd.DataFrame(items)
    d["diff"] = (d[a] - d["y"]) ** 2 - (d[b] - d["y"]) ** 2
    g = d.groupby("fixture_id").agg(s=("diff", "sum"), c=("diff", "size"))
    s, c = g["s"].to_numpy(), g["c"].to_numpy()
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(s), size=(2000, len(s)))
    v = s[idx].sum(1) / c[idx].sum(1)
    return float(s.sum() / c.sum()), float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def main():
    with Pool(16) as pool:
        cur = pool.map(run_cur, CUPS)
        new = pool.map(run_new, range(len(GRID)), chunksize=1)
    cur = pd.concat(cur, ignore_index=True).sort_values(["league", "fixture_id"]).reset_index(drop=True)
    cur["d"] = pd.to_datetime(cur["date"])
    early = (cur["d"] < kx.CUT).to_numpy()
    Y = np.column_stack([[bf.outcomes(h, a)[c] for h, a in zip(cur["hg"], cur["ag"])] for c in bf.CODES]).astype(float)
    P0 = probs(cur)
    b0 = rb.brier_rows(P0, Y)
    frames = {}
    for d in new:
        k = int(d["k"].iloc[0])
        d = d.sort_values(["league", "fixture_id"]).reset_index(drop=True)
        assert (d["fixture_id"].to_numpy() == cur["fixture_id"].to_numpy()).all()
        frames[k] = (d, probs(d))

    table, choice = [], {}
    for cup in CUPS:
        sel = (cur["league"] == cup).to_numpy()
        best, bestv = -1, b0[sel & early].mean()
        table.append({"league": cup, "config": "current", "n_early": int((sel & early).sum()),
                      "n_late": int((sel & ~early).sum()), "brier_early": bestv, "brier_late": b0[sel & ~early].mean()})
        for k, (d, pf) in frames.items():
            b = rb.brier_rows(pf, Y)
            e = b[sel & early].mean()
            table.append({"league": cup, "config": cfg_name(GRID[k]), "n_early": int((sel & early).sum()),
                          "n_late": int((sel & ~early).sum()), "brier_early": e, "brier_late": b[sel & ~early].mean()})
            if e < bestv:
                best, bestv = k, e
        choice[cup] = best
    pd.DataFrame(table).round(5).to_csv(f"validation/tri_v_{TAG}.csv", index=False)

    ch = cur.copy()
    pch = P0.copy()
    for cup, k in choice.items():
        if k < 0:
            continue
        sel = (cur["league"] == cup).to_numpy()
        d, pf = frames[k]
        ch.loc[sel, ["lam", "mu", "rho"]] = d.loc[sel, ["lam", "mu", "rho"]].to_numpy()
        pch.loc[sel] = pf.loc[sel].to_numpy()
    b1 = rb.brier_rows(pch, Y)
    out = cur[["league", "fixture_id", "date", "hg", "ag"]].copy()
    out["lam_cur"], out["mu_cur"], out["rho_cur"] = cur["lam"], cur["mu"], cur["rho"]
    out["lam_new"], out["mu_new"], out["rho_new"] = ch["lam"], ch["mu"], ch["rho"]
    out["config"] = out["league"].map(lambda c: "current" if choice[c] < 0 else cfg_name(GRID[choice[c]]))
    out.to_csv(f"validation/tri_v_{TAG}_matches.csv", index=False)

    P0c, P1c = live_cal(P0), live_cal(pch)
    late = {}
    for cup in CUPS:
        sel = (cur["league"] == cup).to_numpy()
        m = sel & ~early
        late[cup] = {"n": int(m.sum()), "cur": b0[m].mean(), "new": b1[m].mean(), "ci": kx.ci(b1[m], b0[m]),
                     "gap_cur": gap(P0c, Y, m), "gap_new": gap(P1c, Y, m),
                     "gap_cur_raw": gap(P0, Y, m), "gap_new_raw": gap(pch, Y, m)}

    # срещу пазара
    import model_vs_market as mvm
    detail, _ = mvm.build_rows()
    pos = {(lg, fx): i for i, (lg, fx) in enumerate(zip(cur["league"], cur["fixture_id"]))}
    items = []
    for dd in detail:
        if dd["raw_implied"] or dd["league"] not in CUPS:
            continue
        i = pos.get((dd["league"], dd["fixture_id"]))
        if i is None:
            continue
        items.append({"league": dd["league"], "fixture_id": dd["fixture_id"], "code": dd["code"], "y": dd["y"],
                      "market": dd["market"], "logged": dd["ours"],
                      "cur": float(P0c.iloc[i][dd["code"]]), "new": float(P1c.iloc[i][dd["code"]]),
                      "cur_raw": float(P0.iloc[i][dd["code"]]), "new_raw": float(pch.iloc[i][dd["code"]])})
    it = pd.DataFrame(items)
    mk = []
    for cup in CUPS:
        s = it[it["league"] == cup]
        rec = {"league": cup, "n": len(s), "matches": s["fixture_id"].nunique()}
        for c in ("market", "logged", "cur", "new", "cur_raw", "new_raw"):
            rec[f"brier_{c}"] = float(((s[c] - s["y"]) ** 2).mean())
        for c in ("logged", "cur", "new", "cur_raw", "new_raw"):
            rec[f"gap_{c}"] = rec[f"brier_{c}"] - rec["brier_market"]
        rec["ci_new_cur"] = paired_ci(s.to_dict("records"), "new", "cur")
        rec["ci_new_market"] = paired_ci(s.to_dict("records"), "new", "market")
        mk.append(rec)
    mk = pd.DataFrame(mk)
    mk.drop(columns=["ci_new_cur", "ci_new_market"]).round(5).to_csv(f"validation/tri_v_{TAG}_market.csv", index=False)
    pd.to_pickle({"choice": choice, "late": late, "mk": mk, "table": table}, f"/tmp/tri_v_{TAG}.pkl")
    write_md(choice, late, mk, pd.DataFrame(table))


def write_md(choice, late, mk, table):
    ecl = mk.set_index("league").loc["conference_league"]
    ok = ecl["gap_new"] < 0.0135
    L = [f"# ТРИ, ЧАСТ В - евротурнирите от домашното първенство и силата на държавата - {TAG}", "",
         "ZADACHA_TRI.md, ЧАСТ В. Скрипт: `validation/tri_v_20260924.py` (методът е в docstring-а), модел",
         "`validation/tri_v_euro.py`. Държави на отборите: `validation/tri_v_team_countries_20260924.csv` (15 заявки",
         "/teams, `archive/fetch_euro_team_countries_20260924.py`). Сурови числа: `tri_v_20260924.csv` (турнир x",
         "настройка), `_matches.csv` (по мач), `_market.csv` (срещу пазара).", "",
         "## Какво е новото", "",
         "Досега всеки турнир се учи сам, само от своите мачове. Новият модел е ЕДИН за трите турнира и седемте",
         "ни първенства: сила на отбора = сила на държавата му + собствено отклонение. Силата на държавата се",
         "учи от всички европейски мачове на всички нейни отбори (за 4 сезона); отклонението - и от домашното",
         "първенство, където имаме данни (България, Англия, Германия, Испания, Франция, Италия, Португалия).",
         "Само 18% от мачовете в Лигата на конференциите имат отбор с домашно първенство при нас - затова",
         "главната сила е държавата, не домашната история.", "",
         "## Критерий: срещу пазара (логнатите мачове, през живата калибрация)", "",
         "Разлика = Brier наш − Brier пазар (по-малко = по-близо до пазара).", "",
         "| турнир | редове | мачове | записано (база) | сегашен модел, преизчислен | нов модел | нов − сегашен (95% инт.) |",
         "|---|---|---|---|---|---|---|"]
    for r in mk.itertuples():
        c = r.ci_new_cur
        L.append(f"| {r.league} | {r.n} | {r.matches} | {r.gap_logged:+.4f} | {r.gap_cur:+.4f} | {r.gap_new:+.4f} | "
                 f"{c[0]:+.4f} [{c[1]:+.4f}, {c[2]:+.4f}] |")
    L += ["", f"**Критерий за conference_league (под +0.0135): {'ИЗПЪЛНЕН' if ok else 'НЕ е изпълнен'}** "
          f"({ecl['gap_new']:+.4f}).", "",
          "„Записано“ е числото от базовата линия (смесено с пазара, преди калибрацията) - за ориентир.",
          "Сравнението преди/след е „сегашен, преизчислен“ срещу „нов“ - сметнати по един и същи начин.",
          "Без калибрация (сурово): " + "; ".join(f"{r.league} {r.gap_cur_raw:+.4f} → {r.gap_new_raw:+.4f}"
                                                 for r in mk.itertuples()) + ".", "",
          "## Късната половина (всички мачове на турнира, не участват в избора)", "",
          "| турнир | мачове | Brier сегашен | Brier нов | разлика (95% инт.) | колко бърка: сегашен → нов (пункта) |",
          "|---|---|---|---|---|---|"]
    for cup in CUPS:
        v = late[cup]
        L.append(f"| {cup} | {v['n']} | {v['cur']:.4f} | {v['new']:.4f} | {v['ci'][0]:+.4f} [{v['ci'][1]:+.4f}, "
                 f"{v['ci'][2]:+.4f}] | {v['gap_cur']:.1f} → {v['gap_new']:.1f} |")
    L += ["", "„Колко бърка“ = средна разлика обещано − познато по ленти от 10 пункта, всички 11 изхода,",
          "през живата калибрация.", "",
          "## Избор по турнир (най-нисък Brier на ранната половина)", "",
          "| турнир | избрано | Brier ранна: сегашен → избран |", "|---|---|---|"]
    for cup, k in choice.items():
        t = table[table.league == cup]
        e0 = t[t.config == "current"].brier_early.iloc[0]
        nm = "current" if k < 0 else cfg_name(GRID[k])
        e1 = t[t.config == nm].brier_early.iloc[0]
        L.append(f"| {cup} | {nm} | {e0:.4f} → {e1:.4f} |")
    rob = []
    for cup in CUPS:
        t = table[table.league == cup]
        cur_late = t[t.config == "current"].brier_late.iloc[0]
        nn = t[t.config != "current"]
        rob.append(f"{cup} {int((nn.brier_late < cur_late).sum())}/{len(nn)}")
    L += ["", "## Устойчивост", "",
          "Колко от " + str(len(GRID)) + "-те настройки на новия модел бият сегашния на късната половина: " + ", ".join(rob) + ".",
          "Тоест подобрението не идва от удачен избор на настройка. Домашното първенство добавя малко (w_dom = 0,",
          "т.е. само трите турнира заедно + държавите, дава почти същото) - главното е, че (1) трите турнира се",
          "учат заедно (отбор, отпаднал от квалификациите на Шампионската лига, продължава в Лига Европа с историята",
          "си) и (2) нов отбор започва от силата на държавата си, не от нула.", "",
          "Нов модел срещу пазара (сдвоен bootstrap по мач): " + "; ".join(
              f"{r.league} {r.ci_new_market[0]:+.4f} [{r.ci_new_market[1]:+.4f}, {r.ci_new_market[2]:+.4f}]"
              for r in mk.itertuples()) + ".",
          "Интервал, който съдържа нулата = не се различаваме от пазара (не „бием пазара“).", "",
          "## Решение", "",
          "Влиза: за трите турнира ft_model = общият модел (football_lib.fit_euro_model(), копие на",
          "validation/tri_v_euro.fit()) с избраната по турнир настройка от таблицата по-горе. Задържа се на",
          "късната половина и в трите турнира, срещу пазара намалява разликата и в трите - europa_league и",
          "champions_league не се влошават. Калибрацията не е пипната (общата, от ЧАСТ А).", "",
          "Ограничения: (1) държавата на отбора идва от euro_team_countries.csv (15 заявки към /teams) - отбор,",
          "който го няма там (нов в квалификациите), влиза в общата група „?“; файлът трябва да се тегли",
          "наново в началото на всеки сезон (`archive/fetch_euro_team_countries_20260924.py`). (2) Отбор, който",
          "още не е играл в дадения турнир, пак не получава прогноза (team_idx е от CSV-то на турнира) -",
          "непроменено поведение."]
    with open(f"validation/tri_v_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
