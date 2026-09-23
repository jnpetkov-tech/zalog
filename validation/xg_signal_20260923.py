"""
validation/xg_signal_20260923.py - ZADACHA_XG.md, ЧАСТИ Б, В и Г (23.09.2026).

Въпрос: ако силата на отборите се учи от xG / ударите (вместо само от
головете) и мачовете с червен картон тежат наполовина, по-близо ли е моделът
до пазара?

=== ЧАСТ Б - избор на сигнал по лига (автоматично, от data_inventory) ===
- xG попълнен >= 70% -> кандидати "xg" с тегло w в {0.0, 0.3, 0.5, 0.7, 1.0}
  (сигнал = w*xG + (1-w)*голове, където xG липсва -> голове);
- иначе удари И удари в целта >= 70% -> кандидат "shots" (strength_signal.
  shots_conversion(): голове ~ a*в целта + b*извън целта, по лига, само
  от историята преди точката на преобучение);
- иначе -> само сегашният модел.
Сегашният модел ("current") винаги е кандидат - същото, което get_models()
вика днес: fit_goals_direct_covariate(контузии) за england/germany/spain/
france, fit_goals_model() за останалите. Сигналите минават през
fit_goals_model(cov_home_col=..., cov_away_col=...) - машинарията не е
пипната (за четирите лиги с контузии това значи: контузиите отпадат).

Избор "две хронологични половини" (методът от blend_weight_out_of_sample.py):
тестов прозорец = последните 240 завършени мача ПРЕДИ 2026-08-01 (т.е. преди
първия мач от ЧАСТ Г - изборът не вижда мачовете, върху които се мери).
Walk-forward: преобучение на всеки 20 мача, само от мачове с дата < първия
мач от блока. Кандидатът с най-нисък Brier на ПЪРВАТА половина (120 мача) се
прилага без преизбор на ВТОРАТА; приема се само ако там е по-добър от
current. Brier = средно (p - изход)^2 върху home_win, draw, away_win,
over25, btts_yes, home_over15, away_over15.

=== ЧАСТ В - червен картон ===
Само лигите с попълнена колона red >= 70% (сурово, от data_inventory):
теглото на мач с червен картон x0.5 (fit_goals_model(row_weight_col=...)).
Мери се в ЧАСТ Г като отделна конфигурация.

=== ЧАСТ Г - срещу пазара ===
model_vs_market.py мери ЗАПИСАНИТЕ в predictions_log проценти - нов модел
не може да ги промени. Затова: същите редове (build_rows(), без суров
implied: 1x2, над/под 2.5, btts, голове по отбор - 8260 реда), същото
пазарно число и изход, но "нашето" число се преизчислява walk-forward
(модел от мачове с дата < датата на мача) с current и с новата
конфигурация. Така "преди" и "след" са сметнати по един и същи начин.
Плюс: сдвоен bootstrap по мач на (Brier нов - Brier current), 2000, seed 42.

Изход: validation/xg_signal_20260923_selection.csv, _eval.csv, _range.csv
и validation/xg_signal_20260923.md
"""
import json
import os
import sys
from collections import defaultdict
from multiprocessing import Pool

import numpy as np
import pandas as pd
from scipy.stats import poisson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if os.environ.get("XG_LIB"):  # локален тест срещу копие на football_lib.py преди пипане на живия
    sys.path.insert(0, os.environ["XG_LIB"])
os.chdir(ROOT)

import football_lib as fl  # noqa: E402
import strength_signal as ss  # noqa: E402

TAG = "20260923"
SEL_END = pd.Timestamp("2026-08-01")
SEL_N, BLOCK = 240, 20
XG_WEIGHTS = [0.0, 0.3, 0.5, 0.7, 1.0]
THRESH = 70.0
INJURY_LEAGUES = {"england", "germany", "spain", "france"}  # has_injuries в get_models()
CODES = ["home_win", "draw", "away_win", "over25", "under25", "btts_yes", "btts_no",
         "home_over15", "home_under15", "away_over15", "away_under15"]
SEL_CODES = ["home_win", "draw", "away_win", "over25", "btts_yes", "home_over15", "away_over15"]
RANGE_LO, RANGE_HI = 0.3, 3.5


def inventory():
    inv = pd.read_csv(os.path.join(ROOT, "validation", f"data_inventory_{TAG}.csv"))
    return {r.league: r for r in inv.itertuples()}


def candidates(inv_row):
    if inv_row.xg_pct >= THRESH:
        return "xg", [{"kind": "xg", "w": w} for w in XG_WEIGHTS]
    if inv_row.shots_pct >= THRESH and inv_row.shots_on_goal_pct >= THRESH:
        return "shots", [{"kind": "shots"}]
    return "goals", []


def cfg_name(cfg):
    if cfg is None:
        return "current"
    s = cfg["kind"] if cfg.get("kind") else "current"
    if cfg.get("kind") == "xg":
        s += f"_{cfg['w']}"
    if cfg.get("red"):
        s += "+red"
    return s


def fit(league, hist, ref_date, team_idx, n, cfg):
    xi = fl.LEAGUE_XI.get(league, fl.XI)
    if (cfg is None or not cfg.get("kind")) and league in INJURY_LEAGUES:
        # current за лигите с контузии; "+red" не е приложимо тук (red < 70%)
        return fl.fit_goals_direct_covariate(hist, ref_date, team_idx, n, "home_injuries", "away_injuries", xi=xi)
    h, kw = ss.prepare(hist, cfg)
    return fl.fit_goals_model(h, ref_date, team_idx, n, xi=xi, **kw)


def lambdas(model, team_idx, home, away, h_inj, a_inj):
    if model.get("direct_covariate"):
        return fl.get_lambdas_direct(model, team_idx, home, away, h_inj, a_inj)
    return fl.get_lambdas(model, team_idx, home, away)


def probs(lam, mu, rho):
    """Същата сметка като _raw_candidates()/extra_markets_probs() (max_g=10)."""
    g = 10
    pm = np.outer(poisson.pmf(range(g), lam), poisson.pmf(range(g), mu))
    if rho:
        pm = fl.dc_adjust_matrix(pm, lam, mu, rho)
    x, y = np.meshgrid(range(g), range(g), indexing="ij")
    p = {"home_win": pm[x > y].sum(), "draw": pm[x == y].sum(), "away_win": pm[x < y].sum(),
         "over25": pm[x + y > 2.5].sum(), "btts_yes": pm[(x >= 1) & (y >= 1)].sum(),
         "home_over15": pm[x > 1.5].sum(), "away_over15": pm[y > 1.5].sum()}
    p["under25"] = 1 - p["over25"]
    p["btts_no"] = 1 - p["btts_yes"]
    p["home_under15"] = 1 - p["home_over15"]
    p["away_under15"] = 1 - p["away_over15"]
    return p


def outcomes(hg, ag):
    return {"home_win": hg > ag, "draw": hg == ag, "away_win": hg < ag, "over25": hg + ag > 2.5,
            "btts_yes": hg >= 1 and ag >= 1, "home_over15": hg >= 2, "away_over15": ag >= 2}


def inj(v):
    return 0.0 if v is None or pd.isna(v) else float(v)


# ---------------------------------------------------------------- ЧАСТ Б
def selection(league):
    inv = inventory()[league]
    kind, cands = candidates(inv)
    df = fl.load_league_data(league)
    teams, n, team_idx = fl.get_team_index(df)
    fin = df.dropna(subset=["home_goals", "away_goals"])
    test = fin[fin["date"] < SEL_END].tail(SEL_N).reset_index(drop=True)
    configs = [None] + cands
    rows = []
    for start in range(0, len(test), BLOCK):
        block = test.iloc[start:start + BLOCK]
        ref = block["date"].min()
        hist = fin[fin["date"] < ref]
        for cfg in configs:
            m = fit(league, hist, ref, team_idx, n, cfg)
            rho = m.get("rho", 0.0)
            for i, r in block.iterrows():
                lam, mu = lambdas(m, team_idx, r.home_team, r.away_team,
                                  inj(r.get("home_injuries")), inj(r.get("away_injuries")))
                p = probs(lam, mu, rho)
                o = outcomes(r.home_goals, r.away_goals)
                b = float(np.mean([(p[c] - o[c]) ** 2 for c in SEL_CODES]))
                rows.append({"league": league, "config": cfg_name(cfg), "i": int(i),
                             "half": 1 if i < len(test) // 2 else 2, "brier": b})
    return league, kind, rows


def pick(league, kind, rows):
    d = pd.DataFrame(rows)
    t = d.groupby(["config", "half"])["brier"].mean().unstack()
    if kind == "goals":
        return {"league": league, "kind": kind, "chosen": "current", "cfg": None, "table": t,
                "why": "няма xG/удари >= 70% - сегашният модел без промяна"}
    best = t[1].idxmin()
    cur2, best2 = t.loc["current", 2], t.loc[best, 2]
    if best == "current":
        why = "на 1-ва половина current е най-добър"
        chosen = "current"
    elif best2 < cur2:
        why = f"{best} най-добър на 1-ва половина и по-добър от current и на 2-ра ({best2:.4f} < {cur2:.4f})"
        chosen = best
    else:
        why = f"{best} най-добър на 1-ва половина, но НЕ издържа на 2-ра ({best2:.4f} >= {cur2:.4f})"
        chosen = "current"
    cfg = None
    if chosen != "current":
        cfg = {"kind": "shots"} if chosen == "shots" else {"kind": "xg", "w": float(chosen.split("_")[1])}
    return {"league": league, "kind": kind, "chosen": chosen, "cfg": cfg, "table": t, "why": why,
            "best_first": best}


# ---------------------------------------------------------------- ЧАСТ Г
def eval_rows():
    sys.path.insert(0, os.path.join(ROOT, "validation"))
    import model_vs_market as mvm
    import system_tracker as st
    detail, _ = mvm.build_rows()
    detail = [d for d in detail if not d["raw_implied"]]
    info = {r["fixture_id"]: r for r in st.list_predictions()}
    for d in detail:
        r = info[d["fixture_id"]]
        d["home_team"], d["away_team"], d["match_date"] = r["home_team"], r["away_team"], r["match_date"][:10]
    return detail


def replay(args):
    league, fixtures, configs = args
    df = fl.load_league_data(league)
    teams, n, team_idx = fl.get_team_index(df)
    fin = df.dropna(subset=["home_goals", "away_goals"])
    by_id = df.drop_duplicates("fixture_id").set_index("fixture_id")
    out = {}  # (config, fixture_id) -> probs
    missing = []
    by_date = defaultdict(list)
    for fx, (home, away, date) in fixtures.items():
        by_date[date].append((fx, home, away))
    for date, fxs in sorted(by_date.items()):
        ref = pd.Timestamp(date)
        hist = fin[fin["date"] < ref]
        for cfg in configs:
            m = fit(league, hist, ref, team_idx, n, cfg)
            rho = m.get("rho", 0.0)
            for fx, home, away in fxs:
                if fx in by_id.index:
                    r = by_id.loc[fx]
                    h_inj, a_inj = inj(r.get("home_injuries")), inj(r.get("away_injuries"))
                else:
                    h_inj = a_inj = 0.0
                lam, mu = lambdas(m, team_idx, home, away, h_inj, a_inj)
                if lam is None:
                    missing.append(fx)
                    continue
                out[(cfg_name(cfg), fx)] = probs(lam, mu, rho)
    return league, out, sorted(set(missing))


def range_check(args):
    """Очаквани голове за всички двойки отбори, играли в лигата последните
    365 дни - модел от всички данни, както get_models()."""
    league, cfg = args
    df = fl.load_league_data(league)
    teams, n, team_idx = fl.get_team_index(df)
    ref = df["date"].max()
    recent = df[df["date"] >= ref - pd.Timedelta(days=365)]
    active = sorted(set(recent.home_team) | set(recent.away_team))
    res = {}
    for name, c in (("current", None), (cfg_name(cfg), cfg)):
        m = fit(league, df, ref, team_idx, n, c)
        vals = []
        for h in active:
            for a in active:
                if h != a:
                    lam, mu = lambdas(m, team_idx, h, a, 0.0, 0.0)
                    vals += [lam, mu]
        res[name] = (float(np.min(vals)), float(np.max(vals)),
                     float(np.mean([(v < RANGE_LO or v > RANGE_HI) for v in vals])))
    return league, res


def brier_block(items, key):
    y = np.array([d["y"] for d in items], float)
    o = np.array([d[key] for d in items], float)
    return float(((o - y) ** 2).mean())


def paired_ci(items, a, b):
    fx = defaultdict(float)
    for d in items:
        fx[d["fixture_id"]] += (d[a] - d["y"]) ** 2 - (d[b] - d["y"]) ** 2
    cnt = defaultdict(int)
    for d in items:
        cnt[d["fixture_id"]] += 1
    keys = list(fx)
    s = np.array([fx[k] for k in keys])
    c = np.array([cnt[k] for k in keys])
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(s), size=(2000, len(s)))
    diffs = s[idx].sum(1) / c[idx].sum(1)
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def main():
    inv = inventory()
    leagues = list(inv)
    cache = os.path.join(os.environ.get("XG_CACHE", "/tmp"), f"xg_signal_{TAG}_cache.json")

    with Pool(6) as pool:
        sel = pool.map(selection, leagues)
    picks = {lg: pick(lg, kind, rows) for lg, kind, rows in sel}
    sel_rows = []
    for lg, p in picks.items():
        for cfgn, r in p["table"].iterrows():
            sel_rows.append({"league": lg, "signal_type": p["kind"], "config": cfgn,
                             "brier_half1": round(r[1], 5), "brier_half2": round(r[2], 5),
                             "chosen": cfgn == p["chosen"]})
    pd.DataFrame(sel_rows).to_csv(f"validation/xg_signal_{TAG}_selection.csv", index=False)

    # конфигурации за ЧАСТ Г
    eval_cfgs = {}
    for lg in leagues:
        cfgs = [None]
        chosen = picks[lg]["cfg"]
        if chosen:
            cfgs.append(chosen)
        if inv[lg].red_pct >= THRESH:
            base = dict(chosen) if chosen else {}
            base["red"] = True
            cfgs.append(base)
        eval_cfgs[lg] = cfgs

    detail = eval_rows()
    fixtures = defaultdict(dict)
    for d in detail:
        fixtures[d["league"]][d["fixture_id"]] = (d["home_team"], d["away_team"], d["match_date"])
    with Pool(6) as pool:
        rep = pool.map(replay, [(lg, fixtures[lg], eval_cfgs[lg]) for lg in leagues if fixtures[lg]])
    preds, missing = {}, {}
    for lg, out, miss in rep:
        preds.update(out)
        missing[lg] = miss

    # всеки ред: логнатото число, current, новото (без/с red)
    items = []
    for d in detail:
        lg = d["league"]
        names = [cfg_name(c) for c in eval_cfgs[lg]]
        row = dict(d, logged=d["ours"])
        ok = True
        for nm in names:
            p = preds.get((nm, d["fixture_id"]))
            if p is None:
                ok = False
                break
            row[nm] = float(p[d["code"]])
        if ok:
            row["_names"] = names
            items.append(row)

    ev = []
    for lg in leagues:
        it = [d for d in items if d["league"] == lg]
        if not it:
            continue
        rec = {"league": lg, "n": len(it), "matches": len({d["fixture_id"] for d in it}),
               "brier_market": brier_block(it, "market"), "brier_logged": brier_block(it, "logged")}
        for nm in it[0]["_names"]:
            rec[f"brier_{nm}"] = brier_block(it, nm)
            if nm != "current":
                lo, hi = paired_ci(it, nm, "current")
                rec[f"ci_{nm}"] = (lo, hi)
        ev.append(rec)

    with open(cache, "w") as fh:
        json.dump({"picks": {k: {kk: vv for kk, vv in v.items() if kk != "table"} for k, v in picks.items()},
                   "eval_cfgs": {k: v for k, v in eval_cfgs.items()},
                   "eval": ev, "missing": missing}, fh, default=str, indent=1)

    # решение по лига: най-добрата конфигурация на мачовете от ЧАСТ Г срещу current
    final = {}
    for rec in ev:
        lg = rec["league"]
        best, bb = "current", rec["brier_current"]
        for nm in [cfg_name(c) for c in eval_cfgs[lg]][1:]:
            if rec[f"brier_{nm}"] < bb:
                best, bb = nm, rec[f"brier_{nm}"]
        final[lg] = best
    cfg_by_name = {(lg, cfg_name(c)): c for lg in leagues for c in eval_cfgs[lg]}

    # обща равносметка: current навсякъде срещу "всичко ново" срещу "само където помага"
    for d in items:
        lg = d["league"]
        names = d["_names"]
        d["all_new"] = d[names[-1]] if len(names) > 1 else d["current"]
        d["final"] = d[final[lg]]
    tot = {"n": len(items), "matches": len({d["fixture_id"] for d in items}),
           "market": brier_block(items, "market"), "logged": brier_block(items, "logged"),
           "current": brier_block(items, "current"), "all_new": brier_block(items, "all_new"),
           "final": brier_block(items, "final")}
    tot["ci_all_new"] = paired_ci(items, "all_new", "current")
    tot["ci_final"] = paired_ci(items, "final", "current")

    # проверка на диапазона за финалните конфигурации
    to_check = [(lg, cfg_by_name[(lg, final[lg])]) for lg in final if final[lg] != "current"]
    with Pool(6) as pool:
        rng_res = dict(pool.map(range_check, to_check))

    ev_rows = []
    for rec in ev:
        r = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in rec.items() if not k.startswith("ci_")}
        for k, v in rec.items():
            if k.startswith("ci_"):
                r[k + "_low"], r[k + "_high"] = round(v[0], 5), round(v[1], 5)
        r["final"] = final[rec["league"]]
        ev_rows.append(r)
    pd.DataFrame(ev_rows).to_csv(f"validation/xg_signal_{TAG}_eval.csv", index=False)
    rr = []
    for lg, res in rng_res.items():
        for nm, (lo, hi, frac) in res.items():
            rr.append({"league": lg, "config": nm, "min_lambda": round(lo, 3), "max_lambda": round(hi, 3),
                       "share_outside_0.3_3.5": round(frac, 4)})
    pd.DataFrame(rr).to_csv(f"validation/xg_signal_{TAG}_range.csv", index=False)

    print(json.dumps({"final": final, "total": tot, "missing": {k: len(v) for k, v in missing.items()}},
                     default=str, indent=1))
    write_md(inv, picks, ev, final, tot, rr, missing, eval_cfgs)


def write_md(inv, picks, ev, final, tot, rr, missing, eval_cfgs):
    L = [f"# xG / удари като сигнал за силата на отборите - {TAG}", "",
         "ZADACHA_XG.md, части Б, В и Г. Скрипт: `validation/xg_signal_20260923.py` (методът е в",
         "docstring-а). Сурови числа: `_selection.csv`, `_eval.csv`, `_range.csv` до този файл.", "",
         "Brier = средна квадратна грешка на вероятността (по-малко = по-добре).", "",
         "## Важно за метода на ЧАСТ Г", "",
         "`model_vs_market.py` мери процентите, **записани** в predictions_log при публикуването.",
         "Нов модел не може да ги промени - пускането му наново след смяната на модела ще даде",
         "същите числа. Затова тук същите редове (същото пазарно число, същият изход) се",
         "преизчисляват walk-forward: за всеки мач моделът се учи само от мачове с по-ранна",
         "дата, веднъж със сегашната настройка (current) и веднъж с новата. Колоната",
         "„записано“ е числото от базовата линия (model_vs_market_baseline_20260923) за същите",
         "редове - за ориентир; сравнението преди/след е current срещу новото.", "",
         "## ЧАСТ Б - избор на сигнал (мачове преди 01.08.2026, две хронологични половини)", "",
         "| лига | вид по данни | най-добър на 1-ва половина | Brier 2-ра: current | Brier 2-ра: избран | избран | защо |",
         "|---|---|---|---|---|---|---|"]
    for lg, p in picks.items():
        t = p["table"]
        bf = p.get("best_first", "current")
        L.append(f"| {lg} | {p['kind']} | {bf} | {t.loc['current', 2]:.4f} | "
                 f"{t.loc[p['chosen'], 2]:.4f} | {p['chosen']} | {p['why']} |")
    L += ["", "Пълна таблица на всички тегла по лига: `validation/xg_signal_20260923_selection.csv`.", "",
          "## ЧАСТ В - червен картон x0.5", "",
          "Колоната red е попълнена >= 70% само в: " +
          ", ".join(f"{lg} ({inv[lg].red_pct}%)" for lg in inv if inv[lg].red_pct >= THRESH) +
          ". В останалите лиги API-то пази празно вместо 0 (виж data_inventory_20260923.md) -",
          "по буквата на задачата там не се прилага.", "",
          "## ЧАСТ Г - срещу пазара (същите редове, walk-forward)", "",
          "| лига | n | мачове | Brier пазар | записано | current | ново | ново+red | разлика ново−current (95% инт.) | остава |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for rec in ev:
        lg = rec["league"]
        names = [cfg_name(c) for c in eval_cfgs[lg]]
        new = [nm for nm in names[1:] if not nm.endswith("+red")]
        red = [nm for nm in names[1:] if nm.endswith("+red")]
        cell = lambda nm: f"{rec[f'brier_{nm}']:.4f} ({nm})" if nm else "—"  # noqa: E731
        main_new = new[0] if new else (red[0] if red else None)
        ci = ""
        if main_new:
            lo, hi = rec[f"ci_{main_new}"]
            ci = f"{rec[f'brier_{main_new}'] - rec['brier_current']:+.4f} [{lo:+.4f}, {hi:+.4f}]"
        L.append(f"| {lg} | {rec['n']} | {rec['matches']} | {rec['brier_market']:.4f} | {rec['brier_logged']:.4f} | "
                 f"{rec['brier_current']:.4f} | {cell(new[0]) if new else '—'} | {cell(red[0]) if red else '—'} | "
                 f"{ci or '—'} | **{final[lg]}** |")
    L += ["", "### Обща равносметка (всички лиги, без суров implied)", "",
          "| вариант | Brier наш | Brier пазар | разлика спрямо пазара | ново − current (95% инт.) |",
          "|---|---|---|---|---|",
          f"| записано (базова линия, същите редове) | {tot['logged']:.4f} | {tot['market']:.4f} | {tot['logged'] - tot['market']:+.4f} | — |",
          f"| current (walk-forward) | {tot['current']:.4f} | {tot['market']:.4f} | {tot['current'] - tot['market']:+.4f} | — |",
          f"| всичко ново навсякъде | {tot['all_new']:.4f} | {tot['market']:.4f} | {tot['all_new'] - tot['market']:+.4f} | "
          f"{tot['all_new'] - tot['current']:+.4f} [{tot['ci_all_new'][0]:+.4f}, {tot['ci_all_new'][1]:+.4f}] |",
          f"| ново само където помага | {tot['final']:.4f} | {tot['market']:.4f} | {tot['final'] - tot['market']:+.4f} | "
          f"{tot['final'] - tot['current']:+.4f} [{tot['ci_final'][0]:+.4f}, {tot['ci_final'][1]:+.4f}] |",
          "", f"n = {tot['n']} реда, {tot['matches']} мача. Отрицателна разлика = по-близо до изхода.", "",
          "„Само където помага“ е избрано по същите мачове, по които се мери - затова е",
          "оптимистично; честното число за цялата промяна е „всичко ново навсякъде“.", "",
          "## Проверка на очакваните голове (0.3 - 3.5)", "",
          "Модел от всички данни, всички двойки отбори, играли в лигата последните 365 дни.", "",
          "| лига | конфигурация | мин | макс | дял извън 0.3-3.5 |", "|---|---|---|---|---|"]
    for r in rr:
        L.append(f"| {r['league']} | {r['config']} | {r['min_lambda']} | {r['max_lambda']} | {100 * r['share_outside_0.3_3.5']:.2f}% |")
    miss = {k: len(v) for k, v in missing.items() if v}
    if miss:
        L += ["", f"Мачове без прогноза (отбор без история преди датата): {miss} - отпадат от всички варианти еднакво."]
    with open(f"validation/xg_signal_{TAG}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
