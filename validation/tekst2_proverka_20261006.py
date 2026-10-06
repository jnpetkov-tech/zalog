"""validation/tekst2_proverka_20261006.py - проверка на текста на мача след ZADACHA_TEKST_2 (06.10.2026).

Повтаря проверката от tekst_proverka_20261006.py (числата срещу независимо пресметнатото, забранените думи) и добавя:
  - отсъстващите титуляри ПО МИНУТИ: минутите и головете на всеки показан играч се смятат наново с отделен прост код направо от
    {лига}_lineups.csv и {лига}_events.csv (pandas, без match_text/build_features); проверява се и че играчът наистина липсва
    (не е в групата за мача / в списъка на контузените), че е титуляр (средно >= 45 мин.) и че "титулярния вратар"/"голмайстора"
    в текста отговарят на данните;
  - имената на хората при българските отбори - на кирилица (без латински букви), при чуждите - както в API-то;
  - на страницата на мача изречението за модела е последно (match_text.page_order), на картата - най-силното (записаният ред).
Мачове: 30 предстоящи (по 2 от лига, seed 20261006) + 5 минали със съставите + 5 минали ПРЕДИ съставите със списък на контузените
(данните отрязани до началото на мача с build_features.truncate; за "преди съставите" съставът на самия мач е махнат).
Пише validation/tekst2_primeri_20261006.md и validation/tekst2_imena_20261006.md (имената за преглед от Дака).
Употреба: venv/bin/python3 validation/tekst2_proverka_20261006.py <копие на базата с match_text>
"""
import importlib.util
import json
import os
import random
import re
import sqlite3
import sys
from datetime import datetime

import numpy as np
import pandas as pd

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, REPO)
os.chdir(REPO)
_spec = importlib.util.spec_from_file_location("tp1", os.path.join(REPO, "validation", "tekst_proverka_20261006.py"))
tp1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tp1)

SEED = 20261006
BANNED = tp1.BANNED
LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
NUM = tp1.NUM


# ----------------------------------------------------------------------------------------------- независимо: минути и голове
class Indep2(tp1.Indep):
    def __init__(self):
        super().__init__()
        ev = pd.concat([pd.read_csv(f, low_memory=False) for l in tp1.LEAGUES for f in (f"{l}_events.csv", f"{l}_events_pre2024.csv")
                        if os.path.exists(f) and os.path.getsize(f) > 0]).drop_duplicates()
        self.ev = {k: g for k, g in ev.groupby("fixture_id")}
        self.lu_g = {k: g for k, g in self.lu.groupby(["fixture_id", "team_id"])}
        bg = self.fx[self.fx["league"].isin(["bulgaria", "bulgaria2"])]
        self.bg_teams = set(bg["home_id"].astype(int)) | set(bg["away_id"].astype(int))

    def minutes(self, fid, tid):
        """{играч: минути} в мача: титуляр 0-90, смяна (player = излиза, assist = влиза), червен картон; без събития - титулярите по 90."""
        g = self.lu_g[(fid, tid)]
        on = {int(p): 0.0 for p in g.loc[g["starter"] == 1, "player_id"].dropna()}
        off = {}
        e = self.ev.get(fid)
        if e is not None:
            for r in e[e["team_id"] == tid].itertuples():
                m = 90.0 if pd.isna(r.elapsed) else min(max(float(r.elapsed), 0.0), 90.0)
                if r.type == "subst":
                    if pd.notna(r.player_id) and int(r.player_id) in on and int(r.player_id) not in off:
                        off[int(r.player_id)] = m
                    if pd.notna(r.assist_id) and int(r.assist_id) not in on:
                        on[int(r.assist_id)] = m
                elif r.type == "Card" and r.detail in ("Red Card", "Second Yellow card") and pd.notna(r.player_id):
                    if int(r.player_id) in on and int(r.player_id) not in off:
                        off[int(r.player_id)] = m
        return {p: max(0.0, off.get(p, 90.0) - t) for p, t in on.items()}

    def goals(self, fid, tid):
        e = self.ev.get(fid)
        if e is None:
            return None
        gg = e[(e["type"] == "Goal") & ~e["detail"].isin(["Missed Penalty", "Own Goal"]) & (e["team_id"] == tid)]
        return gg["player_id"].dropna().astype(int).value_counts().to_dict()

    def usual(self, tid, ts):
        """Титулярите по минути в последните 10 мача със състав (>= 9 титуляри) преди ts."""
        fids = []
        for x in self.team_rows(tid, ts):
            g = self.lu_g.get((x["fid"], tid))
            if g is not None and (g["starter"] == 1).sum() >= 9:
                fids.append(x)
        last = fids[-10:]
        n = len(last)
        tot, gl, pos, n_ev = {}, {}, {}, 0
        for x in last:
            for p, m in self.minutes(x["fid"], tid).items():
                tot[p] = tot.get(p, 0.0) + m
            g = self.goals(x["fid"], tid)
            if g is not None or x["gf"] + x["ga"] == 0:
                n_ev += 1
                for p, k in (g or {}).items():
                    gl[p] = gl.get(p, 0) + k
            lg = self.lu_g[(x["fid"], tid)]
            for p, ps in zip(lg["player_id"], lg["pos"]):
                if pd.notna(p) and ps in ("G", "D", "M", "F"):
                    pos.setdefault(int(p), []).append(ps)
        avg = {p: int(round(t / n)) for p, t in tot.items() if n and t / n >= 45}
        pos1 = {p: sorted(set(v), key=lambda s: (-v.count(s), [-ord(c) for c in s]))[0] for p, v in pos.items()}
        return {"n": n, "n_ev": n_ev, "avg": avg, "goals": gl, "pos": pos1}


def check_absent(I, s, fid, ts, side_tid, missing):
    """facts на изречението за отсъстващите срещу независимо пресметнатото."""
    errs = []
    U = I.usual(side_tid, ts)
    f = s["facts"]
    if f.get("usual_n") != U["n"]:
        errs.append(f"usual_n {f.get('usual_n')} / {U['n']}")
    pids = s.get("pids", [])
    for i, p in enumerate(pids):
        if p not in U["avg"]:
            errs.append(f"играч {p} не е титуляр по минути")
            continue
        if f.get(f"min_{i}") != U["avg"][p]:
            errs.append(f"min_{i} {f.get(f'min_{i}')} / {U['avg'][p]}")
        g = U["goals"].get(p, 0) if U["n_ev"] == U["n"] else 0
        if f.get(f"goals_{i}", 0) != g:
            errs.append(f"goals_{i} {f.get(f'goals_{i}', 0)} / {g}")
        if p not in missing:
            errs.append(f"играч {p} не липсва")
    absent_all = [p for p in U["avg"] if p in missing]
    gk = [p for p in absent_all if U["pos"].get(p) == "G"]
    if ("титулярния вратар" in s["text"]) != (len(gk) == 1):
        errs.append(f"вратар: текст {'титулярния вратар' in s['text']} / данни {len(gk)}")
    top = None
    if U["n_ev"] == U["n"] and U["goals"]:
        mx = max(U["goals"].values())
        best = [p for p, g in U["goals"].items() if g == mx]
        top = best[0] if mx >= 2 and len(best) == 1 else None
    if ("голмайстора" in s["text"]) != (top is not None and top in absent_all and top not in gk):
        errs.append("голмайстор: текстът не отговаря на данните")
    if f.get("more", 0) != max(0, len(absent_all) - len(pids)):
        errs.append(f"more {f.get('more', 0)} / {len(absent_all) - len(pids)}")
    return errs


def names_ok(s, bg_side):
    """Имената на хората (без отборите и съдията): български отбор -> кирилица."""
    if s["kind"] == "ref" or not bg_side:
        return []
    people = s["facts"].get("_names", [])[2:]
    return [f"латиница в име: {n}" for n in people if LATIN.search(n)]


def numbers_ok(sentence):
    text = sentence["text"]
    facts = sentence["facts"]
    for name in sorted(facts.get("_names", []), key=len, reverse=True):
        text = text.replace(name, " ")
    text = text.replace("(xG)", " ")
    allowed = [float(v) for k, v in facts.items() if not k.startswith("_") and v is not None]
    return [n for n in NUM.findall(text) if not any(abs(float(n.replace(",", ".")) - a) < 1e-9 for a in allowed)]


# ----------------------------------------------------------------------------------------------- проверка на един текст
def check_text(I, fid, ss, src, cut_ts, missing_by_team, report, title):
    f = I.fx.set_index("fixture_id").loc[fid]
    ts = int(f["ts"]) if cut_ts is None else int(cut_ts)
    hid, aid = int(f["home_id"]), int(f["away_id"])
    R = tp1.recompute(I, fid, cut_ts=cut_ts)
    errs_all, n_num = [], 0
    report.append(f"### {title}\n")
    report.append("Страница на мача (изречението за модела — последно):\n")
    import match_text as mt
    for s in mt.page_order(ss):
        n_num += len(NUM.findall(s["text"]))
        bad = numbers_ok(s)
        errs = (["число без източник: " + ", ".join(bad)] if bad else [])
        if s["kind"].startswith("absent_"):
            tid = hid if s["kind"].endswith("h") else aid
            errs += check_absent(I, s, fid, ts, tid, missing_by_team.get(tid, set()))
        else:
            errs += tp1.compare(s, R, src)
        # хората в изречението са на отбора s["tid"] (отсъстващи, треньор): български -> кирилица, чужд -> без промяна (латиница)
        if "tid" in s:
            errs += names_ok(s, s["tid"] in I.bg_teams)
            if s["tid"] not in I.bg_teams and any(not LATIN.search(n) for n in s["facts"].get("_names", [])[2:]):
                errs.append("чужд отбор с име на кирилица")
        errs_all += [(fid, s["kind"], e) for e in errs]
        report.append(f"- {s['text']}" + (f"  \n  **ГРЕШКА:** {'; '.join(errs)}" if errs else ""))
    report.append(f"\nКарта в списъка: „{ss[0]['text']}“\n")
    order_ok = (mt.page_order(ss)[-1]["kind"] == "model") if any(s["kind"] == "model" for s in ss) else True
    if not order_ok:
        errs_all.append((fid, "model", "изречението за модела не е последно"))
    return errs_all, len(ss), n_num


def main(db, md_path, names_path):
    import config
    config.MATCH_TEXT = True
    import match_text as mt
    from features import build_features as bf
    from bg_names import to_cyrillic

    con = sqlite3.connect(db)
    texts = {r[0]: (r[1], r[2], json.loads(r[3])) for r in con.execute("SELECT fixture_id, league, match_date, sentences FROM match_text")}
    snap = {}
    for fid, code, pct in con.execute("SELECT fixture_id, market_code, pick_pct FROM predictions_snapshot "
                                      "WHERE market_code IN ('home_win','draw','away_win','over25')"):
        snap.setdefault(fid, {})[code] = pct
    con.close()
    banned_hits = [(f, s["text"]) for f, (_l, _d, ss) in texts.items() for s in ss if any(w in s["text"].lower() for w in BANNED)]

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

    I = Indep2()
    report, all_errs, n_sent, n_num = [], [], 0, 0
    report += ["## Предстоящи мачове (30)", ""]
    for f in sorted(pick, key=lambda x: (texts[x][0], texts[x][1])):
        lg, md, ss = texts[f]
        fr = I.fx.set_index("fixture_id").loc[f]
        e, a, b = check_text(I, f, ss, snap.get(f, {}), None, {}, report,
                             f"{mt.team_name(fr['home'], lg)} — {mt.team_name(fr['away'], lg)} ({lg}, {md}, мач {f})")
        all_errs += e; n_sent += a; n_num += b

    # минали мачове: със съставите и преди съставите (със списък на контузените)
    raw = bf.index_raw(bf.load_raw())
    con = sqlite3.connect(os.path.join(REPO, "predictions.db"))
    fin = con.execute("SELECT fixture_id, league, kickoff_ts, probs_layer FROM layer_shadow WHERE mode='final' ORDER BY computed_at DESC").fetchall()
    pre_rows = {r[0]: r[1] for r in con.execute("SELECT fixture_id, probs_layer FROM layer_shadow WHERE mode='pre' ORDER BY computed_at")}
    con.close()
    names_log = {}
    sections = {"lu": [], "inj": []}
    seen = set()
    for fid, lg, ko, pl in fin:
        if fid in seen or len(sections["lu"]) >= 5 or fid not in pre_rows or fid not in set(I.fx["fixture_id"]):
            continue
        seen.add(fid)
        tr = bf.truncate(raw, int(ko), fid)
        D = mt.Data(raw=tr, names_raw=raw)
        fr = I.fx.set_index("fixture_id").loc[fid]
        now = {c: 100 * v for c, v in json.loads(pl).items()}
        before = {c: 100 * v for c, v in json.loads(pre_rows[fid]).items()}
        res = mt.build_for_fixture(D, fid, now, (mt.team_name(fr["home"], lg), mt.team_name(fr["away"], lg)), False, model_pre=before)
        if not res or not res[1]:
            continue
        names_log.update(D.name_log)
        src = dict(now); src["_pre"] = before
        lu = tr["idx"]["lu"][fid]
        missing = {int(t): {p for p in I.usual(int(t), int(ko))["avg"] if p not in set(lu[int(t)]["squad"])} for t in lu}
        sections["lu"].append((fid, res[0], src, int(ko), missing,
                               f"{mt.team_name(fr['home'], lg)} — {mt.team_name(fr['away'], lg)} ({lg}, мач {fid}) — МИНАЛ мач, СЪС съставите "
                               "(данните отрязани до началото; проценти: суровият слой от сянката преди → след съставите)"))
    # преди съставите: скорошни изиграни мачове със списък на контузените, в който има титуляр по минути; първо българските
    inj = raw["injuries"]
    inj = inj[inj["type"] == "Missing Fixture"]
    fxi = I.fx.set_index("fixture_id")
    cand = [int(x) for x in inj["fixture_id"].unique() if int(x) in fxi.index and bool(fxi.loc[int(x), "fin"])]
    cand.sort(key=lambda x: (fxi.loc[x, "league"] not in ("bulgaria", "bulgaria2"), -int(fxi.loc[x, "ts"])))
    for fid in cand:
        if len(sections["inj"]) >= 5:
            break
        fr = fxi.loc[fid]
        lg, ko = fr["league"], int(fr["ts"])
        if any(fid == x[0] for x in sections["inj"]) or sum(1 for x in sections["inj"] if fxi.loc[x[0], "league"] == lg) >= 3:
            continue
        tr = bf.truncate(raw, ko, fid)
        tr["idx"]["lu"].pop(fid, None)               # преди съставите
        D = mt.Data(raw=tr, names_raw=raw)
        res = mt.build_for_fixture(D, fid, {}, (mt.team_name(fr["home"], lg), mt.team_name(fr["away"], lg)), False)
        if not res or res[1] or not any(s["kind"].startswith("absent_") for s in res[0]):
            continue
        names_log.update(D.name_log)
        g = inj[inj["fixture_id"] == fid]
        missing = {int(t): set(gg["player_id"].dropna().astype(int)) for t, gg in g.groupby("team_id")}
        sections["inj"].append((fid, res[0], {}, ko, missing,
                                f"{mt.team_name(fr['home'], lg)} — {mt.team_name(fr['away'], lg)} ({lg}, мач {fid}) — МИНАЛ мач, ПРЕДИ съставите "
                                "(данните отрязани до началото, съставът на мача махнат; отсъстващите — от списъка на контузените/наказаните)"))
    for key, head in (("lu", "## Минали мачове със съставите (5)"), ("inj", "## Минали мачове преди съставите, със списък на отсъстващите (5)")):
        report += [head, ""]
        for fid, ss, src, ko, missing, title in sections[key]:
            e, a, b = check_text(I, fid, ss, src, ko, missing, report, title)
            all_errs += e; n_sent += a; n_num += b

    n_abs = sum(1 for k in ("lu", "inj") for x in sections[k] for s in x[1] if s["kind"].startswith("absent_"))
    head = [
        "# Текст на мача — примери и проверка след ZADACHA_TEKST_2 (06.10.2026)",
        "",
        f"Генерирано: {datetime.now().strftime('%Y-%m-%d %H:%M')} от `validation/tekst2_proverka_20261006.py` върху копие на базата "
        "(таблица `match_text`, напълнена от `match_text.refresh()` — същият код като в снимката).",
        "",
        "## Проверка",
        "",
        f"- Мачове: {len(pick)} предстоящи (по 2 от лига, seed {SEED}) + {len(sections['lu'])} минали със съставите + "
        f"{len(sections['inj'])} минали преди съставите (със списък на отсъстващите). Изречения: {n_sent}; числа в тях: {n_num}; "
        f"изречения за отсъстващи: {n_abs}.",
        f"- **Разминавания (число без източник, различно от независимо пресметнатото, латиница в име при български отбор, ред): {len(all_errs)}.**",
        f"- **Забранени думи** във всичките {len(texts)} текста в базата: **{len(banned_hits)}**.",
        "",
        "Как: (а) всяко число в текста (без имената) е сред числата, с които шаблонът е попълнен; (б) те се пресмятат наново с отделен прост "
        "код от CSV-тата — както в `tekst_proverka_20261006.py` (форма, домакинства, класиране, удари/xG, почивка, съдия, треньор, модел), "
        "плюс минутите и головете на всеки отсъстващ титуляр от `_lineups.csv`/`_events.csv` (титуляр 0–90, смяна, червен картон), "
        "че той наистина липсва и че „титулярния вратар“/„голмайстора“ отговарят на данните; (в) имената на хората при български отбор — "
        "без латински букви; (г) на страницата изречението за модела е последно, на картата — първото записано (най-силното).",
        "",
        "Предстоящите мачове днес са след паузата (първите — 09.10), затова при тях няма списък на контузените още — изреченията за "
        "отсъстващи се виждат в миналите мачове отдолу.",
        "",
    ]
    if all_errs:
        head += ["## Разминавания", ""] + [f"- мач {f}, {k}: {e}" for f, k, e in all_errs] + [""]
    if banned_hits:
        head += ["## Забранени думи", ""] + [f"- мач {f}: {t}" for f, t in banned_hits] + [""]
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(head + report) + "\n")
    write_names(raw, names_path)
    print(f"{len(pick)}+{len(sections['lu'])}+{len(sections['inj'])} мача, {n_sent} изречения, {n_num} числа, отсъстващи {n_abs}, "
          f"разминавания {len(all_errs)}, забранени думи {len(banned_hits)}")
    for e in all_errs[:30]:
        print("  ", e)
    return not all_errs and not banned_hits


def write_names(raw, path):
    """Всички хора на българските отбори от сезон 2025-2026 (състави: играчи и треньори) - латиница -> кирилица, за преглед."""
    import match_text as mt
    from bg_names import person_to_cyrillic, to_cyrillic
    fx = raw["fx"]
    bgfx = fx[fx["league"].isin(["bulgaria", "bulgaria2"]) & (fx["season"] >= 2025)]
    ids = set(bgfx["fixture_id"])
    bg_teams = set(bgfx["home_id"].astype(int)) | set(bgfx["away_id"].astype(int))
    lu = raw["lineups"]
    lu = lu[lu["fixture_id"].isin(ids) & lu["team_id"].isin(bg_teams)]
    full = {}
    ev = raw["events"]
    for pid, nm in list(zip(ev["player_id"], ev["player"])) + list(zip(ev["assist_id"], ev["assist"])):
        if pid == pid and isinstance(nm, str) and "." not in nm:
            full[int(pid)] = mt.clean_name(nm)
    team_nm = {int(t): n for t, n in zip(lu["team_id"], lu["team"])}
    rows = {}
    for tid, pid, nm in zip(lu["team_id"], lu["player_id"], lu["player"]):
        if not isinstance(nm, str) or pid != pid:
            continue
        nm = mt.clean_name(nm)
        f = full.get(int(pid))
        if f and (mt._name_tokens(f) & mt._name_tokens(nm)):
            nm = f
        rows[(int(tid), "играч", nm)] = person_to_cyrillic(nm)
    for tid, nm in zip(lu["team_id"], lu["coach"]):
        if isinstance(nm, str) and nm.strip():
            nm = mt.clean_name(nm)
            rows[(int(tid), "треньор", nm)] = person_to_cyrillic(nm)
    by_src = {}
    for (_t, _k, _n), (_c, src) in rows.items():
        by_src[src] = by_src.get(src, 0) + 1
    out = [
        "# Имена на кирилица — за преглед от Дака (ZADACHA_TEKST_2, 06.10.2026)",
        "",
        "Всички играчи и треньори на българските отбори от съставите за сезони 2025–2026 (както ще излязат в текста на мача).",
        "Източник: **речник** — от `bg_names.py` (потвърдено или двусмислена дума, напр. Petar → Петър); **закон** — обратно на Закона "
        "за транслитерацията (zh→ж, ts→ц, sht→щ, ya→я, yu→ю, y→й, -ia→-ия; „a“ винаги → „а“, затова „ъ“ може да липсва); "
        "**чуждо** — в името има букви извън закона (c, j, q, w, x, ć, é и т.н.) — най-вероятно чужденец, преведен по най-близкото четене, "
        "**най-много нужда от преглед**.",
        "",
        "Как се поправя име: кажи ми „X да е Y“ — влиза в `PERSON_NAMES` в `bg_names.py` (точното изписване от лявата колона → твоето).",
        "",
        f"Общо: {len(rows)} имена — " + ", ".join(f"{k}: {v}" for k, v in sorted(by_src.items())) + ".",
        "",
    ]
    for tid in sorted({k[0] for k in rows}, key=lambda t: to_cyrillic(team_nm.get(t, str(t)), "bulgaria")):
        out += [f"## {to_cyrillic(team_nm.get(tid, str(tid)), 'bulgaria')}", "", "| | Латиница (API) | Кирилица | Източник |", "|---|---|---|---|"]
        items = sorted([(k, v) for k, v in rows.items() if k[0] == tid], key=lambda kv: (kv[0][1] != "треньор", kv[1][1] != "чуждо", kv[0][2]))
        for (_t, kind, nm), (cyr, src) in items:
            out.append(f"| {kind} | {nm} | {cyr} | {'**чуждо**' if src == 'чуждо' else src} |")
        out.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


if __name__ == "__main__":
    ok = main(sys.argv[1], os.path.join(REPO, "validation", "tekst2_primeri_20261006.md"),
              os.path.join(REPO, "validation", "tekst2_imena_20261006.md"))
    sys.exit(0 if ok else 1)
