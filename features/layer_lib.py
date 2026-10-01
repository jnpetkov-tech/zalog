"""features/layer_lib.py - обучен слой отгоре на ядрото (ZADACHA_TABLICA, стъпка 3, 01.10.2026).

ИДЕЯ. Ядрото (football_lib: Dixon-Coles + контузии + xG смес + общ евро модел) дава очакваните голове lam (домакин) и mu (гост).
Слоят е градиентно усилено дърво (LightGBM), което учи КОРЕКЦИЯ на очакваните голове: цел - вкараните голове на отбора, Поасонова
функция на загубата, НАЧАЛНА стойност log(ядро) -> новото очакване = ядро * exp(s * изход_на_дърветата). Дървета, които не намерят
сигнал, оставят изхода ~0 -> нова оценка = ядрото. Всичката допълнителна информация влиза само през таблицата с признаци
(features/features_table.csv.gz). Пазарът НЕ е признак и НЕ е в обучението.

ПОСТАНОВКА. Два реда на мач ("собствен отбор" / "противник"): за домакина own_* = h_*, opp_* = a_*; за госта - обратно; is_home;
ядрото own_lam/opp_lam. Един модел за двете страни (повече данни, симетрия).

WALK-FORWARD. За всяка календарна седмица (понеделник-неделя) слоят се учи ВЕДНЪЖ от всички редове на мачове с дата < понеделника
на седмицата (включително мачовете преди тестовия период) и предсказва мачовете на седмицата. Никога от бъдещ мач.

ВЕРОЯТНОСТИ. От (lam', mu', rho на ядрото) със същата матрица като живия код: Поасон + Dixon-Coles + зависимост на резултата
(football_lib.SCORE_DEP_*) -> 11-те изхода на мерилото (1x2, над/под 2.5, двата вкарват, отборни голове 1.5).
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

import backtest_full as bf  # noqa: E402
import final_a_20260924 as fa  # noqa: E402
import football_lib as fl  # noqa: E402
import razpredelenie_b_20260923 as rb  # noqa: E402

TABLE = os.path.join(ROOT, "features", "features_table.csv.gz")
EVAL_START = "2024-08-28"      # началото на мерилото (11 823 мача)
EARLY_END = "2025-09-23"       # ранна половина: дата < това; късна: >= това (като final_b/final_v)
NEW_AFTER = "2026-09-21"       # мачовете след тази дата (последният мач на мерилото) са "новите изтеглени"
BENCH = os.path.join(ROOT, "validation", "final_v_20260924_matches.csv")
CODES = bf.CODES
GROUP_OF = bf.GROUPS
GROUPS = ["1x2", "ou25", "btts", "team_total"]

# ----------------------------------------------------------------------------------------------- признаци по блокове (имена БЕЗ h_/a_)
F_CAL = ["rest_days", "n_last7", "n_last14", "euro_prev4", "euro_next4"]
F_STAND = ["rank", "ppg", "gd_pg", "season_frac", "pts_to_first", "pts_to_top4", "pts_over_drop", "games_left"]
F_FORM = ["pts5", "gf5", "ga5", "pts10", "gf10", "ga10", "n_ev10", "gf_late_share10", "gf_early_share10", "ga_late_share10",
          "ga_early_share10", "lead_share10", "trail_share10", "first_goal_rate10", "red_for10", "red_against10",
          "pen_for10", "pen_against10"]
F_SHOTS = ["n_st5", "sh_for5", "sh_ag5", "sot_for5", "sot_ag5", "xg_for5", "xg_ag5", "n_st10", "sh_for10", "sh_ag10",
           "sot_for10", "sot_ag10", "xg_for10", "xg_ag10", "box_for10", "box_ag10", "cor_for10", "pos_for10"]
F_SQUAD = ["n_usual", "n_absent", "absent_weight", "gk_absent", "def_absent", "mid_absent", "fwd_absent",
           "absent_involve_share", "xi_changes", "xi_experience", "coach_new", "coach_tenure_days", "inj_missing", "inj_quest"]
SHARED_D = ["ref_n", "ref_yellow", "ref_red", "ref_fouls", "ref_pens", "ref_goals", "ref_home_win", "kick_hour", "weekday",
            "month", "round_no"]
BLOCKS = {"A": F_CAL + F_STAND + F_FORM, "B": F_SHOTS, "C": F_SQUAD}
FEATURE_SETS = {"A": ["A"], "AB": ["A", "B"], "ABC": ["A", "B", "C"], "ABCD": ["A", "B", "C", "D"]}


def feature_columns(fset):
    own = []
    for b in FEATURE_SETS[fset]:
        if b in BLOCKS:
            own += BLOCKS[b]
    cols = ["own_lam", "opp_lam", "lam_total", "rho", "is_home", "is_cup", "league_code", "n_teams"]
    cols += [f"own_{c}" for c in own] + [f"opp_{c}" for c in own]
    cols += ["rest_diff_own"] if "A" in FEATURE_SETS[fset] else []
    if "D" in FEATURE_SETS[fset]:
        cols += SHARED_D
    return cols


# ----------------------------------------------------------------------------------------------- данни
def load_table():
    t = pd.read_csv(TABLE, float_precision="round_trip")
    t["d"] = pd.to_datetime(t["date"])
    t["week"] = t["d"] - pd.to_timedelta(t["d"].dt.weekday, unit="D")
    t = t.sort_values(["d", "fixture_id"]).reset_index(drop=True)
    t["league_code"] = t["league"].map({l: i for i, l in enumerate(sorted(t["league"].unique()))}).astype(float)
    bench = set(pd.read_csv(BENCH, usecols=["fixture_id"])["fixture_id"])
    # ТЕСТОВ НАБОР = мачовете на мерилото (11 823) + новите след 21.09.2026; останалите редове са само за обучение
    t["is_eval"] = t["fixture_id"].isin(bench) | (t["date"] > NEW_AFTER)
    return t.copy()


def to_long(t):
    """Два реда на мач (домакин, гост) в perspective own/opp. Индексът 'row' сочи към реда в t."""
    side_cols = sorted({c[2:] for c in t.columns if c.startswith("h_")})
    shared = ["rho", "is_cup", "league_code", "n_teams"] + SHARED_D
    out = []
    for side, other in (("h", "a"), ("a", "h")):
        d = pd.DataFrame({"row": np.arange(len(t)), "side": side, "week": t["week"].to_numpy(), "d": t["d"].to_numpy()})
        d["own_lam"] = (t["lam"] if side == "h" else t["mu"]).to_numpy()
        d["opp_lam"] = (t["mu"] if side == "h" else t["lam"]).to_numpy()
        d["lam_total"] = t["lam"].to_numpy() + t["mu"].to_numpy()
        d["is_home"] = 1.0 if side == "h" else 0.0
        d["y"] = (t["hg"] if side == "h" else t["ag"]).to_numpy(float)
        for c in shared:
            d[c] = t[c].to_numpy(float)
        for c in side_cols:
            d[f"own_{c}"] = t[f"{side}_{c}"].to_numpy(float)
            d[f"opp_{c}"] = t[f"{other}_{c}"].to_numpy(float)
        d["rest_diff_own"] = d["own_rest_days"] - d["opp_rest_days"]
        out.append(d)
    return pd.concat(out, ignore_index=True)


# ----------------------------------------------------------------------------------------------- слой
def lgb_params(cfg):
    return {"objective": "poisson", "learning_rate": cfg.get("lr", 0.03), "num_leaves": 2 ** cfg["depth"],
            "max_depth": cfg["depth"], "min_child_samples": cfg["min_child"], "lambda_l2": cfg["l2"],
            "feature_fraction": 0.7, "bagging_fraction": 0.8, "bagging_freq": 1, "verbose": -1, "num_threads": 1,
            "seed": 42, "deterministic": True, "force_row_wise": True, "max_bin": 63}


def walk_forward(long, t, cfg, start, end=None, want_importance=False):
    """Седмично префитване. cfg: depth, min_child, l2, n_list (напр. [50,100,200]), fset. Една тренировка с max(n_list) дървета дава
    прогнози за всеки брой дървета (num_iteration). Предсказват се само тестовите мачове (is_eval) със start <= дата < end.
    Връща {n: (raw_h, raw_a)} (NaN за непредсказаните) и (по желание) важност на признаците (gain, нормирана по фит)."""
    import lightgbm as lgb
    cols = feature_columns(cfg["fset"])
    cat = ["league_code"]
    X = long[cols].to_numpy(np.float32)
    y = long["y"].to_numpy()
    init = np.log(np.maximum(long["own_lam"].to_numpy(), 1e-6))
    dts = long["d"].to_numpy()
    wk = long["week"].to_numpy()
    ev = np.concatenate([t["is_eval"].to_numpy(), t["is_eval"].to_numpy()])
    n_list = list(cfg["n_list"])
    raw = {n: np.full(len(long), np.nan) for n in n_list}
    imp = np.zeros(len(cols))
    n_fits = 0
    in_win = (dts >= np.datetime64(start)) & ((dts < np.datetime64(end)) if end else True) & ev
    weeks = sorted(np.unique(wk[in_win]))
    for w in weeks:
        tr = dts < w
        te = (wk == w) & in_win
        if tr.sum() < 3000 or not te.any():
            continue
        ds = lgb.Dataset(X[tr], label=y[tr], init_score=init[tr], feature_name=cols, categorical_feature=cat, free_raw_data=True)
        bst = lgb.train(lgb_params(cfg), ds, num_boost_round=max(n_list))
        for n in n_list:
            raw[n][te] = bst.predict(X[te], raw_score=True, num_iteration=n)
        if want_importance:
            g = bst.feature_importance("gain")
            imp += g / g.sum() if g.sum() > 0 else g
            n_fits += 1
    n = len(t)
    res = {k: (v[:n], v[n:]) for k, v in raw.items()}
    return res, (pd.Series(imp / max(n_fits, 1), index=cols) if want_importance else None)


def corrected(t, rh, ra, shrink):
    lam = t["lam"].to_numpy() * np.exp(shrink * rh)
    mu = t["mu"].to_numpy() * np.exp(shrink * ra)
    return lam, mu


# ----------------------------------------------------------------------------------------------- вероятности и мерки
def probs(lam, mu, rho):
    pm = fa.shift(rb.matrices(np.asarray(lam, float), np.asarray(mu, float), np.asarray(rho, float), "poisson", 0),
                  np.asarray(lam, float), np.asarray(mu, float), fl.SCORE_DEP_F0, fl.SCORE_DEP_F1)
    return rb.market_probs(pm)


def y_matrix(hg, ag):
    hg, ag = np.asarray(hg), np.asarray(ag)
    o = {"home_win": hg > ag, "draw": hg == ag, "away_win": hg < ag, "over25": hg + ag > 2.5, "btts_yes": (hg >= 1) & (ag >= 1),
         "home_over15": hg >= 2, "away_over15": ag >= 2}
    o["under25"] = ~o["over25"]
    o["btts_no"] = ~o["btts_yes"]
    o["home_under15"] = ~o["home_over15"]
    o["away_under15"] = ~o["away_over15"]
    return np.column_stack([o[c] for c in CODES]).astype(float)


def brier_match(P, Y):
    """По мач: средно (p-y)^2 по 11-те изхода (същата дефиниция като мерилото)."""
    return ((P.to_numpy() - Y) ** 2).mean(1)


def brier_group(P, Y):
    out = {}
    for g in GROUPS:
        idx = [i for i, c in enumerate(CODES) if GROUP_OF[c] == g]
        out[g] = ((P.to_numpy()[:, idx] - Y[:, idx]) ** 2).mean(1)
    return out


def logloss_match(P, Y):
    """По мач: (log-loss 1X2, над/под 2.5, двата вкарват) - отрицателен логаритъм от вероятността на реалния изход."""
    p = P.to_numpy()
    eps = 1e-12
    i = {c: k for k, c in enumerate(CODES)}
    l1 = -np.log(np.maximum((p[:, [i["home_win"], i["draw"], i["away_win"]]] * Y[:, [i["home_win"], i["draw"], i["away_win"]]]).sum(1), eps))
    l2 = -np.log(np.maximum((p[:, [i["over25"], i["under25"]]] * Y[:, [i["over25"], i["under25"]]]).sum(1), eps))
    l3 = -np.log(np.maximum((p[:, [i["btts_yes"], i["btts_no"]]] * Y[:, [i["btts_yes"], i["btts_no"]]]).sum(1), eps))
    return {"1x2": l1, "ou25": l2, "btts": l3}


def calib_base(Y_early):
    return {c: Y_early[:, i].mean() for i, c in enumerate(CODES)}


def calib_coef(P, Y, base):
    """a = sum (p-b)(y-b) / sum (p-b)^2 по група (b - честотата на изхода на ранната половина). Рамка 0.9-1.1."""
    a = {}
    p = P.to_numpy()
    for g in GROUPS:
        num = den = 0.0
        for i, c in enumerate(CODES):
            if GROUP_OF[c] != g:
                continue
            d = p[:, i] - base[c]
            num += (d * (Y[:, i] - base[c])).sum()
            den += (d * d).sum()
        a[g] = num / den
    return a


def apply_cal(P, a, base):
    out = P.copy()
    for c in CODES:
        out[c] = base[c] + a[GROUP_OF[c]] * (P[c] - base[c])
    return out


def boot_ci(x, n=2000, seed=42):
    """95% интервал на средното на x (по мач) с bootstrap."""
    rng = np.random.default_rng(seed)
    x = np.asarray(x)
    idx = rng.integers(0, len(x), size=(n, len(x)))
    m = x[idx].mean(1)
    return float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))
