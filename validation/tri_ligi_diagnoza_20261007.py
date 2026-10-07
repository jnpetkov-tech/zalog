"""validation/tri_ligi_diagnoza_20261007.py - ЗАЩО bulgaria2 / england2 / france2 са по-зле от пазара (само диагноза, моделът не се пипа).

Данни:
  - вероятностите по мач на ядрото и на живия слой AB (walk-forward, без да са виждали мача): validation/kalibraciq2_20261007_layer.csv.gz,
    през същата матрица и калибрация като на живо (final_v_20260924.goal_probs / live_calibrate);
  - пазарът: обезвиговани коефициенти от лога (validation/model_vs_market.build_rows(), без суровите групи), уредени мачове;
  - без пазар (всички мачове от мерилото, късна половина >= 2025-09-23): колко добро е ядрото/слоят по лига спрямо простия базов процент.
Разбивки за трите лиги: по пазар; средно обещано/пазар/реално по изход (накъдето бъркаме); нови в лигата отбори (< 10 мача в лигата преди
мача в данните) срещу утвърдени; мачове с голямо разминаване с пазара - кой е по-близо.
Изход: validation/tri_ligi_diagnoza_20261007.md (+ _market.csv, _rows.csv). Употреба: venv/bin/python3 validation/tri_ligi_diagnoza_20261007.py
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
os.chdir(ROOT)

import final_v_20260924 as fv  # noqa: E402
import model_vs_market as mvm  # noqa: E402

THREE = ["bulgaria2", "england2", "france2"]
LATE = "2025-09-23"
OUT = os.path.join(ROOT, "validation", "tri_ligi_diagnoza_20261007")
NEW_TEAM_N = 10
BIG_GAP = 0.08


def probs_for(t, lam_c, mu_c):
    P = fv.goal_probs(t[lam_c].to_numpy(), t[mu_c].to_numpy(), t["rho"].to_numpy())
    P = pd.DataFrame({c: P[c] for c in fv.GOAL_CODES if c in P})
    return fv.live_calibrate(P)


def team_experience(t):
    """Брой мачове на отбора в СЪЩАТА лига преди мача (по данните в таблицата, от 2023-08 нататък)."""
    fx = pd.concat([pd.read_csv(f"{lg}_fixtures.csv", usecols=["fixture_id", "home_id", "away_id", "timestamp", "fetched_at"],
                                low_memory=False).assign(league=lg)
                    for lg in t["league"].unique() if os.path.exists(f"{lg}_fixtures.csv")])
    fx = fx.sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    t = t.merge(fx[["fixture_id", "home_id", "away_id"]], on="fixture_id", how="left")
    seen, nh, na = {}, [], []
    for r in t.sort_values(["date", "fixture_id"]).itertuples():
        kh, ka = (r.league, r.home_id), (r.league, r.away_id)
        nh.append(seen.get(kh, 0))
        na.append(seen.get(ka, 0))
        seen[kh] = seen.get(kh, 0) + 1
        seen[ka] = seen.get(ka, 0) + 1
    s = t.sort_values(["date", "fixture_id"]).assign(n_home=nh, n_away=na)
    return t.merge(s[["fixture_id", "n_home", "n_away"]], on="fixture_id")


def ci_line(d, fx):
    m, lo, hi = fv.boot_ci(d, fx)
    sig = "пазарът по-добър" if lo > 0 else ("ние по-добри" if hi < 0 else "в шума")
    return m, lo, hi, sig


def main():
    t = pd.read_csv("validation/kalibraciq2_20261007_layer.csv.gz")
    t = team_experience(t)
    Y = fv.goal_outcomes(t["hg"].to_numpy(), t["ag"].to_numpy())
    Pc, Pa = probs_for(t, "lam", "mu"), probs_for(t, "lam_AB", "mu_AB")
    key = {(lg, fx): i for i, (lg, fx) in enumerate(zip(t["league"], t["fixture_id"]))}

    # --- срещу пазара
    detail, _ = mvm.build_rows()
    rows = []
    for d in detail:
        if d["raw_implied"]:
            continue
        i = key.get((d["league"], d["fixture_id"]))
        if i is None or d["code"] not in Pa.columns:
            continue
        rows.append({"fixture_id": d["fixture_id"], "league": d["league"], "date": t["date"].iloc[i], "group": d["group"],
                     "code": d["code"], "y": d["y"], "market": d["market"], "core": float(Pc[d["code"]].iloc[i]),
                     "ab": float(Pa[d["code"]].iloc[i]), "n_home": t["n_home"].iloc[i], "n_away": t["n_away"].iloc[i]})
    mk = pd.DataFrame(rows)
    chk = np.array([Y[r.code].iloc[key[(r.league, r.fixture_id)]] for r in mk.itertuples()])
    assert (chk == mk["y"].to_numpy()).all(), "изходът от лога се разминава с резултата"
    mk["e_m"] = (mk.market - mk.y) ** 2
    mk["e_c"] = (mk.core - mk.y) ** 2
    mk["e_a"] = (mk.ab - mk.y) ** 2
    mk["new_team"] = (mk[["n_home", "n_away"]].min(axis=1) < NEW_TEAM_N)
    mk.round(5).to_csv(OUT + "_rows.csv", index=False)

    res = []
    for lvl, parts in (("всички", [("всички", mk)]), ("лига", list(mk.groupby("league")))):
        for nm, s in parts:
            for who, col in (("ядро", "e_c"), ("слой AB (на живо)", "e_a")):
                m, lo, hi, sig = ci_line((s[col] - s.e_m).to_numpy(), s.fixture_id.to_numpy())
                res.append({"level": lvl, "name": nm, "model": who, "rows": len(s), "matches": s.fixture_id.nunique(),
                            "brier_market": s.e_m.mean(), "brier_model": s[col].mean(), "diff": m, "lo": lo, "hi": hi,
                            "rel_pct": 100 * m / s.e_m.mean(), "verdict": sig})
    res = pd.DataFrame(res)
    res.round(5).to_csv(OUT + "_market.csv", index=False)

    L = ["# Защо bulgaria2 / england2 / france2 са по-зле от пазара — диагноза, 07.10.2026", "",
         "Само измерване — моделът, `football_lib.py`, `prediction_policy.py` и живият код не са пипани.",
         "Скрипт: `validation/tri_ligi_diagnoza_20261007.py`. Вероятностите по мач: walk-forward (`kalibraciq2_20261007_layer.csv.gz`) — "
         "ядро и живият слой AB, с калибрацията от живия код. Пазарът: обезвиговани коефициенти от лога (`model_vs_market.build_rows`).",
         f"Разлика = грешката ни (Brier) минус тази на пазара; плюс = пазарът по-точен. Интервал 95% bootstrap по мач. "
         f"Мачове с пазар: {mk.fixture_id.nunique()} (до {mk.date.max()}).", "",
         "## 1. Срещу пазара по лига (слоят AB = живата прогноза)", "",
         "| лига | мачове | ядро − пазар | слой − пазар | 95% (слой) | отн. | присъда |", "|---|---|---|---|---|---|---|"]
    ra = res[res.model == "слой AB (на живо)"].set_index("name")
    rc = res[res.model == "ядро"].set_index("name")
    for nm in ["всички"] + sorted(ra.index.drop("всички"), key=lambda x: -ra.loc[x, "rel_pct"]):
        a, c = ra.loc[nm], rc.loc[nm]
        b = "**" if nm in THREE else ""
        L.append(f"| {b}{nm}{b} | {a.matches} | {c['diff']:+.4f} | {a['diff']:+.4f} | [{a.lo:+.4f}; {a.hi:+.4f}] | "
                 f"{a.rel_pct:+.1f}% | {a.verdict} |")

    # --- без пазар: умение спрямо базовия процент, късна половина, по лига
    late = (t["date"] >= LATE).to_numpy()
    codes = [c for c in fv.bf.CODES if c in Pa.columns]
    base_rate = Y[codes][~late].mean()
    sk = []
    for lg in sorted(t.league.unique()):
        m = late & (t.league == lg).to_numpy()
        if m.sum() < 50:
            continue
        bb = ((Y[codes][m] - base_rate) ** 2).to_numpy().mean()
        bc = ((Y[codes][m] - Pc[codes][m]) ** 2).to_numpy().mean()
        ba = ((Y[codes][m] - Pa[codes][m]) ** 2).to_numpy().mean()
        sk.append({"league": lg, "n": int(m.sum()), "skill_core": 100 * (1 - bc / bb), "skill_ab": 100 * (1 - ba / bb),
                   "o25_real": 100 * Y["over25"][m].mean(), "o25_ab": 100 * Pa["over25"][m].mean(),
                   "home_real": 100 * Y["home_win"][m].mean(), "home_ab": 100 * Pa["home_win"][m].mean(),
                   "draw_real": 100 * Y["draw"][m].mean(), "draw_ab": 100 * Pa["draw"][m].mean()})
    sk = pd.DataFrame(sk).sort_values("skill_ab")
    L += ["", "## 2. Без пазар: колко моделът изобщо „вижда“ в лигата (късна половина, всички мачове)", "",
          "Умение = с колко % грешката е по-малка от простото „винаги средния процент“ (11 изхода на голове). Ниско = лигата е по-трудна "
          "за модела или моделът е по-слаб там.", "",
          "| лига | мачове | умение ядро | умение слой | над 2.5 реално / слой | домакин реално / слой | равен реално / слой |",
          "|---|---|---|---|---|---|---|"]
    for r in sk.itertuples():
        b = "**" if r.league in THREE else ""
        L.append(f"| {b}{r.league}{b} | {r.n} | {r.skill_core:.1f}% | {r.skill_ab:.1f}% | {r.o25_real:.1f} / {r.o25_ab:.1f} | "
                 f"{r.home_real:.1f} / {r.home_ab:.1f} | {r.draw_real:.1f} / {r.draw_ab:.1f} |")

    # --- трите лиги в подробности
    L += ["", "## 3. Трите лиги в подробности (редовете с пазар)", ""]
    for lg in THREE:
        s = mk[mk.league == lg]
        if s.empty:
            continue
        L += [f"### {lg} — {s.fixture_id.nunique()} мача, {len(s)} реда", "", "**По пазар (слой − пазар):**", "",
              "| пазар | редове | слой − пазар | 95% | присъда |", "|---|---|---|---|---|"]
        for g, gs in s.groupby("group"):
            m, lo, hi, sig = ci_line((gs.e_a - gs.e_m).to_numpy(), gs.fixture_id.to_numpy())
            L.append(f"| {fv.GN.get(g, g)} | {len(gs)} | {m:+.4f} | [{lo:+.4f}; {hi:+.4f}] | {sig} |")
        L += ["", "**Накъде бъркаме (средно, %):** обещано от нас / от пазара / реално", "", "| изход | редове | ние | пазар | реално |",
              "|---|---|---|---|---|"]
        for code in ["home_win", "draw", "away_win", "over25", "under25", "btts_yes", "home_over15", "away_over15"]:
            cs = s[s.code == code]
            if len(cs) >= 10:
                L.append(f"| {code} | {len(cs)} | {100 * cs.ab.mean():.1f} | {100 * cs.market.mean():.1f} | {100 * cs.y.mean():.1f} |")
        nw = s[s.new_team]
        old = s[~s.new_team]
        L += ["", f"**Нови в лигата отбори** (поне един отбор с < {NEW_TEAM_N} мача в лигата преди мача):", ""]
        for nm, part in (("с нов отбор", nw), ("само утвърдени", old)):
            if part.fixture_id.nunique() >= 5:
                m, lo, hi, sig = ci_line((part.e_a - part.e_m).to_numpy(), part.fixture_id.to_numpy())
                L.append(f"- {nm}: {part.fixture_id.nunique()} мача, слой − пазар {m:+.4f} [{lo:+.4f}; {hi:+.4f}] — {sig}")
            else:
                L.append(f"- {nm}: {part.fixture_id.nunique()} мача — твърде малко")
        big = s[(s.ab - s.market).abs() >= BIG_GAP]
        if len(big):
            closer_m = int(((big.market - big.y).abs() < (big.ab - big.y).abs()).sum())
            L += ["", f"**Голямо разминаване с пазара** (≥ {int(BIG_GAP * 100)} пункта): {len(big)} реда от {len(s)}; пазарът по-близо в "
                  f"{closer_m}, ние — в {len(big) - closer_m}. Грешка там: ние {big.e_a.mean():.4f}, пазар {big.e_m.mean():.4f}. "
                  f"Средно над пазара: {100 * (big.ab - big.market).mean():+.1f} пункта.", ""]
            for code, cs in big.groupby("code"):
                if len(cs) >= 5:
                    L.append(f"- {code}: {len(cs)} реда, ние {100 * cs.ab.mean():.1f}%, пазар {100 * cs.market.mean():.1f}%, реално {100 * cs.y.mean():.1f}%")
        L.append("")
    open(OUT + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
