"""
validation/calibration_fit.py - ZADACHA_MERILO.md, ЧАСТ В (23.09.2026).

Само измерване. prediction_policy.calibrate() и живият код - непипнати.

Вход: validation/backtest_full_<ТАГ>_matches.csv (ЧАСТ А - walk-forward
вероятности на сегашния модел за всеки мач от последните 2 години).

=== МЕТОД ===
1. Обещано срещу познато: всеки ред мач x изход (11 изхода на мач, виж
   backtest_full.CODES) пада в лента по обещания процент (0-10%, ...,
   90-100%); за всяка лента - n, средно обещано, реално познато. По
   пазарна група и по лига.
2. Калибрация "свиване към базовата честота", ПО ЕДИН ПАРАМЕТЪР НА ГРУПА:
       p' = b + a * (p - b)
   b = честотата на изхода (по код, напр. over25) в ПО-РАННАТА част,
   a = едно число за групата (1x2, ou25, btts, team_total), най-малки
   квадрати върху по-ранната част: a = sum((p-b)(y-b)) / sum((p-b)^2).
   a < 1 = моделът е прекалено уверен (свиваме), a > 1 = прекалено плах.
   Сумата на 1X2 и двойките (над/под и т.н.) остава 1, защото b-тата се
   сумират до 1.
3. Разделяне по време: по-ранна част = мачове с дата < медианната дата на
   всички мачове; по-късна = останалите. a и b се учат само от
   по-ранната и се прилагат БЕЗ преизбор върху по-късната.
4. Резултат: Brier на по-късната част преди/след, по група, по лига и
   общо; 95% интервал на разликата - сдвоен bootstrap по мач, 2000, seed 42.

Изход: validation/calibration_fit_<ДАТА>.md и .csv
"""
import argparse
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

from backtest_full import long_form, LEAGUES  # noqa: E402

BANDS = np.linspace(0, 1, 11)


def boot_ci(df, a, b):
    per = df.assign(d=(df[a] - df["y"]) ** 2 - (df[b] - df["y"]) ** 2).groupby("fixture_id")["d"].agg(["sum", "size"])
    s, c = per["sum"].to_numpy(), per["size"].to_numpy()
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(s), size=(2000, len(s)))
    v = s[idx].sum(1) / c[idx].sum(1)
    return np.percentile(v, [2.5, 97.5])


def reliability(lf, by):
    lf = lf.assign(band=pd.cut(lf["p"], BANDS, include_lowest=True, labels=[f"{int(10*i)}-{int(10*i+10)}%" for i in range(10)]))
    return lf.groupby([by, "band"], observed=True).agg(n=("y", "size"), promised=("p", "mean"), hit=("y", "mean")).reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="20260923")
    args = ap.parse_args()
    tag = date.today().strftime("%Y%m%d")
    matches = pd.read_csv(f"validation/backtest_full_{args.src}_matches.csv")
    lf = long_form(matches)
    lf["date"] = pd.to_datetime(lf["date"])
    cut = pd.to_datetime(matches["date"]).median()
    early, late = lf[lf["date"] < cut].copy(), lf[lf["date"] >= cut].copy()

    base = early.groupby("code")["y"].mean()
    params = []
    late["p_cal"] = np.nan
    for g, s in early.groupby("group"):
        b = s["code"].map(base)
        x, y = s["p"] - b, s["y"] - b
        a = float((x * y).sum() / (x * x).sum())
        params.append({"group": g, "a": a, "n_early": len(s)})
        m = late["group"] == g
        bl = late.loc[m, "code"].map(base)
        late.loc[m, "p_cal"] = (bl + a * (late.loc[m, "p"] - bl)).clip(0, 1)
    late["sq"] = (late["p"] - late["y"]) ** 2
    late["sq_cal"] = (late["p_cal"] - late["y"]) ** 2

    res = []
    for lvl, key in (("група", "group"), ("лига", "league")):
        for k, s in late.groupby(key):
            lo, hi = boot_ci(s, "p_cal", "p")
            res.append({"level": lvl, "key": k, "n": len(s), "matches": s["fixture_id"].nunique(),
                        "brier_before": s["sq"].mean(), "brier_after": s["sq_cal"].mean(),
                        "diff": s["sq_cal"].mean() - s["sq"].mean(), "ci_low": lo, "ci_high": hi})
    lo, hi = boot_ci(late, "p_cal", "p")
    res.append({"level": "общо", "key": "ALL", "n": len(late), "matches": late["fixture_id"].nunique(),
                "brier_before": late["sq"].mean(), "brier_after": late["sq_cal"].mean(),
                "diff": late["sq_cal"].mean() - late["sq"].mean(), "ci_low": lo, "ci_high": hi})
    res = pd.DataFrame(res)
    res.round(5).to_csv(f"validation/calibration_fit_{tag}.csv", index=False)
    rel_g = reliability(lf, "group")
    rel_l = reliability(lf, "league")
    rel_g.round(4).to_csv(f"validation/calibration_fit_{tag}_bands_group.csv", index=False)
    rel_l.round(4).to_csv(f"validation/calibration_fit_{tag}_bands_league.csv", index=False)

    allr = res[res.level == "общо"].iloc[0]
    L = [f"# Калибрация на сегашния модел - само измерване - {tag}", "",
         "ZADACHA_MERILO.md, ЧАСТ В. Скрипт: `validation/calibration_fit.py` (методът е в docstring-а).",
         f"Вход: `backtest_full_{args.src}_matches.csv` (ЧАСТ А). `prediction_policy.calibrate()` и живият код",
         "НЕ са пипнати.", "",
         f"Разделяне по време при {cut.date()}: по-ранна част {early['fixture_id'].nunique()} мача (учене), "
         f"по-късна {late['fixture_id'].nunique()} мача (проверка).", "",
         "## Резултат извън извадката (по-късната част)", "",
         f"**Общо: Brier {allr['brier_before']:.5f} → {allr['brier_after']:.5f} "
         f"(разлика {allr['diff']:+.5f}, 95% интервал [{allr['ci_low']:+.5f}, {allr['ci_high']:+.5f}]).**", "",
         "Параметрите (научени само от по-ранната част). p' = b + a·(p − b); a < 1 = моделът е",
         "прекалено уверен и процентите се свиват към базовата честота:", "",
         "| група | a | редове (учене) |", "|---|---|---|"]
    for p in params:
        L.append(f"| {p['group']} | {p['a']:.3f} | {p['n_early']} |")
    L += ["", "| ниво | група/лига | мачове | Brier преди | Brier след | разлика (95% инт.) |", "|---|---|---|---|---|---|"]
    for r in res.itertuples():
        L.append(f"| {r.level} | {r.key} | {r.matches} | {r.brier_before:.5f} | {r.brier_after:.5f} | "
                 f"{r.diff:+.5f} [{r.ci_low:+.5f}, {r.ci_high:+.5f}] |")
    L += ["", "## Обещано срещу познато по ленти (целият период, преди калибрация)", "",
          "Всички редове мач x изход. Близо = честна вероятност; обещано > познато = самоувереност.", "",
          "| група | лента | n | обещано | познато |", "|---|---|---|---|---|"]
    for r in rel_g.itertuples():
        L.append(f"| {r.group} | {r.band} | {r.n} | {100*r.promised:.1f}% | {100*r.hit:.1f}% |")
    L += ["", f"По лига - в `calibration_fit_{tag}_bands_league.csv`. Кратко (лентите 60-100%, където",
          "самоувереността струва най-скъпо):", "", "| лига | n (≥60%) | обещано | познато |", "|---|---|---|---|"]
    hi_ = lf[lf["p"] >= 0.6]
    for lg in LEAGUES:
        s = hi_[hi_.league == lg]
        if len(s):
            L.append(f"| {lg} | {len(s)} | {100*s['p'].mean():.1f}% | {100*s['y'].mean():.1f}% |")
    with open(f"validation/calibration_fit_{tag}.md", "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()
