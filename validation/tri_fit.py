"""
validation/tri_fit.py - ZADACHA_TRI.md (23.09.2026). Бърз фитър за backtest.

Същият модел като football_lib.fit_goals_model() / fit_goals_direct_covariate()
(атака/защита/домакинско предимство, време-тегла, ridge регуларизация,
Dixon-Coles rho, контузии като директен ковариант, дробни наблюдения за xG),
но с ТОЧЕН градиент - L-BFGS-B без числени производни, ~50-100 пъти по-бързо.
Проверено срещу football_lib (виж check() - разлика в lam/mu) преди употреба.

Допълнителни настройки (само за измерване в ZADACHA_TRI.md, ЧАСТ А):
  reg_mult  - множител на ЦЯЛАТА регуларизация (reg_strength и low_data_extra_reg)
  tempo_mult - допълнителен множител САМО за "темпото" на отбора. Атака a и защита d
              се разлагат на сила s = (a+d)/2 (решава кой печели - 1X2) и темпо
              t = (a-d)/2 (решава колко гола има в мачовете му - над/под, двата
              отбора). Сегашната регуларизация reg*(a^2+d^2) = 2*reg*(s^2+t^2);
              с tempo_mult = k става 2*reg*(s^2 + k*t^2). k = 1 - точно сегашното.
  intercept - общо ниво на головете (без регуларизация). Без него силната
              регуларизация дърпа отборите към lam = exp(home_adv), mu = 1.0,
              а не към средното на лигата.
"""
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln


def fit(hist, ref_date, team_idx, n, xi, kind="goals", reg_strength=3.0, low_data_extra_reg=15.0,
        reg_floor=1.0, reg_mult=1.0, intercept=False, tempo_mult=1.0, x0=None, obs_cols=("home_goals", "away_goals"),
        cov_cols=None):
    """kind: 'goals' (= fit_goals_model, use_dc=True), 'direct' (= fit_goals_direct_covariate),
    'xg' (= fit_goals_model(obs_cols=xG, use_dc=False))."""
    use_dc = kind == "goals"
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
    const = (w * (gammaln(hg + 1) + gammaln(ag + 1))).sum()
    # индекси на параметрите
    i_ha = 2 * n
    k = 2 * n + 1
    i_c = k if intercept else None
    k += int(intercept)
    i_b = k if kind == "direct" else None
    k += int(kind == "direct")
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
        lam, mu = np.exp(eh), np.exp(ea)
        ll = w * (hg * eh - lam + ag * ea - mu)
        glam = w * (hg - lam)   # d ll / d eh
        gmu = w * (ag - mu)
        grho = 0.0
        if use_dc:
            rho = p[i_r]
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
            grho = (w * g).sum()
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
        if use_dc:
            gr[i_r] = -grho
        return val, gr

    start = np.zeros(npar) if x0 is None or len(x0) != npar else x0
    bounds = [(None, None)] * (npar - 1) + [(-0.9, 0.9)] if use_dc else None
    r = minimize(f, start, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 5000})
    p = r.x
    return {"attack": p[:n], "defence": p[n:2 * n], "home_adv": p[i_ha], "c": p[i_c] if intercept else 0.0,
            "beta": p[i_b] if kind == "direct" else 0.0, "rho": float(p[i_r]) if use_dc else 0.0,
            "kind": kind, "x": p}


def lambdas(m, team_idx, home, away, h_cov=0.0, a_cov=0.0):
    if home not in team_idx or away not in team_idx:
        return None, None
    hi, ai = team_idx[home], team_idx[away]
    lam = np.exp(m["c"] + m["attack"][hi] - m["defence"][ai] + m["home_adv"] + m["beta"] * h_cov)
    mu = np.exp(m["c"] + m["attack"][ai] - m["defence"][hi] + m["beta"] * a_cov)
    return lam, mu
