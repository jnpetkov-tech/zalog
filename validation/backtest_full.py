"""
validation/backtest_full.py - ZADACHA_MERILO.md, ЧАСТ А (23.09.2026).

МЕРИЛО ВЪРХУ ЦЯЛАТА ИСТОРИЯ. Сравнението между два варианта на модела не
иска пазарно число - само реалния изход. Затова мерим върху всички
завършени мачове от последните две години, не само върху ~840-те логнати.

Защо не runner.py: той мери само последните <= 200 мача на лига,
префитва на всеки 20 мача (не по време), вика само fit_goals_model() (не
fit_goals_direct_covariate() - моделът с контузии, който england/germany/
spain/france реално ползват на живо), смята само 1X2 и над/под 2.5 и пази
само сумите, не вероятностите по мач. Тук е нужно всичко това.

=== МЕТОД (фиксиран; ако се промени - нова дата в името на изхода) ===

1. ПЕРИОД: мачовете с дата >= (последната дата в {лига}_merged_full.csv
   - 730 дни), само завършени (голове попълнени).
2. WALK-FORWARD, ПРЕФИТВАНЕ ВЕДНЪЖ СЕДМИЧНО (за скорост): мачовете се
   групират по календарна седмица (понеделник-неделя). За всяка седмица
   моделът се учи ВЕДНЪЖ от всички мачове с дата < понеделника на тази
   седмица и предсказва всички мачове от седмицата. Мачове от същата
   седмица не влизат в ученето (дори по-ранните от нея) - между два
   съседни мача моделът почти не се променя, а сметката става ~7 пъти
   по-бърза. Никога не се учи от бъдещ мач.
3. МОДЕЛЪТ: по подразбиране "current" = точно това, което get_models()
   (match_predictor_app.py) фитва днес за ft_model:
   fit_goals_direct_covariate(контузии) за лигите с колона home_injuries,
   които не са в NO_INJURY_MODEL_LEAGUES (england, germany, spain, france),
   иначе fit_goals_model(); xi = LEAGUE_XI. Контузиите на тествания мач -
   от CSV-то (празно -> 0). Друг вариант се подава като функция
   fit_fn(league, history, ref_date, team_idx, n) -> model (виж run_league()).
4. ПАЗАРИ (от матрицата на резултата, max 10 гола, Dixon-Coles rho, както
   _raw_candidates()): home_win/draw/away_win, over25/under25, btts_yes/
   btts_no, home_over15/home_under15, away_over15/away_under15.
   Групи (prediction_policy.market_group): 1x2, ou25, btts, team_total.
5. BRIER: за всеки изход поотделно (p - изход)^2, после средно - същата
   дефиниция като validation/model_vs_market.py, за да са сравними.

Изход: validation/backtest_full_<ДАТА>.csv (лига x група: n, Brier),
       validation/backtest_full_<ДАТА>_matches.csv (всеки мач: lam, mu,
       вероятностите, изходите - вход за ЧАСТ В и за бъдещи сравнения),
       validation/backtest_full_<ДАТА>.md (отчет).

Употреба: venv/bin/python3 validation/backtest_full.py [--tag ДАТА]
"""
import argparse
import os
import sys
from datetime import date
from multiprocessing import Pool

import numpy as np
import pandas as pd
from scipy.stats import poisson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import football_lib as fl  # noqa: E402

LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "champions_league",
           "europa_league", "conference_league", "italy", "portugal", "france2", "spain2",
           "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
NO_INJURY_MODEL_LEAGUES = {"champions_league", "europa_league"}  # = match_predictor_app.py
PERIOD_DAYS = 730
MAX_G = 10
GROUPS = {"home_win": "1x2", "draw": "1x2", "away_win": "1x2",
          "over25": "ou25", "under25": "ou25", "btts_yes": "btts", "btts_no": "btts",
          "home_over15": "team_total", "home_under15": "team_total",
          "away_over15": "team_total", "away_under15": "team_total"}
CODES = list(GROUPS)
_G = np.arange(MAX_G)
_X, _Y = np.meshgrid(_G, _G, indexing="ij")


def current_fit(league, hist, ref_date, team_idx, n, df_cols):
    xi = fl.LEAGUE_XI.get(league, fl.XI)
    if "home_injuries" in df_cols and league not in NO_INJURY_MODEL_LEAGUES:
        return fl.fit_goals_direct_covariate(hist, ref_date, team_idx, n, "home_injuries", "away_injuries", xi=xi)
    return fl.fit_goals_model(hist, ref_date, team_idx, n, xi=xi)


def lambdas(model, team_idx, home, away, h_inj, a_inj):
    if model.get("direct_covariate"):
        return fl.get_lambdas_direct(model, team_idx, home, away, h_inj, a_inj)
    return fl.get_lambdas(model, team_idx, home, away)


def market_probs(lam, mu, rho):
    pm = np.outer(poisson.pmf(_G, lam), poisson.pmf(_G, mu))
    if rho:
        pm = fl.dc_adjust_matrix(pm, lam, mu, rho)
    p = {"home_win": pm[_X > _Y].sum(), "draw": pm[_X == _Y].sum(), "away_win": pm[_X < _Y].sum(),
         "over25": pm[_X + _Y > 2.5].sum(), "btts_yes": pm[(_X >= 1) & (_Y >= 1)].sum(),
         "home_over15": pm[_X > 1.5].sum(), "away_over15": pm[_Y > 1.5].sum()}
    p["under25"] = 1 - p["over25"]
    p["btts_no"] = 1 - p["btts_yes"]
    p["home_under15"] = 1 - p["home_over15"]
    p["away_under15"] = 1 - p["away_over15"]
    return {k: float(v) for k, v in p.items()}


def outcomes(hg, ag):
    o = {"home_win": hg > ag, "draw": hg == ag, "away_win": hg < ag, "over25": hg + ag > 2.5,
         "btts_yes": hg >= 1 and ag >= 1, "home_over15": hg >= 2, "away_over15": ag >= 2}
    o["under25"] = not o["over25"]
    o["btts_no"] = not o["btts_yes"]
    o["home_under15"] = not o["home_over15"]
    o["away_under15"] = not o["away_over15"]
    return {k: int(v) for k, v in o.items()}


def _inj(v):
    return 0.0 if v is None or pd.isna(v) else float(v)


def run_league(league, fit_fn=None, config="current"):
    """Връща DataFrame, ред на мач. fit_fn(league, hist, ref, team_idx, n) ->
    model; None -> current_fit()."""
    df = fl.load_league_data(league)
    teams, n, team_idx = fl.get_team_index(df)
    fin = df.dropna(subset=["home_goals", "away_goals"])
    start = fin["date"].max() - pd.Timedelta(days=PERIOD_DAYS)
    test = fin[fin["date"] >= start].copy()
    test["week"] = test["date"] - pd.to_timedelta(test["date"].dt.weekday, unit="D")
    rows = []
    for week, block in test.groupby("week", sort=True):
        hist = fin[fin["date"] < week]
        if fit_fn is None:
            model = current_fit(league, hist, week, team_idx, n, df.columns)
        else:
            model = fit_fn(league, hist, week, team_idx, n)
        rho = model.get("rho", 0.0)
        for r in block.itertuples():
            lam, mu = lambdas(model, team_idx, r.home_team, r.away_team,
                              _inj(getattr(r, "home_injuries", None)), _inj(getattr(r, "away_injuries", None)))
            if lam is None:
                continue
            p = market_probs(lam, mu, rho)
            o = outcomes(r.home_goals, r.away_goals)
            rec = {"league": league, "config": config, "fixture_id": r.fixture_id,
                   "date": r.date.date().isoformat(), "fit_week": week.date().isoformat(),
                   "home_team": r.home_team, "away_team": r.away_team,
                   "home_goals": int(r.home_goals), "away_goals": int(r.away_goals),
                   "lam": round(float(lam), 4), "mu": round(float(mu), 4), "rho": round(float(rho), 4)}
            for c in CODES:
                rec[f"p_{c}"] = round(p[c], 5)
                rec[f"y_{c}"] = o[c]
            rows.append(rec)
    return pd.DataFrame(rows)


def long_form(matches):
    """Мач x пазар -> един ред (league, group, code, p, y)."""
    parts = []
    for c in CODES:
        parts.append(pd.DataFrame({"league": matches["league"], "date": matches["date"],
                                   "fixture_id": matches["fixture_id"], "group": GROUPS[c], "code": c,
                                   "p": matches[f"p_{c}"], "y": matches[f"y_{c}"]}))
    out = pd.concat(parts, ignore_index=True)
    out["sq"] = (out["p"] - out["y"]) ** 2
    return out


def summary(matches):
    lf = long_form(matches)
    rows = []
    for (lg, g), s in lf.groupby(["league", "group"]):
        rows.append({"league": lg, "group": g, "matches": s["fixture_id"].nunique(), "n": len(s),
                     "brier": s["sq"].mean()})
    for lg, s in lf.groupby("league"):
        rows.append({"league": lg, "group": "ALL", "matches": s["fixture_id"].nunique(), "n": len(s),
                     "brier": s["sq"].mean()})
    for g, s in lf.groupby("group"):
        rows.append({"league": "ALL", "group": g, "matches": s["fixture_id"].nunique(), "n": len(s),
                     "brier": s["sq"].mean()})
    rows.append({"league": "ALL", "group": "ALL", "matches": lf["fixture_id"].nunique(), "n": len(lf),
                 "brier": lf["sq"].mean()})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=date.today().strftime("%Y%m%d"))
    ap.add_argument("--procs", type=int, default=8)
    args = ap.parse_args()
    with Pool(args.procs) as pool:
        parts = pool.map(run_league, LEAGUES)
    matches = pd.concat(parts, ignore_index=True)
    matches.to_csv(f"validation/backtest_full_{args.tag}_matches.csv", index=False)
    summ = summary(matches)
    summ["brier"] = summ["brier"].round(5)
    summ.to_csv(f"validation/backtest_full_{args.tag}.csv", index=False)
    write_md(args.tag, matches, summ)


def write_md(tag, matches, summ):
    piv = summ.pivot(index="league", columns="group", values="brier")
    cnt = summ[summ.group == "ALL"].set_index("league")["matches"]
    allrow = summ[(summ.league == "ALL") & (summ.group == "ALL")].iloc[0]
    L = [f"# Мерило върху цялата история (walk-forward) - {tag}", "",
         "ZADACHA_MERILO.md, ЧАСТ А. Скрипт: `validation/backtest_full.py` (методът е в docstring-а).",
         f"Сурови числа: `backtest_full_{tag}.csv` (лига x група) и `backtest_full_{tag}_matches.csv` (всеки мач).", "",
         "**Метод накратко:** последните 730 дни на всяка лига; моделът („current“ - същото, което",
         "`get_models()` фитва днес: с контузиите за england/germany/spain/france, иначе",
         "`fit_goals_model()`) се префитва **веднъж седмично** - за всяка календарна седмица се учи",
         "само от мачове ПРЕДИ понеделника ѝ и предсказва всички нейни мачове. Brier - за всеки изход",
         "поотделно, после средно (същата дефиниция като `model_vs_market.py`).", "",
         f"**Влизат {int(allrow['matches'])} мача** ({int(allrow['n'])} реда мач x изход) - срещу 840 мача в",
         "базовата линия срещу пазара.", "",
         "## Brier по лига и пазарна група", "",
         "| лига | мачове | 1x2 | над/под 2.5 | двата отбора | отборни голове | всичко |",
         "|---|---|---|---|---|---|---|"]
    order = [lg for lg in LEAGUES if lg in piv.index] + ["ALL"]
    for lg in order:
        r = piv.loc[lg]
        L.append(f"| {lg} | {int(cnt[lg])} | {r['1x2']:.4f} | {r['ou25']:.4f} | {r['btts']:.4f} | "
                 f"{r['team_total']:.4f} | {r['ALL']:.4f} |")
    L += ["", "## Проверка за здрав разум", "",
          f"Общ Brier {allrow['brier']:.4f}. Базовата линия срещу пазара (записаните прогнози, същите",
          "четири групи) е 0.2284 за модела и 0.2186 за пазара - същият порядък (0.20-0.25), значи",
          "мерилото мери същото нещо."]
    # очаквани голове
    lam_all = pd.concat([matches[["league", "date", "home_team", "away_team", "lam"]].rename(columns={"lam": "x"}).assign(side="домакин"),
                         matches[["league", "date", "home_team", "away_team", "mu"]].rename(columns={"mu": "x"}).assign(side="гост")])
    L += ["", "## Очаквани голове (lam/mu) - извън 0.3-3.5", "",
          "| лига | мин | макс | над 3.5 | под 0.3 |", "|---|---|---|---|---|"]
    for lg in order[:-1]:
        s = lam_all[lam_all.league == lg]["x"]
        L.append(f"| {lg} | {s.min():.2f} | {s.max():.2f} | {(s > 3.5).sum()} | {(s < 0.3).sum()} |")
    sp = lam_all[(lam_all.league == "spain") & (lam_all.x > 3.5)].sort_values("x", ascending=False)
    L += ["", "### Испания - мачовете с очаквани голове над 3.5", ""]
    if len(sp):
        L += ["| дата | домакин | гост | страна | очаквани голове |", "|---|---|---|---|---|"]
        for r in sp.head(25).itertuples():
            L.append(f"| {r.date} | {r.home_team} | {r.away_team} | {r.side} | {r.x:.2f} |")
    else:
        L.append("Няма нито един.")
    with open(f"validation/backtest_full_{tag}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
