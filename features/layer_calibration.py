"""features/layer_calibration.py - калибрационните коефициенти за ядро+слой, фитнати САМО на ранната половина (ZADACHA_TABLICA, стъпка 4).
Метод = validation/calibration_fit (b - честотата на изхода на ранната половина; a по група). Изход: validation/sloy_kalibraciq_20261001.csv.
Нищо не се прилага в живия код (prediction_policy.CALIBRATION_A остава непроменена)."""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from features import layer_lib as L  # noqa: E402


def main():
    cfg = json.load(open(os.path.join(ROOT, "features", "layer_config.json")))
    T = L.load_table()
    LONG = L.to_long(T)
    early = (T["is_eval"] & (T["d"] >= L.EVAL_START) & (T["d"] < L.EARLY_END)).to_numpy()
    res, _ = L.walk_forward(LONG, T, {"depth": cfg["depth"], "min_child": cfg["min_child"], "l2": cfg["l2"], "n_list": [cfg["n_est"]], "fset": cfg["fset"]},
                            L.EVAL_START, L.EARLY_END)
    rh, ra = res[cfg["n_est"]]
    lam, mu = L.corrected(T, rh, ra, cfg["shrink"])
    Y = L.y_matrix(T["hg"][early], T["ag"][early])
    base = L.calib_base(Y)
    a0 = L.calib_coef(L.probs(T["lam"][early], T["mu"][early], T["rho"][early]), Y, base)
    a1 = L.calib_coef(L.probs(lam[early], mu[early], T["rho"][early]), Y, base)
    rows = [{"group": g, "a_core_early": a0[g], "a_layer_early": a1[g], "live_CALIBRATION_A": {"1x2": 1.070, "btts": 1.003, "ou25": 1.028, "team_total": 0.980}[g]} for g in L.GROUPS]
    pd.DataFrame(rows).round(4).to_csv(os.path.join(ROOT, "validation", "sloy_kalibraciq_20261001.csv"), index=False)
    pd.DataFrame([{"code": c, "b_early": v} for c, v in base.items()]).round(6).to_csv(os.path.join(ROOT, "validation", "sloy_kalibraciq_base_20261001.csv"), index=False)
    print(pd.DataFrame(rows).round(4).to_string(index=False))


if __name__ == "__main__":
    main()
