"""validation/pazar_broeve_20261002.py - т.5в корнери и т.5г картони над/под (брой на отбора, LightGBM Поасон, два реда на мач).
Настройки: pazari_nastroyki_20261002.md. Изход: validation/pazar_korneri_20261002.md / validation/pazar_kartoni_20261002.md.
Употреба: nice -n 19 venv/bin/python3 validation/pazar_broeve_20261002.py corners|cards"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import poisson

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pazar_lib_20261002 as PL  # noqa: E402
from features import layer_lib as L  # noqa: E402

LEAGUES = PL.L.ALL_LEAGUES_17
CFG = {"depth": 3, "min_child": 300, "l2": 100, "n_est": 200, "lr": 0.03}
SPEC = {
    "corners": dict(lines=[8.5, 9.5, 10.5], fset="AB", extra=[], name="корнери", out="pazar_korneri_20261002"),
    "cards": dict(lines=[3.5, 4.5, 5.5], fset="AB", extra=L.SHARED_D, name="картони", out="pazar_kartoni_20261002"),
}


def counts(kind):
    """{fixture_id: (домакин, гост)} от {лига}_stats_full.csv; картони = жълти + червени (празно червено = 0, ако има жълти)."""
    out = {}
    for lg in LEAGUES:
        fxp, stp = os.path.join(PL.ROOT, f"{lg}_fixtures.csv"), os.path.join(PL.ROOT, f"{lg}_stats_full.csv")
        if not (os.path.exists(fxp) and os.path.exists(stp)):
            continue
        fx = pd.read_csv(fxp, usecols=["fixture_id", "home_id", "away_id", "fetched_at"]).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
        hid = dict(zip(fx.fixture_id, fx.home_id))
        st = pd.read_csv(stp, low_memory=False).drop_duplicates(["fixture_id", "team_id"])
        if kind == "corners":
            v = pd.to_numeric(st["Corner_Kicks"], errors="coerce")
        else:
            y = pd.to_numeric(st["Yellow_Cards"], errors="coerce")
            r = pd.to_numeric(st["Red_Cards"], errors="coerce")
            v = y + r.fillna(0).where(y.notna())
        st = st.assign(v=v)
        for fid, g in st.groupby("fixture_id"):
            if fid not in hid or len(g) != 2 or g["v"].isna().any():
                continue
            h = g[g["team_id"] == hid[fid]]["v"]
            a = g[g["team_id"] != hid[fid]]["v"]
            if len(h) == 1 and len(a) == 1:
                out[int(fid)] = (float(h.iloc[0]), float(a.iloc[0]))
    return out


def main(kind):
    import lightgbm as lgb
    sp = SPEC[kind]
    t = L.load_table()
    c = counts(kind)
    t["ch"] = t["fixture_id"].map(lambda f: c.get(int(f), (np.nan, np.nan))[0])
    t["ca"] = t["fixture_id"].map(lambda f: c.get(int(f), (np.nan, np.nan))[1])
    long = L.to_long(t)
    long["y"] = np.concatenate([t["ch"].to_numpy(), t["ca"].to_numpy()])
    cols = L.feature_columns(sp["fset"]) + [f"{x}" for x in sp["extra"] if x in long.columns]
    X = long[cols].to_numpy(np.float32)
    y = long["y"].to_numpy()
    dts, wk = long["d"].to_numpy(), long["week"].to_numpy()
    early, late = PL.halves(t)
    lt2 = np.concatenate([late, late])
    pred = np.full(len(long), np.nan)
    params = {**L.lgb_params({**CFG, "fset": sp["fset"]}), "objective": "poisson"}
    for w in sorted(np.unique(wk[lt2])):
        tr = (dts < w) & ~np.isnan(y)
        te = (wk == w) & lt2
        if tr.sum() < 3000 or not te.any():
            continue
        bst = lgb.train(params, lgb.Dataset(X[tr], label=y[tr], feature_name=cols, categorical_feature=["league_code"]), num_boost_round=CFG["n_est"])
        pred[te] = bst.predict(X[te])
    n = len(t)
    lam_h, lam_a = pred[:n], pred[n:]
    m = late & ~np.isnan(t["ch"].to_numpy()) & ~np.isnan(lam_h) & ~np.isnan(lam_a)
    tot = (t["ch"] + t["ca"]).to_numpy()
    lt = lam_h + lam_a
    e = early & ~np.isnan(tot)
    lines = [f"# Т.5{'в' if kind == 'corners' else 'г'} — {sp['name']} над/под (02.10.2026)", "",
             "Настройки и критерии (записани преди резултатите): `validation/pazari_nastroyki_20261002.md`. LightGBM (Поасон, depth 3, min_child 300, "
             "l2 100, 200 дървета), цел — брой на отбора; седмично префитване само от минали мачове; сбор = Поасон(λ_д + λ_г).",
             f"Признаци: набор {sp['fset']}" + (" + блок D (съдия, час, кръг)" if sp["extra"] else "") + f" ({len(cols)} колони).",
             f"Късна половина с {sp['name']}: **{int(m.sum())} мача**. Средно реално {np.nanmean(tot[m]):.2f}, модел {lt[m].mean():.2f}.", ""]
    hdr = list(PL.HEADER)
    if kind == "corners":
        hdr = [hdr[0].replace("| решение |", "| сегашният модел (Brier) | решение |"), hdr[1] + "---|"]
        cur = pd.read_csv(os.path.join(PL.ROOT, "validation", "final_v_20260924_matches.csv"),
                          usecols=["fixture_id", "p_corners_total_over_9.5", "y_corners_total_over_9.5"]).dropna()
    lines += hdr
    res = {}
    for line in sp["lines"]:
        p = 1 - poisson.cdf(np.floor(line), lt[m])
        Y = np.column_stack([tot[m] > line, tot[m] <= line]).astype(float)
        b = np.array([(tot[e] > line).mean(), (tot[e] <= line).mean()])
        P = np.column_stack([p, 1 - p])
        extra_ok, extra_text = True, ""
        if kind == "corners" and line == 9.5:
            fids = t["fixture_id"].to_numpy()[m]
            j = pd.DataFrame({"fixture_id": fids, "p_new": p, "y": Y[:, 0]}).merge(cur, on="fixture_id")
            import prediction_policy as policy
            bb = policy.CALIBRATION_BASE.get("corners_total_over_9.5")
            aa = policy.CALIBRATION_A.get(policy.market_group("corners_total_over_9.5"), 1.0)
            pc = j["p_corners_total_over_9.5"].to_numpy()
            pc_cal = np.clip(bb + aa * (pc - bb), 0, 1) if bb is not None else pc
            yy = j["y"].to_numpy()
            b_new = (j["p_new"] - yy) ** 2
            b_cur = (pc_cal - yy) ** 2
            dd = L.boot_ci(b_new.to_numpy() - b_cur)
            extra_ok = dd[0] <= 0      # „не по-лош“: средната разлика нов − сегашен ≤ 0
            extra_text = (f"{len(j)} общи мача: нов {b_new.mean():.5f}, сегашен (показван, калибриран a={aa}) {b_cur.mean():.5f}, "
                          f"разлика {dd[0]:+.5f} [{dd[1]:+.5f}; {dd[2]:+.5f}] → {'не по-лош' if extra_ok else 'ПО-ЛОШ'}")
        elif kind == "corners":
            extra_text = "—"
        ok, Lr, num = PL.verdict(f"над/под {line}", P, Y, b, extra_ok, extra_text)
        res[line] = (ok, num)
        lines += Lr
    lines += ["", "## Решение", ""] + [f"- над/под {k}: **{'влиза' if v[0] else 'не влиза'}** (a = {v[1]['a']:.3f}; "
                                        f"информативен: {'да' if v[1]['informative'] else 'не'})" for k, v in res.items()] + [""]
    open(os.path.join(PL.ROOT, "validation", sp["out"] + ".md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1])
