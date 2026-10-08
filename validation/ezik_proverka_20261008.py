"""validation/ezik_proverka_20261008.py - проверка на английския текст на мача (ZADACHA_EZIK, 08.10.2026).

Пуска СЪЩАТА проверка като validation/tekst2_proverka_20261006.py (30 предстоящи мача по 2 от лига, seed 20261006 + 5 минали със
съставите + 5 минали преди съставите; числата във facts срещу независимо пресметнатото от суровите CSV и от снимката) и за всяко
изречение добавя проверките на английския вариант "text_en":
  а) всяко число в text_en (без имената на отборите/хората, names_en) е сред facts;
  б) числата в text_en са ТОЧНО числата в българския text (същия брой, същите стойности; 2,5 = 2.5);
  в) без кирилица; без забранени думи (bookmaker, odds, market, bet, wager, stake, sure, certain, guarantee - цели думи, имената махнати);
  г) "first-choice goalkeeper" / "top scorer" в английския <=> "титулярния вратар" / "голмайстора" в българския;
  д) имената на хората - оригиналните от API-то (без кирилица), и при българските отбори.
Пише validation/ezik_proverka_20261008.txt (обобщение) и validation/ezik_primeri_20261008.md (10 мача от поне 5 лиги - вкл. bulgaria,
bulgaria2, евротурнир, мач след съставите - английският текст до българския).
Употреба: venv/bin/python3 validation/ezik_proverka_20261008.py <копие на базата с match_text, напълнена от новия код> <папка за чернови>
"""
import importlib.util
import os
import re
import sys
from datetime import datetime

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, REPO)
os.chdir(REPO)

_spec = importlib.util.spec_from_file_location("tp2", os.path.join(REPO, "validation", "tekst2_proverka_20261006.py"))
tp2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tp2)

CYR = re.compile(r"[А-Яа-яЁёЪъ]")
NUM_BG = re.compile(r"\d+(?:,\d+)?")
NUM_EN = re.compile(r"\d+(?:\.\d+)?")
EN_ERRS, EXAMPLES, STATS = [], [], {"sent": 0, "num": 0}


def _strip(text, names):
    for nm in sorted((n for n in names if n), key=len, reverse=True):
        text = text.replace(nm, " ")
    return text.replace("(xG)", " ")


def check_en(s):
    import match_text as mt
    errs = []
    en = s.get("text_en")
    if not en:
        return ["няма text_en"]
    facts = s["facts"]
    allowed = [float(v) for k, v in facts.items() if not k.startswith("_") and v is not None]
    t_en = _strip(en, s.get("names_en", []))
    t_bg = _strip(s["text"], facts.get("_names", []))
    n_en = [float(x) for x in NUM_EN.findall(t_en)]
    n_bg = [float(x.replace(",", ".")) for x in NUM_BG.findall(t_bg)]
    STATS["num"] += len(n_en)
    bad = [x for x in n_en if not any(abs(x - a) < 1e-9 for a in allowed)]
    if bad:
        errs.append(f"число без източник в text_en: {bad}")
    if sorted(n_en) != sorted(n_bg):
        errs.append(f"числата се различават от българския: en {sorted(n_en)} / bg {sorted(n_bg)}")
    if CYR.search(en):
        errs.append("кирилица в text_en")
    b = mt.banned_en(en, s.get("names_en", []))
    if b:
        errs.append(f"забранена дума {b}")
    if ("first-choice goalkeeper" in en) != ("титулярн" in s["text"] and "вратар" in s["text"]):
        errs.append("вратар: английският не отговаря на българския")
    if ("top scorer" in en) != ("голмайстора" in s["text"]):
        errs.append("голмайстор: английският не отговаря на българския")
    people = s.get("names_en", [])[2:]
    if any(CYR.search(n) for n in people):
        errs.append(f"име на кирилица: {people}")
    return errs


_orig_check_text = tp2.check_text


def check_text(I, fid, ss, src, cut_ts, missing_by_team, report, title):
    res = _orig_check_text(I, fid, ss, src, cut_ts, missing_by_team, report, title)
    import match_text as mt
    lg = I.fx.set_index("fixture_id").loc[fid]["league"]
    rows = []
    for s in mt.page_order(ss):
        STATS["sent"] += 1
        e = check_en(s)
        EN_ERRS.extend((fid, s["kind"], x) for x in e)
        rows.append((s["text"], s.get("text_en", ""), e))
    EXAMPLES.append({"fid": fid, "league": lg, "title": title, "rows": rows, "after": cut_ts is not None and "СЪС съставите" in title,
                     "card": (ss[0]["text"], ss[0].get("text_en", ""))})
    return res


tp2.check_text = check_text


def pick_examples():
    """10 мача, поне 5 лиги: bulgaria, bulgaria2, евротурнир, мач след съставите, после различни лиги."""
    chosen = []
    want = [lambda x: x["league"] == "bulgaria", lambda x: x["league"] == "bulgaria2",
            lambda x: x["league"] in ("champions_league", "europa_league", "conference_league"), lambda x: x["after"],
            lambda x: "ПРЕДИ съставите" in x["title"]]
    for w in want:
        for x in EXAMPLES:
            if w(x) and x not in chosen:
                chosen.append(x)
                break
    for x in EXAMPLES:
        if len(chosen) >= 10:
            break
        if x not in chosen and x["league"] not in {c["league"] for c in chosen}:
            chosen.append(x)
    for x in EXAMPLES:
        if len(chosen) >= 10:
            break
        if x not in chosen:
            chosen.append(x)
    return chosen


def main():
    db, work = sys.argv[1], sys.argv[2]
    os.makedirs(work, exist_ok=True)
    ok_bg = tp2.main(db, os.path.join(work, "tekst2_primeri.md"), os.path.join(work, "tekst2_imena.md"))
    ex = pick_examples()
    leagues = sorted({x["league"] for x in ex})
    lines = [
        f"ZADACHA_EZIK - проверка на английския текст на мача ({datetime.now().strftime('%Y-%m-%d %H:%M')} UTC)",
        "",
        f"База: копие на живата с match_text, напълнена от новия match_text.refresh(). Мачове: {len(EXAMPLES)} "
        "(30 предстоящи по 2 от лига + минали със/преди съставите - същите като tekst2_proverka_20261006.py).",
        f"{'OK  ' if ok_bg else 'FAIL'} българската проверка (tekst2_proverka_20261006.py: числа срещу независимо пресметнатото, "
        "забранени думи, имена, ред) - непроменена",
        f"{'OK  ' if not EN_ERRS else 'FAIL'} английският текст: {STATS['sent']} изречения, {STATS['num']} числа; разминавания: {len(EN_ERRS)}",
        "  (числата в text_en са сред facts и са същите като в българския; без кирилица; без забранени думи; вратар/голмайстор; имена)",
    ] + [f"  - мач {f}, {k}: {e}" for f, k, e in EN_ERRS[:40]]
    with open(os.path.join(REPO, "validation", "ezik_proverka_20261008.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    md = ["# Текст на мача на английски — 10 примера (ZADACHA_EZIK, 08.10.2026)", "",
          f"Генерирано от `validation/ezik_proverka_20261008.py`. {len(ex)} мача, {len(leagues)} лиги ({', '.join(leagues)}). "
          "Ляво — българският текст (както е на сайта), дясно — английският (`text_en`, същите числа). Подредбата е като на страницата "
          "на мача (изречението за модела — последно). Имената на английски — оригиналните от API-то.", "",
          f"Автоматична проверка на всичките {STATS['sent']} изречения от проверката: **{len(EN_ERRS)} разминавания** "
          "(`validation/ezik_proverka_20261008.txt`).", ""]
    for x in ex:
        md += [f"## {x['title']}", "", "| български | English |", "|---|---|"]
        for bg, en, e in x["rows"]:
            md.append(f"| {bg} | {en}{' **ГРЕШКА: ' + '; '.join(e) + '**' if e else ''} |")
        md += ["", f"Карта в списъка: „{x['card'][0]}“ / “{x['card'][1]}”", ""]
    with open(os.path.join(REPO, "validation", "ezik_primeri_20261008.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(lines))
    sys.exit(0 if ok_bg and not EN_ERRS else 1)


if __name__ == "__main__":
    main()
