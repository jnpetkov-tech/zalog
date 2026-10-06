"""validation/tekst_proverka_20261006.py - проверка на текста на мача (ZADACHA_TEKST, 06.10.2026).

1. 30 случайни предстоящи мача от различни лиги (по 2 от лига, seed 20261006) -> целият текст в validation/tekst_primeri_20261006.md.
   + 3 минали мача СЪС съставите (данните отрязани до началото с build_features.truncate) - за изречението "след съставите".
2. Автоматична проверка за всеки текст:
   а) всяко число в текста (без имената на отборите/хората) е сред числата, с които изречението е попълнено (facts);
   б) всяко от тези числа съвпада с НЕЗАВИСИМО пресметнатото тук наново - с отделен прост код върху суровите CSV (pandas, без
      build_features/match_text) и от снимката (predictions_snapshot) за процентите на модела;
   в) забранени думи: букмейкъри, коефициенти, "пазар", залог/залагане, "сигурно", "гарантирано" - в никой текст (всичките 150 мача).
Употреба: venv/bin/python3 validation/tekst_proverka_20261006.py <база с match_text> [--md validation/tekst_primeri_20261006.md]
"""
import glob
import json
import os
import random
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, REPO)
os.chdir(REPO)

LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal", "champions_league", "europa_league",
           "conference_league", "france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
CUPS = {"champions_league", "europa_league", "conference_league"}
BANNED = ["букмейк", "коефициент", "пазар", "залог", "залага", "заложи", "сигурн", "гарантира"]
SEED = 20261006


# ----------------------------------------------------------------------------------------------- независими данни
def load():
    fx = pd.concat([pd.read_csv(f"{l}_fixtures.csv", low_memory=False) for l in LEAGUES if os.path.exists(f"{l}_fixtures.csv")])
    fx = fx.sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["timestamp"].notna()].copy()
    fx["ts"] = fx["timestamp"].astype("int64")
    hg = pd.to_numeric(fx["ft_home"], errors="coerce")
    ag = pd.to_numeric(fx["ft_away"], errors="coerce")
    fx["hg"] = hg.where(hg.notna(), pd.to_numeric(fx["home_goals"], errors="coerce"))
    fx["ag"] = ag.where(ag.notna(), pd.to_numeric(fx["away_goals"], errors="coerce"))
    fx["fin"] = fx["status"].isin(["FT", "AET", "PEN"]) & fx["hg"].notna() & fx["ag"].notna()
    st = pd.concat([pd.read_csv(f"{l}_stats_full.csv", low_memory=False) for l in LEAGUES if os.path.exists(f"{l}_stats_full.csv")])
    st = st.drop_duplicates(["fixture_id", "team_id"])
    for c in ("Total_Shots", "Shots_on_Goal", "expected_goals", "Yellow_Cards"):
        st[c] = pd.to_numeric(st[c].astype(str).str.replace("%", ""), errors="coerce")
    lu = pd.concat([pd.read_csv(f"{l}_lineups.csv", low_memory=False) for l in LEAGUES if os.path.exists(f"{l}_lineups.csv")])
    lu = lu.drop(columns=["fetched_at"]).drop_duplicates()
    return fx, st, lu


class Indep:
    def __init__(self, cut_fixture=None):
        self.fx, self.st, self.lu = load()
        self.stats = {(int(r.fixture_id), int(r.team_id)): r for r in self.st.itertuples()}

    def prior(self, tid, ts):
        f = self.fx
        m = f[f["fin"] & (f["ts"] < ts) & ((f["home_id"] == tid) | (f["away_id"] == tid))]
        return m.sort_values(["ts", "fixture_id"])

    def team_rows(self, tid, ts):
        out = []
        for r in self.prior(tid, ts).itertuples():
            home = r.home_id == tid
            gf, ga = (r.hg, r.ag) if home else (r.ag, r.hg)
            out.append({"fid": int(r.fixture_id), "ts": int(r.ts), "home": home, "gf": int(gf), "ga": int(ga),
                        "res": "W" if gf > ga else "D" if gf == ga else "L", "league": r.league, "opp": int(r.away_id if home else r.home_id)})
        return out


def r1(x):
    return round(float(x) + 1e-9, 1)


def recompute(I, fid, cut_ts=None):
    """Числата, които текстът може да каже за мача, пресметнати наново. -> {kind: {ключ: стойност}}"""
    f = I.fx.set_index("fixture_id").loc[fid]
    ts = int(f["ts"]) if cut_ts is None else cut_ts
    hid, aid = int(f["home_id"]), int(f["away_id"])
    th, ta = I.team_rows(hid, ts), I.team_rows(aid, ts)
    out = {}
    # форма
    n = min(5, len(th), len(ta))
    d = {"n": n}
    for tag, t in (("h", th), ("a", ta)):
        last = t[-n:] if n else []
        d.update({f"{tag}_w": sum(x["res"] == "W" for x in last), f"{tag}_d": sum(x["res"] == "D" for x in last),
                  f"{tag}_l": sum(x["res"] == "L" for x in last), f"{tag}_gf": sum(x["gf"] for x in last), f"{tag}_ga": sum(x["ga"] for x in last)})
    out["form"] = d
    hh = [x for x in th if x["home"]][-5:]
    aa = [x for x in ta if not x["home"]][-5:]
    out["venue"] = {"h_n": len(hh), "h_w": sum(x["res"] == "W" for x in hh), "a_n": len(aa), "a_w": sum(x["res"] == "W" for x in aa)}
    # класиране
    if f["league"] not in CUPS:
        ls = I.fx[(I.fx["league"] == f["league"]) & (I.fx["season"] == f["season"])]
        teams = sorted(set(ls["home_id"]) | set(ls["away_id"]))
        past = ls[ls["fin"] & (ls["ts"] < ts)]
        pts = {t: 0 for t in teams}; gf = {t: 0 for t in teams}; ga = {t: 0 for t in teams}
        for r in past.itertuples():
            gf[r.home_id] += r.hg; ga[r.home_id] += r.ag; gf[r.away_id] += r.ag; ga[r.away_id] += r.hg
            if r.hg > r.ag: pts[r.home_id] += 3
            elif r.hg < r.ag: pts[r.away_id] += 3
            else: pts[r.home_id] += 1; pts[r.away_id] += 1
        order = sorted(teams, key=lambda t: (-pts[t], -(gf[t] - ga[t]), -gf[t], t))
        rank = {t: i + 1 for i, t in enumerate(order)}
        d = {"n_teams": len(teams)}
        for tag, t in (("h", hid), ("a", aid)):
            d[f"{tag}_rank"] = rank[t]; d[f"{tag}_pts"] = int(pts[t])
            d[f"{tag}_gap"] = int(pts[t] - pts[order[1]]) if rank[t] == 1 else int(pts[order[0]] - pts[t])
            d[f"{tag}_gap4"] = int(pts[order[3]] - pts[t])
        out["table"] = d
    # удари / xG
    d = {"n": 5}
    for tag, t in (("h", th), ("a", ta)):
        rows = []
        for x in t[-5:]:
            a, b = I.stats.get((x["fid"], hid if tag == "h" else aid)), I.stats.get((x["fid"], x["opp"]))
            if a is not None and b is not None:
                rows.append((a, b))
        def m(get):
            v = [get(a, b) for a, b in rows if not np.isnan(get(a, b))]
            return r1(np.mean(v)) if len(v) >= 4 else None
        d.update({f"{tag}_xg_for": m(lambda a, b: a.expected_goals), f"{tag}_xg_ag": m(lambda a, b: b.expected_goals),
                  f"{tag}_sh": m(lambda a, b: a.Total_Shots), f"{tag}_sot": m(lambda a, b: a.Shots_on_Goal), f"{tag}_sh_ag": m(lambda a, b: b.Total_Shots)})
    out["xg"] = out["shots"] = d
    # почивка / евромачове
    d = {}
    for tag, t, tid in (("h", th, hid), ("a", ta, aid)):
        if t:
            d[f"{tag}_rest"] = int(round((ts - t[-1]["ts"]) / 86400.0))
        nxt = I.fx[((I.fx["home_id"] == tid) | (I.fx["away_id"] == tid)) & (I.fx["ts"] > ts) & (I.fx["ts"] <= ts + 4 * 86400)
                   & I.fx["league"].isin(CUPS)].sort_values("ts")
        if len(nxt):
            d[f"{tag}_next"] = int(round((int(nxt["ts"].iloc[0]) - ts) / 86400.0))
    out["rest"] = d
    # съдия
    ref = f["referee"]
    if isinstance(ref, str) and ref.strip():
        k = ref.strip().lower()
        pm = I.fx[I.fx["fin"] & (I.fx["ts"] < ts) & (I.fx["referee"].astype(str).str.strip().str.lower() == k)]
        ys = []
        for r in pm.itertuples():
            a, b = I.stats.get((int(r.fixture_id), int(r.home_id))), I.stats.get((int(r.fixture_id), int(r.away_id)))
            if a is not None and b is not None and not np.isnan(a.Yellow_Cards + b.Yellow_Cards):
                ys.append(a.Yellow_Cards + b.Yellow_Cards)
        out["ref"] = {"ref_n": len(pm), "ref_hw": int(round(100 * (pm["hg"] > pm["ag"]).mean())) if len(pm) else None,
                      "ref_y": r1(np.mean(ys)) if ys else None}
    # треньор (по фамилия) и отсъстващи - от съставите
    lu_fx = I.lu.groupby(["fixture_id", "team_id"])
    def toks(name):
        n = "".join(c for c in unicodedata.normalize("NFKD", str(name).lower()) if not unicodedata.combining(c))
        return frozenset(t for t in n.replace(".", " ").replace("-", " ").split() if len(t) >= 3)

    def same(a, b):          # един и същи треньор: еднакъв ненулев id или обща дума от името
        return (a[1] and b[1] and a[1] == b[1]) or bool(a[0] & b[0])
    for tag, t, tid in (("h", th, hid), ("a", ta, aid)):
        seq = []
        for x in t:
            try:
                g = lu_fx.get_group((x["fid"], tid))
            except KeyError:
                continue
            if (g["starter"] == 1).sum() >= 9:
                cn, ci = g["coach"].iloc[0], g["coach_id"].iloc[0]
                seq.append(((toks(cn), int(ci) if ci == ci and ci else None) if isinstance(cn, str) else None, g))
        k = 0
        for c, _g in reversed(seq):
            if c is not None and seq[-1][0] is not None and same(c, seq[-1][0]):
                k += 1
            else:
                break
        out.setdefault("coach", {})[tag] = {"coach_k": k}
        last = seq[-10:]
        starts = {}
        for _c, g in last:
            for p in g.loc[g["starter"] == 1, "player_id"].dropna().astype(int):
                starts[p] = starts.get(p, 0) + 1
        out.setdefault("usual", {})[tag] = ({p: c for p, c in starts.items() if c / len(last) >= 0.5}, len(last))
    return out


# ----------------------------------------------------------------------------------------------- проверката
NUM = re.compile(r"\d+(?:,\d+)?")


def fmt(v):
    if isinstance(v, float) and not float(v).is_integer():
        return f"{v:.1f}".replace(".", ",")
    return str(int(v))


def numbers_ok(sentence):
    """Всяко число в текста е сред facts (имената - махнати)."""
    text = sentence["text"]
    facts = sentence["facts"]
    for name in sorted(facts.get("_names", []), key=len, reverse=True):
        text = text.replace(name, " ")
    allowed = [float(v) for k, v in facts.items() if k != "_names" and v is not None]
    return [n for n in NUM.findall(text) if not any(abs(float(n.replace(",", ".")) - a) < 1e-9 for a in allowed)]


def compare(sentence, R, model_src):
    """facts срещу независимо пресметнатото. -> списък с разминавания."""
    kind, facts = sentence["kind"], sentence["facts"]
    errs = []
    if kind in ("form", "venue", "table", "xg", "shots", "rest", "ref"):
        ref = R.get(kind, {})
        for k, v in facts.items():
            if k in ("_names", "line", "place4"):
                continue
            if k == "n" and kind in ("xg", "shots"):
                continue
            if ref.get(k) is None or (abs(float(ref[k]) - float(v)) > 1e-9):
                errs.append(f"{kind}.{k}: текст {v} / данни {ref.get(k)}")
    elif kind == "coach":
        k = facts.get("coach_k")
        if k is not None and k not in (R["coach"]["h"]["coach_k"], R["coach"]["a"]["coach_k"]):
            errs.append(f"coach_k {k} / данни {R['coach']}")
    elif kind == "model":
        for k, code in (("m_h", "home_win"), ("m_d", "draw"), ("m_a", "away_win"), ("m_o", "over25")):
            if k in facts and int(round(model_src.get(code, -99))) != facts[k]:
                errs.append(f"model.{k}: текст {facts[k]} / снимка {model_src.get(code)}")
        if "line" in facts and facts["line"] != 2.5:
            errs.append("model.line")
    elif kind.startswith("absent_"):
        tag = kind[-1]
        usual, n = R["usual"][tag]
        if facts.get("usual_n") != n:
            errs.append(f"{kind}.usual_n {facts.get('usual_n')} / {n}")
        vals = sorted(usual.values(), reverse=True)
        for i in range(4):
            k = f"starts_{i}"
            if k in facts and facts[k] not in vals:
                errs.append(f"{kind}.{k} {facts[k]} не е брой стартове на обичаен титуляр")
    elif kind == "lineups":
        for k, code in (("now_h", "home_win"), ("now_d", "draw"), ("now_a", "away_win")):
            if k in facts and int(round(model_src.get(code, -99))) != facts[k]:
                errs.append(f"lineups.{k}: текст {facts[k]} / данни {model_src.get(code)}")
        for k, code in (("pre_h", "home_win"), ("pre_d", "draw"), ("pre_a", "away_win")):
            if k in facts and int(round(model_src.get("_pre", {}).get(code, -99))) != facts[k]:
                errs.append(f"lineups.{k}: текст {facts[k]} / данни преди {model_src.get('_pre', {}).get(code)}")
    return errs


def main(db, md_path):
    con = sqlite3.connect(db)
    texts = {r[0]: (r[1], r[2], json.loads(r[3])) for r in con.execute("SELECT fixture_id, league, match_date, sentences FROM match_text")}
    snap = {}
    names = {}
    for fid, code, pct, ht, at in con.execute("SELECT fixture_id, market_code, pick_pct, home_team, away_team FROM predictions_snapshot "
                                              "WHERE market_code IN ('home_win','draw','away_win','over25')"):
        snap.setdefault(fid, {})[code] = pct
        names[fid] = (ht, at)
    con.close()

    # в) забранени думи - всички текстове
    banned_hits = [(f, s["text"]) for f, (_l, _d, ss) in texts.items() for s in ss if any(w in s["text"].lower() for w in BANNED)]

    # 30 случайни: по 2 от лига
    rnd = random.Random(SEED)
    by_lg = {}
    for f, (lg, _d, _s) in texts.items():
        by_lg.setdefault(lg, []).append(f)
    pick = []
    for lg in sorted(by_lg):
        pick += rnd.sample(sorted(by_lg[lg]), min(2, len(by_lg[lg])))
    rest = sorted(set(texts) - set(pick))
    rnd.shuffle(rest)
    pick = (pick + rest)[:30]

    I = Indep()
    from bg_names import to_cyrillic
    report, n_sent, n_num, all_errs = [], 0, 0, []
    for f in sorted(pick, key=lambda x: (texts[x][0], texts[x][1])):
        lg, md, ss = texts[f]
        R = recompute(I, f)
        H, A = (to_cyrillic(n, lg) for n in names[f])
        report.append(f"### {H} — {A} ({lg}, {md}, мач {f})\n")
        for s in ss:
            n_sent += 1
            bad_n = numbers_ok(s)
            n_num += len(NUM.findall(s["text"]))
            errs = (["число без източник: " + ", ".join(bad_n)] if bad_n else []) + compare(s, R, snap.get(f, {}))
            all_errs += [(f, s["kind"], e) for e in errs]
            report.append(f"- {s['text']}" + (f"  \n  **ГРЕШКА:** {'; '.join(errs)}" if errs else ""))
        report.append("")

    # минали мачове със съставите (данните отрязани до началото)
    past_report = past_examples(I)
    for f, ss, R, src, title in past_report:
        report.append(f"### {title}\n")
        for s in ss:
            n_sent += 1
            bad_n = numbers_ok(s)
            n_num += len(NUM.findall(s["text"]))
            errs = (["число без източник: " + ", ".join(bad_n)] if bad_n else []) + compare(s, R, src)
            all_errs += [(f, s["kind"], e) for e in errs]
            report.append(f"- {s['text']}" + (f"  \n  **ГРЕШКА:** {'; '.join(errs)}" if errs else ""))
        report.append("")

    head = [
        "# Текст на мача — 30 примера и проверка (ZADACHA_TEKST, 06.10.2026)",
        "",
        f"Генерирано: {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC от `validation/tekst_proverka_20261006.py` върху копие на базата "
        "(таблица `match_text`, напълнена от `match_text.refresh()` — същият код като в снимката).",
        "",
        "## Проверка",
        "",
        f"- Текстове с проверени числа: {len(pick)} предстоящи мача (по 2 от лига, случайни, seed {SEED}) + {len(past_report)} минали мача със съставите.",
        f"- Изречения: {n_sent}; числа в тях: {n_num}.",
        f"- **Разминавания (число без източник или различно от независимо пресметнатото): {len(all_errs)}.**",
        f"- **Забранени думи** (букмейк*, коефициент*, пазар*, залог/залага/заложи, сигурн*, гарантира*) във всичките {len(texts)} текста: "
        f"**{len(banned_hits)}**.",
        "",
        "Как се проверява: (а) всяко число в текста (без имената на отборите и хората) трябва да е сред числата, с които шаблонът е попълнен; "
        "(б) всяко от тях се пресмята наново с отделен прост код направо от CSV-тата (`{лига}_fixtures.csv`, `_stats_full.csv`, `_lineups.csv`) "
        "— форма, домакинства/гостувания, класиране, удари/xG, почивка/евромачове, съдия, треньор, обичайни титуляри — а процентите на модела "
        "се сравняват с `predictions_snapshot` (числата, които сайтът показва).",
        "",
        "Бележки: формата, почивката и ударите са по мачовете в 17-те лиги в базата (първенства + европейски турнири, без купите). "
        "Класирането е пресметнато от резултатите в базата (без наказания с точки). Имената на играчи, треньори и съдии са както в API-то "
        "(латиница); отборите — на кирилица, където има потвърдено име (`bg_names.py`).",
        "",
        "## Предстоящи мачове" if pick else "",
        "",
    ]
    if all_errs:
        head += ["## Разминавания", ""] + [f"- мач {f}, {k}: {e}" for f, k, e in all_errs] + [""]
    if banned_hits:
        head += ["## Забранени думи", ""] + [f"- мач {f}: {t}" for f, t in banned_hits] + [""]
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(head + report) + "\n")
    print(f"{len(pick)}+{len(past_report)} мача, {n_sent} изречения, {n_num} числа, разминавания {len(all_errs)}, забранени думи {len(banned_hits)}")
    for e in all_errs[:20]:
        print("  ", e)
    return not all_errs and not banned_hits


def past_examples(I, k=3):
    """Минали мачове с final ред в сянката (съставите са излезли): текстът така, както би бил 15-100 мин преди началото - данните
    отрязани с build_features.truncate до началото на мача; процентите - суровият слой от сянката (pre -> final), за "какво се промени"."""
    import config
    config.MATCH_TEXT = True
    import match_text as mt
    from features import build_features as bf
    from bg_names import to_cyrillic
    con = sqlite3.connect(os.path.join(REPO, "predictions.db"))
    fin = con.execute("SELECT fixture_id, league, kickoff_ts, probs_layer FROM layer_shadow WHERE mode='final' ORDER BY computed_at DESC").fetchall()
    out, seen = [], set()
    raw = bf.index_raw(bf.load_raw())
    for fid, lg, ko, pl in fin:
        if fid in seen or len(out) >= k:
            continue
        seen.add(fid)
        pre = con.execute("SELECT probs_layer FROM layer_shadow WHERE fixture_id=? AND mode='pre' ORDER BY computed_at DESC LIMIT 1", (fid,)).fetchone()
        if not pre or fid not in set(I.fx["fixture_id"]):
            continue
        tr = bf.truncate(raw, int(ko), fid)
        D = mt.Data(raw=tr, names_raw=raw)
        f = I.fx.set_index("fixture_id").loc[fid]
        now = {c: 100 * v for c, v in json.loads(pl).items()}
        before = {c: 100 * v for c, v in json.loads(pre[0]).items()}
        H, A = to_cyrillic(f["home"], lg), to_cyrillic(f["away"], lg)
        res = mt.build_for_fixture(D, fid, now, (H, A), False, model_pre=before)
        if not res or not res[1]:
            continue
        src = dict(now); src["_pre"] = before
        R = recompute(I, fid, cut_ts=int(ko))
        title = (f"{H} — {A} ({lg}, мач {fid}) — МИНАЛ мач, данните отрязани до началото; съставите налични; "
                 "проценти: суровият слой от сянката преди → след съставите")
        out.append((fid, res[0], R, src, title))
    con.close()
    return out


if __name__ == "__main__":
    md = sys.argv[sys.argv.index("--md") + 1] if "--md" in sys.argv else os.path.join(REPO, "validation", "tekst_primeri_20261006.md")
    sys.exit(0 if main(sys.argv[1], md) else 1)
