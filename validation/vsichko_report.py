"""validation/vsichko_report.py - ZADACHA_VSICHKO т.5: отчет за всичко показано (SHOW_ALL) след седмица.

Чете extra_markets_log (predictions.db, първата показана стойност на мач и пазар) и урежда всеки ред срещу реалния изход от живите файлове:
  голове (90 мин) и полувреме - {лига}_fixtures.csv (ft_home/ft_away, ht_home/ht_away); пръв гол - {лига}_events.csv (по event_index,
  автоголът е за противника); корнери и картони (жълти + червени) - {лига}_stats_full.csv.
По пазар (група изходи) и по лига: брой уредени мачове, Brier на модела срещу простата честота (b = честотата на изхода в същата лига
през последните 365 дни преди 02.10.2026, от същите файлове), калибрация a = Σ(p−b)(y−b)/Σ(p−b)², 95% интервал на разликата (bootstrap по мач).
Под 30 уредени мача - "малко данни", без заключение.
Изход: validation/vsichko_<дата>.md (+ _po_liga.csv). Употреба: venv/bin/python3 validation/vsichko_report.py [--date 20261012]
"""
import os
import re
import sqlite3
import sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal", "champions_league", "europa_league",
           "conference_league", "france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
MIN_N = 30
BASE_FROM, BASE_TO = datetime(2025, 10, 2).timestamp(), datetime(2026, 10, 2).timestamp()


def market_of(code):
    """Код -> (пазар, изход). Пазарът групира изходите, които се събират до 100%."""
    m = re.match(r"^(cornall|cardall):(total|home|away)_(over|under)_([\d.]+)$", code)
    if m:
        return f"{m[1]}:{m[2]}_{m[4]}", m[3]
    m = re.match(r"^corners_(total|home|away)_(over|under)_([\d.]+)$", code)
    if m:
        return f"corners:{m[1]}_{m[3]}", m[2]
    for pref, mk in (("cs:", "точен резултат"), ("ht:", "полувреме"), ("first:", "пръв гол"), ("htftall:", "полувреме/край"),
                     ("htft:", "полувреме/край (топ 4)"), ("dc_", "двоен шанс")):
        if code.startswith(pref):
            return mk, code
    pairs = {"home_win": "1x2", "draw": "1x2", "away_win": "1x2", "btts_yes": "btts", "btts_no": "btts",
             "home_clean_sheet": "чиста мрежа домакин", "away_clean_sheet": "чиста мрежа гост"}
    if code in pairs:
        return pairs[code], code
    m = re.match(r"^(home_|away_)?(over|under)(\d)(\d)$", code)
    if m:
        return f"{(m[1] or 'total_')}{m[3]}.{m[4]}", m[2]
    return code, code


def outcomes():
    """fixture_id -> dict с реалните стойности (hg, ag, hth, hta, first ('h'/'a'/None), hc, ac, hcd, acd); ts по мач."""
    res = {}
    for lg in LEAGUES:
        fp = os.path.join(ROOT, f"{lg}_fixtures.csv")
        if not os.path.exists(fp):
            continue
        fx = pd.read_csv(fp, low_memory=False).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
        fx = fx[fx["status"].isin(["FT", "AET", "PEN"])]
        for r in fx.itertuples():
            hg = r.ft_home if pd.notna(r.ft_home) else r.home_goals
            ag = r.ft_away if pd.notna(r.ft_away) else r.away_goals
            if pd.isna(hg) or pd.isna(ag):
                continue
            res[int(r.fixture_id)] = {"league": lg, "ts": r.timestamp, "home_id": r.home_id, "hg": int(hg), "ag": int(ag),
                                      "hth": r.ht_home, "hta": r.ht_away}
        ep = os.path.join(ROOT, f"{lg}_events.csv")
        if os.path.exists(ep):
            ev = pd.read_csv(ep, low_memory=False, usecols=["fixture_id", "event_index", "team_id", "type", "detail"])
            ev = ev[(ev["type"] == "Goal") & (ev["detail"] != "Missed Penalty")].sort_values(["fixture_id", "event_index"])
            for fid, g in ev.groupby("fixture_id"):
                o = res.get(int(fid))
                if o is None or len(g) != o["hg"] + o["ag"]:
                    continue
                t, d = int(g.iloc[0]["team_id"]), g.iloc[0]["detail"]
                o["first"] = "h" if (t == o["home_id"]) != (d == "Own Goal") else "a"
        sp = os.path.join(ROOT, f"{lg}_stats_full.csv")
        if os.path.exists(sp):
            st = pd.read_csv(sp, low_memory=False).drop_duplicates(["fixture_id", "team_id"])
            for fid, g in st.groupby("fixture_id"):
                o = res.get(int(fid))
                if o is None or len(g) != 2:
                    continue
                for side, row in (("h", g[g["team_id"] == o["home_id"]]), ("a", g[g["team_id"] != o["home_id"]])):
                    if len(row) != 1:
                        continue
                    row = row.iloc[0]
                    c = pd.to_numeric(row.get("Corner_Kicks"), errors="coerce")
                    y = pd.to_numeric(row.get("Yellow_Cards"), errors="coerce")
                    rd = pd.to_numeric(row.get("Red_Cards"), errors="coerce")
                    o[f"{side}c"] = None if pd.isna(c) else float(c)
                    o[f"{side}cd"] = None if pd.isna(y) else float(y) + (0.0 if pd.isna(rd) else float(rd))
    return res


def hit(code, o):
    """1/0 за изхода или None (не може да се уреди)."""
    hg, ag = o["hg"], o["ag"]
    m = re.match(r"^(cornall|cardall):(total|home|away)_(over|under)_([\d.]+)$", code) or \
        re.match(r"^(corners)_(total|home|away)_(over|under)_([\d.]+)$", code)
    if m:
        k = "c" if m[1] in ("cornall", "corners") else "cd"
        h, a = o.get(f"h{k}"), o.get(f"a{k}")
        v = {"total": None if h is None or a is None else h + a, "home": h, "away": a}[m[2]]
        if v is None:
            return None
        return float(v > float(m[4])) if m[3] == "over" else float(v <= float(m[4]))
    if code.startswith("cs:"):
        if code == "cs:other":
            return float(not (hg <= 3 and ag <= 3))
        i, j = map(int, code[3:].split("-"))
        return float(hg == i and ag == j)
    if code.startswith(("ht:", "htftall:", "htft:")):
        if pd.isna(o["hth"]) or pd.isna(o["hta"]):
            return None
        sign = lambda a, b: "1" if a > b else "X" if a == b else "2"  # noqa: E731
        ht, ft = sign(o["hth"], o["hta"]), sign(hg, ag)
        if code.startswith("ht:"):
            return float(code[3:] == ht)
        return float(code.split(":", 1)[1] == f"{ht}/{ft}")
    if code.startswith("first:"):
        if hg + ag == 0:
            return float(code == "first:none")
        f = o.get("first")
        if f is None:
            return None
        return float(code == ("first:home" if f == "h" else "first:away"))
    simple = {"home_win": hg > ag, "draw": hg == ag, "away_win": hg < ag, "dc_1x": hg >= ag, "dc_x2": hg <= ag, "dc_12": hg != ag,
              "btts_yes": hg >= 1 and ag >= 1, "btts_no": not (hg >= 1 and ag >= 1), "home_clean_sheet": ag == 0, "away_clean_sheet": hg == 0}
    if code in simple:
        return float(simple[code])
    m = re.match(r"^(home_|away_)?(over|under)(\d)(\d)$", code)
    if m:
        v = hg if m[1] == "home_" else ag if m[1] == "away_" else hg + ag
        line = float(f"{m[3]}.{m[4]}")
        return float(v > line) if m[2] == "over" else float(v <= line)
    return None


def boot(x, n=2000, seed=42):
    x = np.asarray(x)
    idx = np.random.default_rng(seed).integers(0, len(x), size=(n, len(x)))
    m = x[idx].mean(1)
    return float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    stamp = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else datetime.utcnow().strftime("%Y%m%d")
    db = sys.argv[sys.argv.index("--db") + 1] if "--db" in sys.argv else os.path.join(ROOT, "predictions.db")
    con = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    log = pd.read_sql_query("select * from extra_markets_log", con)
    con.close()
    res = outcomes()
    log["y"] = [hit(c, res[f]) if f in res else None for f, c in zip(log["fixture_id"], log["market_code"])]
    log[["market", "outcome"]] = [market_of(c) for c in log["market_code"]]
    settled = log.dropna(subset=["y"]).copy()
    settled["p"] = settled["pick_pct"] / 100.0
    # проста честота: същата лига, последната година преди 02.10.2026
    base_rows = [(f, o) for f, o in res.items() if BASE_FROM <= (o["ts"] or 0) < BASE_TO]
    base = {}
    for lg, code in settled[["league", "market_code"]].drop_duplicates().itertuples(index=False):
        ys = [hit(code, o) for f, o in base_rows if o["league"] == lg]
        ys = [y for y in ys if y is not None]
        base[(lg, code)] = float(np.mean(ys)) if ys else np.nan
    settled["b"] = [base[(lg, c)] for lg, c in zip(settled["league"], settled["market_code"])]
    settled = settled.dropna(subset=["b"])

    def summarize(g):
        per_match = g.groupby("fixture_id").apply(lambda d: pd.Series({"bm": ((d.p - d.y) ** 2).mean(), "bb": ((d.b - d.y) ** 2).mean()}))
        n = len(per_match)
        den = ((g.p - g.b) ** 2).sum()
        a = float(((g.p - g.b) * (g.y - g.b)).sum() / den) if den > 0 else np.nan
        if n < MIN_N:
            return {"n": n, "brier": per_match.bm.mean(), "brier_b": per_match.bb.mean(), "d": np.nan, "lo": np.nan, "hi": np.nan, "a": a,
                    "извод": "малко данни"}
        d = boot((per_match.bm - per_match.bb).to_numpy())
        good = d[2] < 0 and 0.9 <= a <= 1.1
        bad = d[1] > 0 or not (0.8 <= a <= 1.2)
        return {"n": n, "brier": per_match.bm.mean(), "brier_b": per_match.bb.mean(), "d": d[0], "lo": d[1], "hi": d[2], "a": a,
                "извод": "добре" if good else "зле" if bad else "неясно"}

    by_market = pd.DataFrame([{"пазар": mk, **summarize(g)} for mk, g in settled.groupby("market")]).sort_values("пазар")
    by_ml = pd.DataFrame([{"пазар": mk, "лига": lg, **summarize(g)} for (mk, lg), g in settled.groupby(["market", "league"])])
    if "--out" not in sys.argv:
        by_ml.round(5).to_csv(os.path.join(ROOT, "validation", f"vsichko_{stamp}_po_liga.csv"), index=False)
    first, last = log["logged_at"].min(), log["logged_at"].max()
    L = [f"# Всичко на сайта — отчет {stamp[6:8]}.{stamp[4:6]}.{stamp[:4]}", "",
         f"Дневник `extra_markets_log`: {len(log)} реда (мач × изход), {log['fixture_id'].nunique()} мача, записани {first} → {last}.",
         f"Уредени: {len(settled)} реда, {settled['fixture_id'].nunique()} мача. Проста честота b — същата лига, 02.10.2025–01.10.2026.",
         f"Под {MIN_N} уредени мача — „малко данни“, без заключение. „Добре“ = значимо по-нисък Brier от честотата И a в 0.9–1.1; "
         "„зле“ = значимо по-висок или a извън 0.8–1.2; иначе „неясно“.", "",
         "## По пазар", "", "| пазар | мачове | Brier | Brier честота | разлика [95%] | a | извод |", "|---|---|---|---|---|---|---|"]
    for r in by_market.itertuples():
        di = "—" if np.isnan(r.d) else f"{r.d:+.4f} [{r.lo:+.4f}; {r.hi:+.4f}]"
        L.append(f"| {r.пазар} | {r.n} | {r.brier:.4f} | {r.brier_b:.4f} | {di} | {r.a:.2f} | {r.извод} |")
    L += ["", f"## По пазар и лига — само комбинациите с ≥ {MIN_N} мача (всички: `vsichko_{stamp}_po_liga.csv`)", "",
          "| пазар | лига | мачове | Brier | Brier честота | a | извод |", "|---|---|---|---|---|---|---|"]
    for r in by_ml[by_ml.n >= MIN_N].sort_values(["пазар", "лига"]).itertuples():
        L.append(f"| {r.пазар} | {r.лига} | {r.n} | {r.brier:.4f} | {r.brier_b:.4f} | {r.a:.2f} | {r.извод} |")
    L += ["", "Неуредени (мачът не е изигран/няма данни за изхода): " + str(len(log) - len(log.dropna(subset=["y"]))) + " реда.", ""]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(ROOT, "validation", f"vsichko_{stamp}.md")
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
