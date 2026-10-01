"""features/layer_shadow_report.py - седмичен отчет на режима "в сянка" (ZADACHA_SYANKA 2.4, 01.10.2026).

За УРЕДЕНИТЕ мачове с запис в layer_shadow (predictions.db): ядро сам срещу ядро+слой - Brier (11 изхода на мерилото), log-loss (1X2, над/под 2.5,
двата вкарват), коефициент на калибрация (b - честотата на ранната половина на мерилото, validation/sloy_kalibraciq_base_20261001.csv), по лиги,
с 95% интервали (bootstrap по мач, 2000, seed 42). ОТДЕЛНО pre (набор AB, последният запис преди началото) и final (набор ABC, след съставите).
England - отделна секция. Пазарът (първият наличен коефициент от predictions_log, обезвигован) - само справка.
Първият отчет - когато има поне MIN_SETTLED уредени мача; иначе излиза без файл. Записите са излезли ПРЕДИ мачовете (out-of-sample).
Изход: validation/syanka_<дата>.md. Употреба: venv/bin/python3 features/layer_shadow_report.py [--force]   (crontab: понеделник сутрин)
"""
import json
import os
import sqlite3
import sys
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from features import layer_lib as L  # noqa: E402

MIN_SETTLED = 150
FINISHED = {"FT", "AET", "PEN"}
LEAGUES = L.ALL_LEAGUES_17


def load_results():
    parts = [pd.read_csv(f"{l}_fixtures.csv", low_memory=False) for l in LEAGUES if os.path.exists(f"{l}_fixtures.csv")]
    fx = pd.concat(parts).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["status"].isin(FINISHED)]
    g = fx["ft_home"].where(fx["ft_home"].notna(), fx["home_goals"]), fx["ft_away"].where(fx["ft_away"].notna(), fx["away_goals"])
    return pd.DataFrame({"fixture_id": fx["fixture_id"].astype(int), "hg": pd.to_numeric(g[0], errors="coerce"), "ag": pd.to_numeric(g[1], errors="coerce")}).dropna()


def load_shadow(res):
    con = sqlite3.connect("file:predictions.db?mode=ro", uri=True)
    d = pd.read_sql_query("select * from layer_shadow", con)
    d = d[d["computed_at"].str.replace("T", " ") < pd.to_datetime(d["kickoff_ts"], unit="s").dt.strftime("%Y-%m-%d %H:%M:%S")]   # само преди началото
    d = d.sort_values("computed_at").groupby(["fixture_id", "mode"]).tail(1)                                                       # последният преди началото
    return d.merge(res, on="fixture_id", how="inner"), con


def market_reference(con, fixtures):
    od = pd.read_sql_query("select fixture_id, market_code, market_odds from predictions_log where market_odds is not null", con)
    od = od[od["fixture_id"].isin(fixtures)].groupby(["fixture_id", "market_code"])["market_odds"].first().unstack()
    out = {}
    for fx, r in od.iterrows():
        rec = {}
        for codes in (["home_win", "draw", "away_win"], ["over25", "under25"], ["btts_yes", "btts_no"]):
            if all(c in r.index and pd.notna(r[c]) for c in codes):
                inv = np.array([1.0 / r[c] for c in codes])
                rec.update(dict(zip(codes, inv / inv.sum())))
        out[int(fx)] = rec
    return out


def section(title, d, base, mk):
    P0 = pd.DataFrame([json.loads(x) for x in d["probs_core"]])[L.CODES]
    P1 = pd.DataFrame([json.loads(x) for x in d["probs_layer"]])[L.CODES]
    Y = L.y_matrix(d["hg"], d["ag"])
    b0, b1 = L.brier_match(P0, Y), L.brier_match(P1, Y)
    l0, l1 = L.logloss_match(P0, Y), L.logloss_match(P1, Y)
    ll0, ll1 = np.mean(list(l0.values()), axis=0), np.mean(list(l1.values()), axis=0)
    dB, dL = L.boot_ci(b1 - b0), L.boot_ci(ll1 - ll0)
    f = lambda x: f"{x:.5f}"
    sg = lambda lo, hi: "значимо по-добре" if hi < 0 else "значимо по-зле" if lo > 0 else "в рамките на шума"
    out = [f"## {title}", "", f"Уредени мачове: **{len(d)}** (версии на слоя: {', '.join(sorted(d['layer_version'].unique()))}).", "",
           "| мярка | ядро сам | ядро + слой | разлика (слой − ядро) | 95% | |", "|---|---|---|---|---|---|",
           f"| Brier, 11 изхода | {f(b0.mean())} | {f(b1.mean())} | {dB[0]:+.5f} | [{dB[1]:+.5f}; {dB[2]:+.5f}] | {sg(dB[1], dB[2])} |",
           f"| log-loss (1X2, над/под, двата вкарват) | {f(ll0.mean())} | {f(ll1.mean())} | {dL[0]:+.5f} | [{dL[1]:+.5f}; {dL[2]:+.5f}] | {sg(dL[1], dL[2])} |"]
    for g in L.GROUPS:
        idx = [i for i, c in enumerate(L.CODES) if L.GROUP_OF[c] == g]
        x0, x1 = ((P0.to_numpy()[:, idx] - Y[:, idx]) ** 2).mean(1), ((P1.to_numpy()[:, idx] - Y[:, idx]) ** 2).mean(1)
        dd = L.boot_ci(x1 - x0)
        out.append(f"| Brier {g} | {f(x0.mean())} | {f(x1.mean())} | {dd[0]:+.5f} | [{dd[1]:+.5f}; {dd[2]:+.5f}] | {sg(dd[1], dd[2])} |")
    a0, a1 = L.calib_coef(P0, Y, base), L.calib_coef(P1, Y, base)
    out += ["", "Коефициент на калибрация (рамка 0.9–1.1): " + "; ".join(f"{g} {a0[g]:.3f} → {a1[g]:.3f}" for g in L.GROUPS) + " (ядро → ядро+слой).", "",
            "По лиги (Brier, 11 изхода):", "", "| лига | мачове | ядро | слой | разлика | 95% | |", "|---|---|---|---|---|---|---|"]
    lg = d["league"].to_numpy()
    for league in sorted(set(lg)):
        m = lg == league
        if m.sum() < 10:
            out.append(f"| {league} | {int(m.sum())} | — | — | (под 10 мача) | | |")
            continue
        dm = L.boot_ci((b1 - b0)[m])
        out.append(f"| {league} | {int(m.sum())} | {f(b0[m].mean())} | {f(b1[m].mean())} | {dm[0]:+.5f} | [{dm[1]:+.5f}; {dm[2]:+.5f}] | {sg(dm[1], dm[2])} |")
    # справка: пазар
    rows = []
    for i, fid in enumerate(d["fixture_id"]):
        rec = mk.get(int(fid), {})
        for g, codes in (("1x2", ["home_win", "draw", "away_win"]), ("ou25", ["over25", "under25"]), ("btts", ["btts_yes", "btts_no"])):
            if all(c in rec for c in codes):
                ys = [Y[i, L.CODES.index(c)] for c in codes]
                rows.append({"fx": fid, "core": np.mean([(P0.iloc[i][c] - y) ** 2 for c, y in zip(codes, ys)]),
                             "layer": np.mean([(P1.iloc[i][c] - y) ** 2 for c, y in zip(codes, ys)]),
                             "market": np.mean([(rec[c] - y) ** 2 for c, y in zip(codes, ys)])})
    if rows:
        mdf = pd.DataFrame(rows).groupby("fx").mean()
        d0, d1 = L.boot_ci((mdf["core"] - mdf["market"]).to_numpy()), L.boot_ci((mdf["layer"] - mdf["market"]).to_numpy())
        out += ["", f"Справка — пазарът (не е в обучението), {len(mdf)} мача с коефициенти: разлика с пазара (положително = пазарът е по-точен): ядро {d0[0]:+.5f} "
                    f"[{d0[1]:+.5f}; {d0[2]:+.5f}], ядро+слой {d1[0]:+.5f} [{d1[1]:+.5f}; {d1[2]:+.5f}]."]
    out.append("")
    return out


def main():
    res = load_results()
    d, con = load_shadow(res)
    base = dict(pd.read_csv("validation/sloy_kalibraciq_base_20261001.csv").set_index("code")["b_early"])
    pre, fin = d[d["mode"] == "pre"], d[d["mode"] == "final"]
    n_pre = len(pre)
    print(f"уредени: pre {n_pre}, final {len(fin)}")
    if n_pre < MIN_SETTLED and "--force" not in sys.argv:
        print(f"под {MIN_SETTLED} уредени мача с 'pre' - няма отчет")
        return
    mk = market_reference(con, set(d["fixture_id"]))
    L_ = [f"# Режим „в сянка“ на слоя — седмичен отчет — {datetime.utcnow().strftime('%d.%m.%Y')}", "",
          "Скрипт: `features/layer_shadow_report.py`. Данни: `layer_shadow` в `predictions.db` (записите са излезли ПРЕДИ мачовете; последният преди началото на всеки мач). "
          "Нищо публично не е променено. Критерият от `validation/sloy_nastroyki_20261001.md` се прилага върху тези нови мачове.", "",
          f"Записани мачове: pre {int(d[d['mode']=='pre']['fixture_id'].nunique())}, final {int(d[d['mode']=='final']['fixture_id'].nunique())}; уредени: pre {n_pre}, final {len(fin)}.", ""]
    if n_pre:
        L_ += section("pre (набор AB, преди състав)", pre, base, mk)
    if len(fin) >= 20:
        L_ += section("final (набор ABC, след състав)", fin, base, mk)
    else:
        L_ += ["## final (набор ABC)", "", f"Още малко уредени мача ({len(fin)}) — без таблица.", ""]
    for name, dd in (("england (отделно)", pre[pre["league"] == "england"]),):
        L_ += [f"## {name}", ""]
        L_ += section("england — pre", dd, base, mk)[1:] if len(dd) >= 10 else [f"Само {len(dd)} уредени мача — недостатъчно за таблица.", ""]
        fe = fin[fin["league"] == "england"]
        if len(fe) >= 10:
            L_ += section("england — final", fe, base, mk)
    out = os.path.join(ROOT, "validation", f"syanka_{datetime.utcnow().strftime('%Y%m%d')}.md")
    open(out, "w", encoding="utf-8").write("\n".join(L_) + "\n")
    print("записан", out)


if __name__ == "__main__":
    main()
