"""
validation/tri_v_euro.py - ZADACHA_TRI.md, ЧАСТ В (24.09.2026). Общ модел за евротурнирите.

Проблем: всеки евротурнир се учи САМО от своите мачове (6-10 на отбор на сезон), а
съперниците идват от първенства, за които моделът няма представа колко са силни.

Модел (Поасон + Dixon-Coles, както fit_goals_model): ЕДНО фитване върху мачовете на трите
турнира + седемте ни първи дивизии (bulgaria, england, germany, spain, france, italy, portugal).
Всеки отбор принадлежи на група = държавата му (домашните - по файла, останалите - по
euro_team_countries.csv; без държава - група "?"):

    атака на отбор  = S_g + T_g + a_i        защита = S_g - T_g + d_i
    log lam (домакин) = c_comp + H_comp + атака_дом - защита_гост
    log mu  (гост)    = c_comp + атака_гост - защита_дом

  S_g - сила на държавата/първенството (кой печели срещу отбор от друга държава) - учи се от
        всички европейски мачове на всички отбори от тази държава;
  T_g - темпо на групата (колко гола в мачовете ѝ); в домашните мачове се слива с c_comp;
  a_i, d_i - собственото отклонение на отбора, учи се и от домашното първенство (30-40 мача
        на сезон) - регуларизация като fit_goals_model (reg_strength + low_data_extra/(тегло+1)),
        свиване на темпото на отбора с tempo_mult (както ЧАСТ А);
  c_comp, H_comp - ниво на головете и домакинско предимство по състезание (без регуларизация).

Настройки: w_dom - тегло на домашния мач спрямо евро мача (0 = само трите турнира заедно +
държави); reg_S, reg_T - регуларизация на S_g, T_g; tempo_mult; xi - време-тегла (едно за всички).

Точен градиент, L-BFGS-B (като validation/tri_fit.py).
"""
import os

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUPS = ["champions_league", "europa_league", "conference_league"]
DOMESTIC = {"bulgaria": "Bulgaria", "england": "England", "germany": "Germany", "spain": "Spain",
            "france": "France", "italy": "Italy", "portugal": "Portugal"}
HIST_FROM = pd.Timestamp("2022-01-01")


def load_all(load_league_data):
    """Всички завършени мачове (от HIST_FROM) с колона comp; team -> група."""
    frames, group = [], {}
    countries = dict(pd.read_csv(os.path.join(ROOT, "euro_team_countries.csv")).values)
    for lg, ctry in DOMESTIC.items():
        d = load_league_data(lg)
        d = d[d["date"] >= HIST_FROM]
        for t in set(d.home_team) | set(d.away_team):
            group[t] = ctry
        frames.append(d.assign(comp=lg))
    for cup in CUPS:
        frames.append(load_league_data(cup).assign(comp=cup))
    cols = ["fixture_id", "date", "home_team", "away_team", "home_goals", "away_goals", "comp"]
    allm = pd.concat([f[cols] for f in frames], ignore_index=True)
    for t in set(allm.home_team) | set(allm.away_team):
        if t not in group:
            group[t] = countries.get(t, "?")
    return allm, group


class Index:
    def __init__(self, allm, group):
        self.teams = sorted(set(allm.home_team) | set(allm.away_team))
        self.ti = {t: i for i, t in enumerate(self.teams)}
        self.groups = sorted(set(group[t] for t in self.teams))
        self.gi = {g: i for i, g in enumerate(self.groups)}
        self.tg = np.array([self.gi[group[t]] for t in self.teams])
        self.comps = list(DOMESTIC) + CUPS
        self.ci = {c: i for i, c in enumerate(self.comps)}
        self.nt, self.ng, self.nc = len(self.teams), len(self.groups), len(self.comps)


def fit(hist, ref_date, ix, w_dom=1.0, reg_S=1.0, reg_T=30.0, tempo_mult=1.0, xi=0.0018, reg_strength=3.0,
        low_data_extra_reg=15.0, x0=None, _objective=False):
    """hist - мачове с дата < ref_date (колони от load_all). Връща dict с параметрите."""
    v = hist.dropna(subset=["home_goals", "away_goals"])
    h = v["home_team"].map(ix.ti).to_numpy()
    a = v["away_team"].map(ix.ti).to_numpy()
    gh, ga = ix.tg[h], ix.tg[a]
    cm = v["comp"].map(ix.ci).to_numpy()
    hg = v["home_goals"].to_numpy(float)
    ag = v["away_goals"].to_numpy(float)
    w = np.exp(-xi * np.clip((ref_date - v["date"]).dt.days.to_numpy(), 0, None))
    dom = cm < len(DOMESTIC)
    w = np.where(dom, w * w_dom, w)
    keep = w > 0
    h, a, gh, ga, cm, hg, ag, w = h[keep], a[keep], gh[keep], ga[keep], cm[keep], hg[keep], ag[keep], w[keep]
    nt, ng, nc = ix.nt, ix.ng, ix.nc
    tw = np.zeros(nt)
    np.add.at(tw, h, w)
    np.add.at(tw, a, w)
    reg_vec = reg_strength + low_data_extra_reg / (tw + 1.0)
    const = (w * (gammaln(hg + 1) + gammaln(ag + 1))).sum()
    o_a, o_d, o_S, o_T, o_c, o_H = 0, nt, 2 * nt, 2 * nt + ng, 2 * nt + 2 * ng, 2 * nt + 2 * ng + nc
    i_r = 2 * nt + 2 * ng + 2 * nc
    npar = i_r + 1
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)

    def f(p):
        att, de = p[o_a:o_d], p[o_d:o_S]
        S, T, c, H, rho = p[o_S:o_T], p[o_T:o_c], p[o_c:o_H], p[o_H:i_r], p[i_r]
        eh = c[cm] + H[cm] + att[h] + S[gh] + T[gh] - de[a] - S[ga] + T[ga]
        ea = c[cm] + att[a] + S[ga] + T[ga] - de[h] - S[gh] + T[gh]
        lam, mu = np.exp(eh), np.exp(ea)
        ll = w * (hg * eh - lam + ag * ea - mu)
        glam = w * (hg - lam)
        gmu = w * (ag - mu)
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
        val = (-ll.sum() + const + np.sum(2 * reg_vec * (ss ** 2 + tempo_mult * tt ** 2))
               + reg_S * np.sum(S ** 2) + reg_T * np.sum(T ** 2))
        gr = np.zeros(npar)
        np.add.at(gr, o_a + h, -glam)
        np.add.at(gr, o_a + a, -gmu)
        np.add.at(gr, o_d + a, glam)
        np.add.at(gr, o_d + h, gmu)
        gr[o_a:o_d] += 2 * reg_vec * (ss + tempo_mult * tt)
        gr[o_d:o_S] += 2 * reg_vec * (ss - tempo_mult * tt)
        np.add.at(gr, o_S + gh, -(glam - gmu))
        np.add.at(gr, o_S + ga, -(gmu - glam))
        np.add.at(gr, o_T + gh, -(glam + gmu))
        np.add.at(gr, o_T + ga, -(glam + gmu))
        gr[o_S:o_T] += 2 * reg_S * S
        gr[o_T:o_c] += 2 * reg_T * T
        np.add.at(gr, o_c + cm, -(glam + gmu))
        np.add.at(gr, o_H + cm, -glam)
        gr[i_r] = -(w * g).sum()
        return val, gr

    if _objective:
        return f, npar
    start = np.zeros(npar) if x0 is None or len(x0) != npar else x0
    bounds = [(None, None)] * (npar - 1) + [(-0.9, 0.9)]
    r = minimize(f, start, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 5000})
    p = r.x
    return {"att": p[o_a:o_d], "de": p[o_d:o_S], "S": p[o_S:o_T], "T": p[o_T:o_c], "c": p[o_c:o_H],
            "H": p[o_H:i_r], "rho": float(p[i_r]), "x": p, "ok": r.success, "nit": r.nit}


def lambdas(m, ix, comp, home, away):
    if home not in ix.ti or away not in ix.ti:
        return None, None
    hi, ai = ix.ti[home], ix.ti[away]
    ghi, gai = ix.tg[hi], ix.tg[ai]
    ci = ix.ci[comp]
    ah = m["S"][ghi] + m["T"][ghi] + m["att"][hi]
    dh = m["S"][ghi] - m["T"][ghi] + m["de"][hi]
    aa = m["S"][gai] + m["T"][gai] + m["att"][ai]
    da = m["S"][gai] - m["T"][gai] + m["de"][ai]
    lam = np.exp(m["c"][ci] + m["H"][ci] + ah - da)
    mu = np.exp(m["c"][ci] + aa - dh)
    return float(lam), float(mu)


def check_grad():
    """Градиентът срещу числени производни (малка задача, случайна точка)."""
    import sys
    sys.path.insert(0, ROOT)
    import football_lib as fl
    allm, group = load_all(fl.load_league_data)
    ix = Index(allm, group)
    small = allm[(allm["date"] > pd.Timestamp("2026-03-01")) & (allm["date"] < pd.Timestamp("2026-09-01"))]
    f, npar = fit(small, pd.Timestamp("2026-09-01"), ix, w_dom=0.5, reg_S=2.0, reg_T=5.0, tempo_mult=3.0,
                  _objective=True)
    rng = np.random.default_rng(1)
    p = rng.normal(0, 0.1, npar)
    p[-1] = -0.05
    v, g = f(p)
    idx = rng.choice(npar, 40, replace=False)
    num = []
    for i in idx:
        e = np.zeros(npar)
        e[i] = 1e-6
        num.append((f(p + e)[0] - f(p - e)[0]) / 2e-6)
    print("макс. разлика градиент:", float(np.max(np.abs(np.array(num) - g[idx]))), "мащаб", float(np.max(np.abs(g[idx]))))


if __name__ == "__main__":
    check_grad()
