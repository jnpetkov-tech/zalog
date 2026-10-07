"""validation/kalibraciq2_20261007.py - ZADACHA_MODELI, ЧАСТ 3 (07.10.2026): калибрация с отместване върху ядро+слой.

Настройки и критерий - validation/kalibraciq2_nastroyki_20261007.md (записани преди пускането).
Употреба (по ред):
  venv/bin/python3 validation/kalibraciq2_20261007.py --layer   # walk-forward на слоя AB и ABC -> вероятностите по мач (без калибрация)
  venv/bin/python3 validation/kalibraciq2_20261007.py --early   # фит на Б/В на ранната, мерки на ранната, избор (записва се)
  venv/bin/python3 validation/kalibraciq2_20261007.py --late    # А срещу избрания на късната (веднъж) -> отчет
  venv/bin/python3 validation/kalibraciq2_20261007.py --report  # ако няма избран: отчет само от ранната
Изход: validation/kalibraciq2_20261007_{layer.csv.gz,early.md,izbor.json,late.json}, validation/kalibraciq2_20261007.md
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import minimize  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from features import layer_lib as L  # noqa: E402

TAG = "20261007"
V = os.path.join(ROOT, "validation")
LAYER_CSV = os.path.join(V, f"kalibraciq2_{TAG}_layer.csv.gz")
SEL = os.path.join(V, f"kalibraciq2_{TAG}_izbor.json")
CODES = L.CODES
GROUPS = L.GROUPS
PAIRS = [("over25", "under25"), ("btts_yes", "btts_no"), ("home_over15", "home_under15"), ("away_over15", "away_under15")]
X3 = ["home_win", "draw", "away_win"]
EPS = 1e-9


# ----------------------------------------------------------------------------------------------- вероятности по мач
def layer():
    import features.layer_train as T
    T_ = L.load_table()
    long = L.to_long(T_)
    abc = json.load(open(os.path.join(ROOT, "features", "layer_config.json")))
    out = T_[["fixture_id", "league", "date", "hg", "ag", "lam", "mu", "rho", "is_eval"]].copy()
    for name, cfg in (("AB", T.AB_CFG), ("ABC", {k: abc[k] for k in T.CFG_KEYS})):
        res, _ = L.walk_forward(long, T_, {**cfg, "n_list": [cfg["n_est"]]}, L.EVAL_START)
        rh, ra = res[cfg["n_est"]]
        out[f"lam_{name}"], out[f"mu_{name}"] = L.corrected(T_, rh, ra, cfg["shrink"])
        print(name, "готово", flush=True)
    out = out[out["is_eval"] & (out["date"] >= L.EVAL_START) & out["lam_AB"].notna() & out["hg"].notna()].drop(columns="is_eval")
    out.to_csv(LAYER_CSV, index=False, float_format="%.6f")
    print(len(out), "мача ->", LAYER_CSV)


def load(fset):
    d = pd.read_csv(LAYER_CSV)
    P = L.probs(d[f"lam_{fset}"].to_numpy(), d[f"mu_{fset}"].to_numpy(), d["rho"].to_numpy())
    P.index = d.index
    Y = pd.DataFrame(L.y_matrix(d["hg"], d["ag"]), columns=CODES, index=d.index)
    return d, P, Y


# ----------------------------------------------------------------------------------------------- калибрации
def cal_A(P):
    import layer_live
    import prediction_policy as policy
    out = P.copy()
    for c in CODES:
        b = policy.CALIBRATION_BASE[c]
        a = layer_live.LAYER_CALIBRATION_A[L.GROUP_OF[c]]
        out[c] = np.clip(b + a * (P[c] - b), 0.0, 1.0)
    return out


def _logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def apply_params(P, prm):
    out = P.copy()
    lp = np.log(np.clip(P[X3].to_numpy(), EPS, 1))
    a2, a3, b = prm["1x2"]
    z = np.column_stack([b * lp[:, 0], a2 + b * lp[:, 1], a3 + b * lp[:, 2]])
    z -= z.max(1, keepdims=True)
    e = np.exp(z)
    out[X3] = e / e.sum(1, keepdims=True)
    for yes, no in PAIRS:
        a, b = prm[yes]
        q = 1 / (1 + np.exp(-(a + b * _logit(P[yes].to_numpy()))))
        out[yes], out[no] = q, 1 - q
    return out


def fit_params(P, Y, slope=True):
    """Максимално правдоподобие на ранната. slope=False -> β = 1 (само отмествания)."""
    prm = {}
    lp = np.log(np.clip(P[X3].to_numpy(), EPS, 1))
    y3 = Y[X3].to_numpy().argmax(1)

    def nll3(x):
        a2, a3 = x[0], x[1]
        b = x[2] if slope else 1.0
        z = np.column_stack([b * lp[:, 0], a2 + b * lp[:, 1], a3 + b * lp[:, 2]])
        z -= z.max(1, keepdims=True)
        lse = np.log(np.exp(z).sum(1))
        return -(z[np.arange(len(z)), y3] - lse).sum()
    r = minimize(nll3, np.array([0.0, 0.0, 1.0][:3 if slope else 2]), method="L-BFGS-B")
    prm["1x2"] = (float(r.x[0]), float(r.x[1]), float(r.x[2]) if slope else 1.0)
    for yes, _ in PAIRS:
        lg, y = _logit(P[yes].to_numpy()), Y[yes].to_numpy()

        def nll(x):
            a = x[0]
            b = x[1] if slope else 1.0
            s = a + b * lg
            return (np.logaddexp(0, s) - y * s).sum()
        r = minimize(nll, np.array([0.0, 1.0][:2 if slope else 1]), method="L-BFGS-B")
        prm[yes] = (float(r.x[0]), float(r.x[1]) if slope else 1.0)
    return prm


# ----------------------------------------------------------------------------------------------- мерки
def per_match(P, Y):
    p, y = P[CODES].to_numpy(), Y[CODES].to_numpy()
    o = pd.DataFrame({"b11": ((p - y) ** 2).mean(1)}, index=P.index)
    o["ll1x2"] = -np.log(np.maximum((P[X3].to_numpy() * Y[X3].to_numpy()).sum(1), 1e-12))
    for g in GROUPS:
        idx = [i for i, c in enumerate(CODES) if L.GROUP_OF[c] == g]
        o[f"b_{g}"] = ((p[:, idx] - y[:, idx]) ** 2).mean(1)
    return o


def fmt(ci, k=5):
    return f"{ci[0]:+.{k}f} [{ci[1]:+.{k}f}; {ci[2]:+.{k}f}]"


def means(P, Y):
    return {c: (float(P[c].mean()), float(Y[c].mean())) for c in CODES}


def variants(P, prm):
    return {"А": cal_A(P), "Б": apply_params(P, prm["Б"]), "В": apply_params(P, prm["В"])}


# ----------------------------------------------------------------------------------------------- стъпки
def early():
    d, P, Y = load("AB")
    e = (d["date"] < L.EARLY_END).to_numpy()
    prm = {"Б": fit_params(P[e], Y[e], True), "В": fit_params(P[e], Y[e], False)}
    rows, lines = [], []
    Ve = variants(P[e], prm)
    m = {k: per_match(v, Y[e]) for k, v in Ve.items()}
    for k, v in Ve.items():
        mm = means(v, Y[e])
        rows.append({"variant": k, "b11": m[k]["b11"].mean(), "ll1x2": m[k]["ll1x2"].mean(),
                     "max_dev_pp": max(abs(a - b) for a, b in mm.values()) * 100})
    r = pd.DataFrame(rows)
    a_b = r.loc[r.variant == "А", "b11"].iloc[0]
    best = r[r.variant != "А"].sort_values("b11").iloc[0]
    chosen = best["variant"] if best["b11"] < a_b else None
    raw = per_match(P[e], Y[e])
    json.dump({"chosen": chosen, "params": prm, "early": r.to_dict("records"), "early_raw_b11": float(raw["b11"].mean()),
               "rule": "по-ниският Brier 11 на ранната сред Б/В, ако < А"}, open(SEL, "w"), ensure_ascii=False, indent=1)
    md = ["# ЧАСТ 3 — ранна половина (фит и избор), слой AB", "", f"Мачове: {int(e.sum())} (дата < {L.EARLY_END}). Без калибрация: Brier 11 "
          f"{raw['b11'].mean():.5f}, log-loss 1X2 {raw['ll1x2'].mean():.5f}.", "",
          "| вариант | Brier 11 | log-loss 1X2 | разлика спрямо А (Brier 11), 95% | най-голямо отклонение средна/реална |", "|---|---|---|---|---|"]
    for _, x in r.iterrows():
        ci = L.boot_ci(m[x.variant]["b11"] - m["А"]["b11"]) if x.variant != "А" else None
        md.append(f"| {x.variant} | {x.b11:.5f} | {x.ll1x2:.5f} | {fmt(ci) if ci else '—'} | {x.max_dev_pp:.2f} пункта |")
    md += ["", "Параметри (фит на ранната): " + "; ".join(f"{k}: " + ", ".join(f"{g} {tuple(round(t, 4) for t in v)}" for g, v in p.items())
                                                         for k, p in prm.items()), "",
           f"**Избор (правило от настройките):** {'вариант ' + chosen if chosen else 'нито един от Б/В не е по-добър от А на ранната - нищо не се избира'}."]
    open(os.path.join(V, f"kalibraciq2_{TAG}_early.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))


def late():
    sel = json.load(open(SEL))
    ch = sel["chosen"]
    if not ch:
        print("няма избран вариант - късната не се пуска; ползвай --report")
        return
    prm = {k: {g: tuple(v) for g, v in p.items()} for k, p in sel["params"].items()}
    res = {}
    for fset in ("AB", "ABC"):
        d, P, Y = load(fset)
        lt = (d["date"] >= L.EARLY_END).to_numpy()
        Vl = variants(P[lt], prm)
        mA, mX = per_match(Vl["А"], Y[lt]), per_match(Vl[ch], Y[lt])
        raw = per_match(P[lt], Y[lt])
        ci = {k: L.boot_ci(mX[k] - mA[k]) for k in mA.columns}
        dl = d[lt]
        lg = {l: L.boot_ci((mX["b11"] - mA["b11"])[(dl["league"] == l).to_numpy()]) for l in sorted(dl["league"].unique())}
        res[fset] = {"n": int(lt.sum()), "A": {k: float(mA[k].mean()) for k in mA}, "X": {k: float(mX[k].mean()) for k in mX},
                     "raw": {k: float(raw[k].mean()) for k in raw}, "ci": ci, "league_ci": lg,
                     "means_A": means(Vl["А"], Y[lt]), "means_X": means(Vl[ch], Y[lt]), "means_raw": means(P[lt], Y[lt])}
    ab = res["AB"]
    c1 = ab["ci"]["b11"][2] < 0
    c2 = ab["ci"]["ll1x2"][2] < 0
    c3 = all(abs(p - y) <= 0.005 for p, y in ab["means_X"].values())
    c4 = all(v[1] <= 0 for v in ab["league_ci"].values()) and all(ab["ci"][f"b_{g}"][1] <= 0 for g in GROUPS)
    c5 = res["ABC"]["ci"]["b11"][1] <= 0
    passed = all((c1, c2, c3, c4, c5))
    json.dump({"chosen": ch, "passed": passed, "c": [c1, c2, c3, c4, c5], "res": res}, open(os.path.join(V, f"kalibraciq2_{TAG}_late.json"), "w"),
              ensure_ascii=False, indent=1, default=float)
    early_md = open(os.path.join(V, f"kalibraciq2_{TAG}_early.md"), encoding="utf-8").read().split("\n", 2)[2]
    Ln = ["# ЧАСТ 3 (ZADACHA_MODELI) — калибрация с отместване", "",
          f"**Решение: {'КРИТЕРИЯТ Е ИЗПЪЛНЕН — вариант ' + ch if passed else 'КРИТЕРИЯТ НЕ Е ИЗПЪЛНЕН — нищо не влиза'}.**", "",
          "Настройки и критерий — `validation/kalibraciq2_nastroyki_20261007.md` (записани преди пускането). Скрипт `validation/kalibraciq2_20261007.py`; "
          "вероятности по мач — `validation/kalibraciq2_20261007_layer.csv.gz`.", "", "## Ранна половина (фит и избор)", "", early_md.strip(), ""]
    for fset in ("AB", "ABC"):
        r = res[fset]
        Ln += [f"## Късна половина (пусната веднъж), слой {fset}: А срещу {ch}, {r['n']} мача", "",
               f"| мярка | без калибрация | А | {ch} | разлика ({ch} − А), 95% |", "|---|---|---|---|---|"]
        for k, nm in [("b11", "Brier 11 изхода"), ("ll1x2", "log-loss 1X2")] + [(f"b_{g}", f"Brier група {g}") for g in GROUPS]:
            Ln.append(f"| {nm} | {r['raw'][k]:.5f} | {r['A'][k]:.5f} | {r['X'][k]:.5f} | {fmt(r['ci'][k])} |")
        Ln += ["", "| изход | реално | без калибрация | А | " + ch + " |", "|---|---|---|---|---|"]
        for c in CODES:
            y = r["means_A"][c][1]
            Ln.append(f"| {c} | {y * 100:.1f}% | {r['means_raw'][c][0] * 100:.1f}% | {r['means_A'][c][0] * 100:.1f}% | {r['means_X'][c][0] * 100:.1f}% |")
        Ln += ["", "По лига (Brier 11, " + ch + " − А): " + "; ".join(f"{l} {fmt(v)}" for l, v in r["league_ci"].items()), ""]
    Ln += ["## Критерий", "", f"1. Brier 11 под нулата: {'да' if c1 else 'не'}", f"2. log-loss 1X2 под нулата: {'да' if c2 else 'не'}",
           f"3. всеки изход в ±0.5 пункта на късната: {'да' if c3 else 'не'} (най-голямо отклонение "
           f"{max(abs(p - y) for p, y in ab['means_X'].values()) * 100:.2f} пункта)",
           f"4. нито лига, нито група значимо по-зле: {'да' if c4 else 'не'}", f"5. ABC не значимо по-зле: {'да' if c5 else 'не'}", ""]
    open(os.path.join(V, f"kalibraciq2_{TAG}.md"), "w", encoding="utf-8").write("\n".join(Ln) + "\n")
    print("\n".join(Ln))


if __name__ == "__main__":
    if "--layer" in sys.argv:
        layer()
    elif "--early" in sys.argv:
        early()
    elif "--late" in sys.argv:
        late()
    else:
        print(__doc__)
