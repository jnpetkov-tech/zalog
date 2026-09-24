"""
validation/nacionalni2_model_20260924.py - ZADACHA_NACIONALNI2.md, ЧАСТ В (24.09.2026).
Модел за националните отбори + walk-forward проверка по резултатите. Само измерване -
football_lib.py, prediction_policy.py и живият код НЕ се пипат.

ДАННИ: nationals_merged_full.csv (ЧАСТ Б; ако липсва - копието
validation/nacionalni2_istoriya_20260924.csv): 5-те турнира (ЛН, св. квал. Европа,
квал. Евро, Евро, Световно) + сеньорски приятелски между национални отбори, 2022-2026.
Резултатът е 90-минутният (без продълженията).

МОДЕЛ (един общ, по идеята на fl.fit_euro_model - отборът е държавата, учи се от всички
свои мачове във всички турнири):
    log lam = c[тип] + H[тип]*домакин + атака_дом - защита_гост
    log mu  = c[тип] + атака_гост - защита_дом
  тип = официален / приятелски (приятелските - отделно ниво и домакинско предимство);
  домакин = 0 на финалите (Евро, Световно), освен за домакина(ите) на турнира.
  Dixon-Coles rho (както fit_goals_model) + fl.adjust_matrix при смятането на пазарите
  (същата матрица като на живо). Точен градиент, L-BFGS-B.
  Трите разлики спрямо клубния модел, които задачата иска да се обмислят:
  1) забрава по БРОЙ мачове: тегло на мача = exp(-k * (n_дом + n_гост)/2), n = колко мача
     е изиграл отборът СЛЕД него до момента на прогнозата (сравнено и с календарна забрава);
  2) свиване към средата: сила s и темпо t = (атака -+ защита)/2 с регуларизация
     2*(reg + extra/(тегло_на_отбора + 1))*(s^2 + tempo_mult*t^2) - както fit_goals_model;
     отбор с малко мачове се дърпа силно към средния;
  3) разгромите - мерят се отделно (т. РАЗГРОМИ по-долу).
  w_fr - тегло на приятелските мачове (данни за обучение, по-малко тегло).

ПРОВЕРКА (walk-forward): прогнозират се официалните мачове (без приятелските) от
2023-01-01 нататък; моделът за всяка седмица (от понеделник) се учи САМО от мачовете преди
този понеделник (префитване всяка седмица с мачове - т.е. поне веднъж на прозорец).
  Настройките се избират САМО на ранната половина (дата < 2025-01-01, 2023-2024) по общ
  Brier (1X2 + над/под 2.5 + двата отбора); късната половина (2025-2026) е чиста проверка.
  Brier - за всеки изход (p-y)^2, средно по кодовете на групата (както backtest_full.py).
  Коефициент на калибрация (calibration_fit метод): a = сума (p-b)(y-b) / сума (p-b)^2,
  b - честотата на изхода в обучаващите данни преди 2023 (официалните мачове 2022).
  ОТПРАВНА ТОЧКА: само домакинско предимство и среден гол - lam/mu = средните голове на
  домакин/гост в обучаващите мачове от същия вид (с домакин / неутрален), същата седмица,
  същата матрица (Поасон, без rho). Разлика в Brier - bootstrap по мач (2000, seed 42).
  КРИТЕРИЙ: a за 1X2 в 0.9-1.1 и Brier значимо по-добър от отправната точка.

РАЗГРОМИ: средно очаквани голове срещу реални, P(разлика >= 3) модел срещу реално, по
турнир и по силата на фаворита (очаквана разлика в головете).

Изход: validation/nacionalni2_model_20260924.md (числата - вмъкват се в доклада
nacionalni_model_20260924.md), _grid.csv (всички настройки), _matches.csv (прогнозите по мач).
Употреба: venv/bin/python3 validation/nacionalni2_model_20260924.py
"""
import os
import sys

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
import itertools  # noqa: E402
from multiprocessing import Pool  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import minimize  # noqa: E402
from scipy.stats import poisson  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import football_lib as fl  # noqa: E402

TAG = "20260924"
OUT = f"validation/nacionalni2_model_{TAG}"
EVAL_FROM = pd.Timestamp("2023-01-01")
SPLIT = pd.Timestamp("2025-01-01")
FINALS = {1, 4}
FRIENDLY = 10
HOSTS = {(1, 2022): {"Qatar"}, (4, 2024): {"Germany"}, (1, 2026): {"USA", "Mexico", "Canada"}}
LNAME = {5: "Лига на нациите", 32: "Св. квал. Европа", 960: "Квал. Евро", 4: "Евро", 1: "Световно"}
MAX_G = 10
G = np.arange(MAX_G)
GX, GY = np.meshgrid(G, G, indexing="ij")
CODES = ["home_win", "draw", "away_win", "over25", "under25", "btts_yes", "btts_no"]
GROUPS = {"1x2": ["home_win", "draw", "away_win"], "ou25": ["over25", "under25"], "btts": ["btts_yes", "btts_no"]}


def load():
    path = "nationals_merged_full.csv"
    if not os.path.exists(path):
        path = "validation/nacionalni2_istoriya_20260924.csv"
    d = pd.read_csv(path)
    d = d.dropna(subset=["home_goals", "away_goals"]).copy()
    d["date"] = pd.to_datetime(d["date"], utc=True).dt.tz_localize(None)
    d = d[d["date"] >= "2022-01-01"].sort_values("date").reset_index(drop=True)
    d["friendly"] = (d["league_id"] == FRIENDLY).astype(int)
    host = [(lid not in FINALS) or (h in HOSTS.get((lid, s), set()))
            for lid, s, h in zip(d["league_id"], d["season"], d["home_team"])]
    d["home_flag"] = np.array(host, dtype=float)
    d["hg"] = d["home_goals"].astype(int)
    d["ag"] = d["away_goals"].astype(int)
    return d


class Index:
    def __init__(self, d):
        teams = sorted(set(d["home_id"]) | set(d["away_id"]))
        self.ti = {t: i for i, t in enumerate(teams)}
        self.nt = len(teams)


def match_weights(tr, ref_date, forget, k):
    """forget = 'count': exp(-k*(n_дом+n_гост)/2), n = мачове на отбора след този (до ref_date);
    'days': exp(-k*дни)."""
    if forget == "days":
        return np.exp(-k * (ref_date - tr["date"]).dt.days.to_numpy())
    n = len(tr)
    h, a = tr["h"].to_numpy(), tr["a"].to_numpy()
    # за всеки отбор: мачовете му по време; брой по-късни = общо - позиция - 1
    after_h, after_a = np.zeros(n), np.zeros(n)
    teams = np.concatenate([h, a])
    rows = np.concatenate([np.arange(n), np.arange(n)])
    side = np.concatenate([np.zeros(n, int), np.ones(n, int)])
    order = np.lexsort((rows, teams))      # по отбор, после по ред (= по дата)
    t_sorted = teams[order]
    start = np.r_[0, np.flatnonzero(np.diff(t_sorted)) + 1]
    sizes = np.diff(np.r_[start, len(t_sorted)])
    pos = np.arange(len(t_sorted)) - np.repeat(start, sizes)
    later = np.repeat(sizes, sizes) - pos - 1
    r, s = rows[order], side[order]
    after_h[r[s == 0]] = later[s == 0]
    after_a[r[s == 1]] = later[s == 1]
    return np.exp(-k * (after_h + after_a) / 2)


def fit(tr, ref_date, nt, cfg):
    """tr: обучаващи мачове (колони h, a - индекси; hg, ag; friendly; home_flag; date)."""
    h, a = tr["h"].to_numpy(), tr["a"].to_numpy()
    hg, ag = tr["hg"].to_numpy(float), tr["ag"].to_numpy(float)
    fr = tr["friendly"].to_numpy()
    hf = tr["home_flag"].to_numpy()
    w = match_weights(tr, ref_date, cfg["forget"], cfg["k"])
    w = np.where(fr == 1, w * cfg["w_fr"], w)
    tw = np.zeros(nt)
    np.add.at(tw, h, w)
    np.add.at(tw, a, w)
    reg_vec = cfg["reg"] + cfg["extra"] / (tw + 1.0)
    km = cfg["tempo_mult"]
    o_a, o_d, o_c, o_H, i_r = 0, nt, 2 * nt, 2 * nt + 2, 2 * nt + 4
    npar = i_r + 1
    m00, m01 = (hg == 0) & (ag == 0), (hg == 0) & (ag == 1)
    m10, m11 = (hg == 1) & (ag == 0), (hg == 1) & (ag == 1)

    def f(p):
        att, de, c, H, rho = p[o_a:o_d], p[o_d:o_c], p[o_c:o_H], p[o_H:i_r], p[i_r]
        eh = c[fr] + H[fr] * hf + att[h] - de[a]
        ea = c[fr] + att[a] - de[h]
        lam, mu = np.exp(eh), np.exp(ea)
        ll = w * (hg * eh - lam + ag * ea - mu)
        glam, gmu = w * (hg - lam), w * (ag - mu)
        tau = np.ones_like(lam)
        tau[m00] = 1 - lam[m00] * mu[m00] * rho
        tau[m01] = 1 + lam[m01] * rho
        tau[m10] = 1 + mu[m10] * rho
        tau[m11] = 1 - rho
        tc = np.clip(tau, 1e-10, None)
        ll = ll + w * np.log(tc)
        ok = tau > 1e-10
        g = np.zeros_like(lam)
        s = m00 & ok
        glam[s] += w[s] * (-lam[s] * mu[s] * rho) / tc[s]
        gmu[s] += w[s] * (-lam[s] * mu[s] * rho) / tc[s]
        g[s] = -lam[s] * mu[s] / tc[s]
        s = m01 & ok
        glam[s] += w[s] * lam[s] * rho / tc[s]
        g[s] = lam[s] / tc[s]
        s = m10 & ok
        gmu[s] += w[s] * mu[s] * rho / tc[s]
        g[s] = mu[s] / tc[s]
        s = m11 & ok
        g[s] = -1 / tc[s]
        ss, tt = (att + de) / 2, (att - de) / 2
        val = -ll.sum() + np.sum(2 * reg_vec * (ss ** 2 + km * tt ** 2))
        gr = np.zeros(npar)
        np.add.at(gr, o_a + h, -glam)
        np.add.at(gr, o_a + a, -gmu)
        np.add.at(gr, o_d + a, glam)
        np.add.at(gr, o_d + h, gmu)
        gr[o_a:o_d] += 2 * reg_vec * (ss + km * tt)
        gr[o_d:o_c] += 2 * reg_vec * (ss - km * tt)
        np.add.at(gr, o_c + fr, -(glam + gmu))
        np.add.at(gr, o_H + fr, -glam * hf)
        gr[i_r] = -(w * g).sum()
        return val, gr

    x0 = np.zeros(npar)
    x0[o_c:o_H] = np.log(max(hg.mean() + ag.mean(), 0.1) / 2)
    bounds = [(None, None)] * (npar - 1) + [(-0.9, 0.9)]
    if cfg.get("_numgrad"):   # само за проверка на градиента
        r = minimize(lambda p: f(p)[0], x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 5000})
    else:
        r = minimize(f, x0, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 5000})
    p = r.x
    return {"att": p[o_a:o_d], "de": p[o_d:o_c], "c": p[o_c:o_H], "H": p[o_H:i_r], "rho": float(p[i_r]),
            "tw": tw}


def probs(lam, mu, rho, adjust=True):
    """(N,) -> DataFrame с CODES, през fl.adjust_matrix (DC + зависимостта) - матрицата на живия код."""
    out = []
    for l_, m_, r_ in zip(lam, mu, np.broadcast_to(rho, np.shape(lam))):
        pm = np.outer(poisson.pmf(G, l_), poisson.pmf(G, m_))
        if adjust:
            pm = fl.adjust_matrix(pm, l_, m_, float(r_))
        out.append(pm)
    pm = np.array(out)
    P = {"home_win": pm[:, GX > GY].sum(1), "draw": pm[:, GX == GY].sum(1), "away_win": pm[:, GX < GY].sum(1),
         "over25": pm[:, GX + GY > 2.5].sum(1), "btts_yes": pm[:, (GX >= 1) & (GY >= 1)].sum(1),
         "big3": pm[:, np.abs(GX - GY) >= 3].sum(1)}
    P["under25"] = 1 - P["over25"]
    P["btts_no"] = 1 - P["btts_yes"]
    return pd.DataFrame(P)


def outcomes(hg, ag):
    Y = pd.DataFrame({"home_win": hg > ag, "draw": hg == ag, "away_win": hg < ag, "over25": hg + ag > 2.5,
                      "btts_yes": (hg >= 1) & (ag >= 1)}).astype(float)
    Y["under25"] = 1 - Y["over25"]
    Y["btts_no"] = 1 - Y["btts_yes"]
    return Y[CODES]


def walk_forward(d, cfg):
    """Прогнозите за официалните мачове от EVAL_FROM, седмично префитване."""
    ix = Index(d)
    d = d.assign(h=d["home_id"].map(ix.ti), a=d["away_id"].map(ix.ti))
    ev = d[(d["date"] >= EVAL_FROM) & (d["friendly"] == 0)].copy()
    ev["week"] = ev["date"].dt.to_period("W-SUN").dt.start_time
    parts = []
    for wk, grp in ev.groupby("week"):
        tr = d[d["date"] < wk]
        m = fit(tr, wk, ix.nt, cfg)
        fr = grp["friendly"].to_numpy()
        hf = grp["home_flag"].to_numpy()
        lam = np.exp(m["c"][fr] + m["H"][fr] * hf + m["att"][grp["h"]] - m["de"][grp["a"]])
        mu = np.exp(m["c"][fr] + m["att"][grp["a"]] - m["de"][grp["h"]])
        # отправна точка: средните голове на домакин/гост в официалните обучаващи мачове от същия вид
        off = tr[tr["friendly"] == 0]
        bl_l, bl_m = np.empty(len(grp)), np.empty(len(grp))
        for flag in (0.0, 1.0):
            sub = off[off["home_flag"] == flag]
            if len(sub) < 30:
                sub = off
            s = hf == flag
            bl_l[s], bl_m[s] = sub["hg"].mean(), sub["ag"].mean()
        # колко тегло има отборът в обучението (за "малко мачове")
        n_h = np.array([((tr["h"] == i) | (tr["a"] == i)).sum() for i in grp["h"]])
        n_a = np.array([((tr["h"] == i) | (tr["a"] == i)).sum() for i in grp["a"]])
        parts.append(pd.DataFrame({"fixture_id": grp["fixture_id"].to_numpy(), "lam": lam, "mu": mu,
                                   "rho": m["rho"], "bl_lam": bl_l, "bl_mu": bl_m, "n_h": n_h, "n_a": n_a}))
    out = ev.merge(pd.concat(parts), on="fixture_id")
    return out


def score(out, b):
    """Brier по група и общо, коефициент a по група (b - базовите честоти)."""
    P = probs(out["lam"].to_numpy(), out["mu"].to_numpy(), out["rho"].to_numpy())
    Y = outcomes(out["hg"].to_numpy(), out["ag"].to_numpy())
    sq = (P[CODES].to_numpy() - Y.to_numpy()) ** 2
    return P, Y, sq


def calib_a(P, Y, b, codes, mask):
    num = den = 0.0
    for c in codes:
        dd = P.loc[mask, c].to_numpy() - b[c]
        num += (dd * (Y.loc[mask, c].to_numpy() - b[c])).sum()
        den += (dd * dd).sum()
    return num / den


def a_ci(P, Y, b, codes, mask, B=2000, seed=42):
    """95% bootstrap интервал (по мач) за коефициента a."""
    idx = np.flatnonzero(mask)
    num = np.zeros(len(P))
    den = np.zeros(len(P))
    for c in codes:
        dd = P[c].to_numpy() - b[c]
        num += dd * (Y[c].to_numpy() - b[c])
        den += dd * dd
    rng = np.random.default_rng(seed)
    bs = rng.choice(idx, size=(B, len(idx)))
    v = num[bs].sum(1) / den[bs].sum(1)
    return f"{np.percentile(v, 2.5):.2f}-{np.percentile(v, 97.5):.2f}"


def brier_group(sq, mask, codes):
    idx = [CODES.index(c) for c in codes]
    return sq[mask][:, idx].mean()


def grid_job(cfg):
    d = load()
    out = walk_forward(d, cfg)
    P, Y, sq = score(out, None)
    early = (out["date"] < SPLIT).to_numpy()
    late = ~early
    pre = d[(d["date"] < EVAL_FROM) & (d["friendly"] == 0)]
    Ypre = outcomes(pre["hg"].to_numpy(), pre["ag"].to_numpy())
    b = {c: Ypre[c].mean() for c in CODES}
    return {**cfg, "brier_early": sq[early].mean(), "brier_late": sq[late].mean(),
            "b1x2_early": brier_group(sq, early, GROUPS["1x2"]), "b1x2_late": brier_group(sq, late, GROUPS["1x2"]),
            "a1x2_early": calib_a(P, Y, b, GROUPS["1x2"], early), "a1x2_late": calib_a(P, Y, b, GROUPS["1x2"], late),
            "a_ou25_early": calib_a(P, Y, b, GROUPS["ou25"], early), "a_ou25_late": calib_a(P, Y, b, GROUPS["ou25"], late)}


# Мрежата е разширявана два пъти, защото изборът падаше на ръба ѝ - тук са и трите заедно
# (всичките им редове са в _grid.csv, колона "мрежа"):
#  1) reg 1/3, extra 5/15/30, k 0-0.04, w_fr 0.3/0.6/1, tempo 1/5;
#  2) reg 0.1-1, extra 0/2/5, w_fr 0.6/1, tempo 1/2/5;
#  3) още по-слабо свиване на силата (reg 0.03) и по-силно на темпото (tempo до 50).
def _grid(n, forgets, regs, extras, wfrs, tempos):
    return [dict(forget=f, k=k, reg=r, extra=e, w_fr=wf, tempo_mult=tm, grid=n)
            for f, ks in forgets for k, r, e, wf, tm in itertools.product(ks, regs, extras, wfrs, tempos)]


GRID = (_grid(1, (("count", (0.0, 0.01, 0.02, 0.04)), ("days", (0.0009, 0.0018))), (1.0, 3.0), (5.0, 15.0, 30.0),
              (0.3, 0.6, 1.0), (1.0, 5.0))
        + _grid(2, (("count", (0.0, 0.005, 0.01, 0.02)), ("days", (0.0005, 0.0009))), (0.1, 0.3, 0.5, 1.0),
                (0.0, 2.0, 5.0), (0.6, 1.0), (1.0, 2.0, 5.0))
        + _grid(3, (("count", (0.0, 0.005, 0.01)), ("days", (0.0005,))), (0.03, 0.1, 0.3), (0.0, 2.0), (0.6, 1.0),
                (5.0, 10.0, 20.0, 50.0)))


def boot_ci(dvec, seed=42, B=2000):
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(dvec), size=(B, len(dvec)))
    v = dvec[idx].mean(1)
    return float(dvec.mean()), float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def main():
    d = load()
    with Pool(14) as pool:
        rows = pool.map(grid_job, GRID)
    grid = pd.DataFrame(rows).sort_values("brier_early")
    grid.round(6).to_csv(f"{OUT}_grid.csv", index=False)
    best = grid.iloc[0].to_dict()
    cfg = {k: best[k] for k in ("forget", "k", "reg", "extra", "w_fr", "tempo_mult")}
    # най-добрата с календарна забрава - за сравнение "по брой срещу по календар"
    best_days = grid[grid["forget"] == "days"].iloc[0].to_dict()
    cfg_days = {k: best_days[k] for k in cfg}
    out = walk_forward(d, cfg)
    P, Y, sq = score(out, None)
    PB = probs(out["bl_lam"].to_numpy(), out["bl_mu"].to_numpy(), np.zeros(len(out)), adjust=False)
    sqb = (PB[CODES].to_numpy() - Y.to_numpy()) ** 2
    # базови честоти: официалните мачове преди EVAL_FROM
    pre = d[(d["date"] < EVAL_FROM) & (d["friendly"] == 0)]
    Ypre = outcomes(pre["hg"].to_numpy(), pre["ag"].to_numpy())
    b = {c: Ypre[c].mean() for c in CODES}

    masks = {"всички (2023-2026)": np.ones(len(out), bool),
             "ранна (2023-2024, избор)": (out["date"] < SPLIT).to_numpy(),
             "късна (2025-2026, проверка)": (out["date"] >= SPLIT).to_numpy()}
    res = []
    for mname, mk in masks.items():
        for g, codes in list(GROUPS.items()) + [("общо", CODES)]:
            bm, bb = brier_group(sq, mk, codes), brier_group(sqb, mk, codes)
            idx = [CODES.index(c) for c in codes]
            diff = sq[mk][:, idx].mean(1) - sqb[mk][:, idx].mean(1)
            m_, lo, hi = boot_ci(diff)
            res.append({"извадка": mname, "група": g, "n": int(mk.sum()), "brier_model": round(bm, 5),
                        "brier_baseline": round(bb, 5), "разлика": round(m_, 5), "ci_lo": round(lo, 5),
                        "ci_hi": round(hi, 5), "значимо": hi < 0 or lo > 0,
                        "a_model": round(calib_a(P, Y, b, codes, mk), 3),
                        "a_ci": a_ci(P, Y, b, codes, mk),
                        "голове_реално": round((out.loc[mk, "hg"] + out.loc[mk, "ag"]).mean(), 3),
                        "голове_модел": round((out.loc[mk, "lam"] + out.loc[mk, "mu"]).mean(), 3),
                        "a_baseline": round(calib_a(PB, Y, b, codes, mk), 3) if g != "общо" else None})
    res = pd.DataFrame(res)
    res.to_csv(f"{OUT}.csv", index=False)

    # по турнир (всички години)
    by_t = []
    for lid, grp in out.groupby("league_id"):
        mk = (out["league_id"] == lid).to_numpy()
        by_t.append({"турнир": LNAME.get(lid, lid), "n": int(mk.sum()),
                     "brier_1x2": round(brier_group(sq, mk, GROUPS["1x2"]), 4),
                     "brier_1x2_baseline": round(brier_group(sqb, mk, GROUPS["1x2"]), 4),
                     "a_1x2": round(calib_a(P, Y, b, GROUPS["1x2"], mk), 3),
                     "голове_реално": round((out.loc[mk, "hg"] + out.loc[mk, "ag"]).mean(), 2),
                     "голове_модел": round((out.loc[mk, "lam"] + out.loc[mk, "mu"]).mean(), 2),
                     "разгром3+_реално_%": round(100 * ((out.loc[mk, "hg"] - out.loc[mk, "ag"]).abs() >= 3).mean(), 1),
                     "разгром3+_модел_%": round(100 * P.loc[mk, "big3"].mean(), 1)})
    by_t = pd.DataFrame(by_t)

    # разгроми по силата на фаворита (очаквана разлика в головете)
    exp_diff = (out["lam"] - out["mu"]).abs()
    bins = [0, 0.5, 1.0, 1.5, 2.0, 2.5, 10]
    cat = pd.cut(exp_diff, bins, right=False)
    real_big = ((out["hg"] - out["ag"]).abs() >= 3).astype(float)
    fav_home = out["lam"] >= out["mu"]
    fav_goals = np.where(fav_home, out["hg"], out["ag"])
    fav_exp = np.where(fav_home, out["lam"], out["mu"])
    dog_goals = np.where(fav_home, out["ag"], out["hg"])
    dog_exp = np.where(fav_home, out["mu"], out["lam"])
    by_s = pd.DataFrame({"cat": cat.astype(str), "real": real_big, "model": P["big3"],
                         "fg": fav_goals, "fe": fav_exp, "dg": dog_goals, "de": dog_exp,
                         "tot": out["hg"] + out["ag"], "tote": out["lam"] + out["mu"]}) \
        .groupby("cat", sort=False).agg(n=("real", "size"), реално_3плюс=("real", "mean"),
                                        модел_3плюс=("model", "mean"), фаворит_реално=("fg", "mean"),
                                        фаворит_модел=("fe", "mean"), слаб_реално=("dg", "mean"),
                                        слаб_модел=("de", "mean"), общо_реално=("tot", "mean"),
                                        общо_модел=("tote", "mean")).reset_index()
    by_s = by_s.sort_values("cat").round(3)

    # малко мачове: отбор с < 15 мача в обучението
    few = (np.minimum(out["n_h"], out["n_a"]) < 15).to_numpy()
    few_row = {"n_малко": int(few.sum()),
               "brier_1x2_малко": round(brier_group(sq, few, GROUPS["1x2"]), 4) if few.any() else None,
               "brier_1x2_малко_baseline": round(brier_group(sqb, few, GROUPS["1x2"]), 4) if few.any() else None}

    # по брой срещу по календар (късната половина, най-добрите от ранната)
    fg = grid.groupby("forget").first().reset_index()[["forget", "k", "reg", "extra", "w_fr", "tempo_mult",
                                                        "brier_early", "brier_late", "b1x2_early", "b1x2_late"]]

    ev_cols = ["fixture_id", "date", "league_id", "home_team", "away_team", "hg", "ag", "home_flag",
               "lam", "mu", "rho", "bl_lam", "bl_mu", "n_h", "n_a"]
    mt = out[ev_cols].copy()
    for c in CODES + ["big3"]:
        mt["p_" + c] = P[c].round(4).to_numpy()
    mt.to_csv(f"{OUT}_matches.csv", index=False)

    # параметрите на последния модел (всички данни до днес)
    ix = Index(d)
    dd = d.assign(h=d["home_id"].map(ix.ti), a=d["away_id"].map(ix.ti))
    ref = dd["date"].max() + pd.Timedelta(days=1)
    m = fit(dd, ref, ix.nt, cfg)

    write_md(cfg, cfg_days, res, by_t, by_s, few_row, fg, m, len(d), len(out), b)


def md(df):
    """DataFrame -> markdown таблица (без tabulate, него го няма във venv)."""
    cols = [str(c) for c in df.columns]
    rows = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        rows.append("| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) else str(v) for v in r) + " |")
    return "\n".join(rows)


def write_md(cfg, cfg_days, res, by_t, by_s, few_row, fg, m, n_all, n_ev, b):
    L = [f"# Национални - модел и walk-forward (изход на nacionalni2_model_{TAG}.py)", "",
         f"Данни: {n_all} мача; прогнозирани (официални, от 2023-01-01): {n_ev}.",
         f"Избрани настройки (по Brier на ранната половина): {cfg}",
         f"Най-добрата с календарна забрава: {cfg_days}",
         f"Последен модел: c (официален, приятелски) = {np.round(np.exp(m['c']), 3).tolist()} гола на отбор, "
         f"домакинско предимство exp(H) = {np.round(np.exp(m['H']), 3).tolist()}, rho = {m['rho']:.3f}",
         f"Базови честоти (официалните мачове от 2022): " + ", ".join(f"{k} {v:.3f}" for k, v in b.items()), "",
         "## Модел срещу отправната точка (Brier, разлика = модел - отправна; a - коефициент на калибрация)", "",
         md(res), "", "## По турнир (всички години)", "", md(by_t), "",
         "## Разгроми по силата на фаворита (очаквана разлика в головете)", "", md(by_s), "",
         f"## Отбори с малко мачове (<15 в обучението): {few_row}", "",
         "## Забрава по брой мачове срещу по календар (най-добрата настройка от всеки вид)", "",
         md(fg), ""]
    open(f"{OUT}.md", "w").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
