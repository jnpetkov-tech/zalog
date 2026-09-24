"""
validation/sila_fit.py - ZADACHA_GOLQMA.md, Етап 4 (24.09.2026). Фитърите от
validation/tri_fit.py (първенствата) и validation/tri_v_euro.py (общия евро модел) с
ДОПЪЛНИТЕЛНИ ковариати на състава - само за измерване, животът не се пипа.

За ковариатите X (k колони, по една стойност за домакина Xh и за госта Xa):
    log lam += Xh . b_own + Xa . b_opp
    log mu  += Xa . b_own + Xh . b_opp
b_own - колко съставът на отбора променя собствените му голове, b_opp - головете на
съперника (силна защита в състава -> по-малко допуснати). Лека ridge регуларизация
REG_BETA * |b|^2 (при нулеви ковариати b остава 0 - сметката е точно старата; проверено
в check(): разлика в lam/mu спрямо tri_fit/tri_v_euro).
"""
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

import tri_v_euro as E

REG_BETA = 1.0


def _dc_terms(lam, mu, rho, w, m00, m01, m10, m11, glam, gmu):
    tau = np.ones_like(lam)
    tau[m00] = 1 - lam[m00] * mu[m00] * rho
    tau[m01] = 1 + lam[m01] * rho
    tau[m10] = 1 + mu[m10] * rho
    tau[m11] = 1 - rho
    tc = np.clip(tau, 1e-10, None)
    ll = w * np.log(tc)
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
    return ll, (w * g).sum()


def fit_domestic(hist, ref_date, team_idx, n, xi, kind="goals", reg_strength=3.0, low_data_extra_reg=15.0,
                 reg_floor=1.0, reg_mult=1.0, intercept=False, tempo_mult=1.0, x0=None,
                 obs_cols=("home_goals", "away_goals"), cov_cols=None, extra_h=None, extra_a=None):
    """= tri_fit.fit + extra_h/extra_a: списъци с имена на колони (k ковариати на състава)."""
    use_dc = kind == "goals"
    extra_h = list(extra_h or [])
    extra_a = list(extra_a or [])
    k_ex = len(extra_h)
    need = list(obs_cols) + (list(cov_cols) if cov_cols else [])
    v = hist.dropna(subset=need)
    h = v["home_team"].map(team_idx).to_numpy()
    a = v["away_team"].map(team_idx).to_numpy()
    hg = v[obs_cols[0]].to_numpy(float)
    ag = v[obs_cols[1]].to_numpy(float)
    w = np.exp(-xi * np.clip((ref_date - v["date"]).dt.days.to_numpy(), 0, None))
    if kind == "direct":
        hc, ac = v[cov_cols[0]].to_numpy(float), v[cov_cols[1]].to_numpy(float)
        reg_vec = np.full(n, reg_strength * reg_mult)
    else:
        hc = ac = None
        tw = np.zeros(n)
        np.add.at(tw, h, w)
        np.add.at(tw, a, w)
        reg_vec = reg_mult * (reg_strength + low_data_extra_reg / (tw + reg_floor))
    XH = v[extra_h].fillna(0.0).to_numpy(float) if k_ex else None
    XA = v[extra_a].fillna(0.0).to_numpy(float) if k_ex else None
    const = (w * (gammaln(hg + 1) + gammaln(ag + 1))).sum()
    i_ha = 2 * n
    k = 2 * n + 1
    i_c = k if intercept else None
    k += int(intercept)
    i_b = k if kind == "direct" else None
    k += int(kind == "direct")
    i_bo = k
    k += k_ex
    i_bd = k
    k += k_ex
    i_r = k if use_dc else None
    k += int(use_dc)
    npar = k
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)

    def f(p):
        att, de = p[:n], p[n:2 * n]
        c = p[i_c] if intercept else 0.0
        eh = att[h] - de[a] + p[i_ha] + c
        ea = att[a] - de[h] + c
        if kind == "direct":
            eh = eh + p[i_b] * hc
            ea = ea + p[i_b] * ac
        if k_ex:
            bo, bd = p[i_bo:i_bo + k_ex], p[i_bd:i_bd + k_ex]
            eh = eh + XH @ bo + XA @ bd
            ea = ea + XA @ bo + XH @ bd
        lam, mu = np.exp(eh), np.exp(ea)
        ll = w * (hg * eh - lam + ag * ea - mu)
        glam = w * (hg - lam)
        gmu = w * (ag - mu)
        grho = 0.0
        if use_dc:
            lld, grho = _dc_terms(lam, mu, p[i_r], w, m00, m01, m10, m11, glam, gmu)
            ll = ll + lld
        ss, tt = (att + de) / 2, (att - de) / 2
        val = -ll.sum() + const + np.sum(2 * reg_vec * (ss ** 2 + tempo_mult * tt ** 2))
        gr = np.zeros(npar)
        np.add.at(gr, h, -glam)
        np.add.at(gr, a, -gmu)
        np.add.at(gr, n + a, glam)
        np.add.at(gr, n + h, gmu)
        gr[:n] += 2 * reg_vec * (ss + tempo_mult * tt)
        gr[n:2 * n] += 2 * reg_vec * (ss - tempo_mult * tt)
        gr[i_ha] = -glam.sum()
        if intercept:
            gr[i_c] = -(glam.sum() + gmu.sum())
        if kind == "direct":
            gr[i_b] = -((glam * hc).sum() + (gmu * ac).sum())
        if k_ex:
            val += REG_BETA * (np.sum(bo ** 2) + np.sum(bd ** 2))
            gr[i_bo:i_bo + k_ex] = -(glam @ XH + gmu @ XA) + 2 * REG_BETA * bo
            gr[i_bd:i_bd + k_ex] = -(glam @ XA + gmu @ XH) + 2 * REG_BETA * bd
        if use_dc:
            gr[i_r] = -grho
        return val, gr

    start = np.zeros(npar) if x0 is None or len(x0) != npar else x0
    bounds = [(None, None)] * (npar - 1) + [(-0.9, 0.9)] if use_dc else None
    r = minimize(f, start, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 5000})
    p = r.x
    return {"attack": p[:n], "defence": p[n:2 * n], "home_adv": p[i_ha], "c": p[i_c] if intercept else 0.0,
            "beta": p[i_b] if kind == "direct" else 0.0, "rho": float(p[i_r]) if use_dc else 0.0,
            "b_own": p[i_bo:i_bo + k_ex], "b_opp": p[i_bd:i_bd + k_ex], "kind": kind, "x": p}


def lambdas_domestic(m, ti, h, a, hc=None, ac=None, XH=None, XA=None):
    hi = np.array([ti[x] for x in h])
    ai = np.array([ti[x] for x in a])
    lam = m["c"] + m["attack"][hi] - m["defence"][ai] + m["home_adv"]
    mu = m["c"] + m["attack"][ai] - m["defence"][hi]
    if hc is not None:
        lam = lam + m["beta"] * hc
        mu = mu + m["beta"] * ac
    if XH is not None and len(m["b_own"]):
        lam = lam + XH @ m["b_own"] + XA @ m["b_opp"]
        mu = mu + XA @ m["b_own"] + XH @ m["b_opp"]
    return np.exp(lam), np.exp(mu)


def fit_euro(hist, ref_date, ix, w_dom=1.0, reg_S=1.0, reg_T=30.0, tempo_mult=1.0, xi=0.0018, reg_strength=3.0,
             low_data_extra_reg=15.0, x0=None, extra_h=None, extra_a=None):
    """= tri_v_euro.fit + ковариати на състава (extra_h/extra_a - колони в hist)."""
    extra_h = list(extra_h or [])
    extra_a = list(extra_a or [])
    k_ex = len(extra_h)
    v = hist.dropna(subset=["home_goals", "away_goals"])
    h = v["home_team"].map(ix.ti).to_numpy()
    a = v["away_team"].map(ix.ti).to_numpy()
    gh, ga = ix.tg[h], ix.tg[a]
    cm = v["comp"].map(ix.ci).to_numpy()
    hg = v["home_goals"].to_numpy(float)
    ag = v["away_goals"].to_numpy(float)
    w = np.exp(-xi * np.clip((ref_date - v["date"]).dt.days.to_numpy(), 0, None))
    dom = cm < len(E.DOMESTIC)
    w = np.where(dom, w * w_dom, w)
    keep = w > 0
    h, a, gh, ga, cm, hg, ag, w = h[keep], a[keep], gh[keep], ga[keep], cm[keep], hg[keep], ag[keep], w[keep]
    XH = v[extra_h].fillna(0.0).to_numpy(float)[keep] if k_ex else None
    XA = v[extra_a].fillna(0.0).to_numpy(float)[keep] if k_ex else None
    nt, ng, nc = ix.nt, ix.ng, ix.nc
    tw = np.zeros(nt)
    np.add.at(tw, h, w)
    np.add.at(tw, a, w)
    reg_vec = reg_strength + low_data_extra_reg / (tw + 1.0)
    const = (w * (gammaln(hg + 1) + gammaln(ag + 1))).sum()
    o_a, o_d, o_S, o_T, o_c, o_H = 0, nt, 2 * nt, 2 * nt + ng, 2 * nt + 2 * ng, 2 * nt + 2 * ng + nc
    i_bo = 2 * nt + 2 * ng + 2 * nc
    i_bd = i_bo + k_ex
    i_r = i_bd + k_ex
    npar = i_r + 1
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)

    def f(p):
        att, de = p[o_a:o_d], p[o_d:o_S]
        S, T, c, H, rho = p[o_S:o_T], p[o_T:o_c], p[o_c:o_H], p[o_H:i_bo], p[i_r]
        eh = c[cm] + H[cm] + att[h] + S[gh] + T[gh] - de[a] - S[ga] + T[ga]
        ea = c[cm] + att[a] + S[ga] + T[ga] - de[h] - S[gh] + T[gh]
        if k_ex:
            bo, bd = p[i_bo:i_bd], p[i_bd:i_r]
            eh = eh + XH @ bo + XA @ bd
            ea = ea + XA @ bo + XH @ bd
        lam, mu = np.exp(eh), np.exp(ea)
        ll = w * (hg * eh - lam + ag * ea - mu)
        glam = w * (hg - lam)
        gmu = w * (ag - mu)
        lld, grho = _dc_terms(lam, mu, rho, w, m00, m01, m10, m11, glam, gmu)
        ll = ll + lld
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
        if k_ex:
            val += REG_BETA * (np.sum(bo ** 2) + np.sum(bd ** 2))
            gr[i_bo:i_bd] = -(glam @ XH + gmu @ XA) + 2 * REG_BETA * bo
            gr[i_bd:i_r] = -(glam @ XA + gmu @ XH) + 2 * REG_BETA * bd
        gr[i_r] = -grho
        return val, gr

    start = np.zeros(npar) if x0 is None or len(x0) != npar else x0
    bounds = [(None, None)] * (npar - 1) + [(-0.9, 0.9)]
    r = minimize(f, start, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 5000})
    p = r.x
    return {"att": p[o_a:o_d], "de": p[o_d:o_S], "S": p[o_S:o_T], "T": p[o_T:o_c], "c": p[o_c:o_H],
            "H": p[o_H:i_bo], "b_own": p[i_bo:i_bd], "b_opp": p[i_bd:i_r], "rho": float(p[i_r]), "x": p}


def lambdas_euro(m, ix, comp, h, a, XH=None, XA=None):
    out = np.array([E.lambdas(m, ix, comp, x, y) for x, y in zip(h, a)], dtype=float)
    lam, mu = np.log(out[:, 0]), np.log(out[:, 1])
    if XH is not None and len(m["b_own"]):
        lam = lam + XH @ m["b_own"] + XA @ m["b_opp"]
        mu = mu + XA @ m["b_own"] + XH @ m["b_opp"]
    return np.exp(lam), np.exp(mu)
