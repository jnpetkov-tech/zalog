"""validation/ezik_tekst_bg_20261008.py - ZADACHA_EZIK: новият match_text.py пише СЪЩИЯ български текст като стария (git 6e8d333).

match_text.refresh() се вика от самостоятелните снимки (build_predictions_snapshot.py, snapshot_final.py) - commit-ът влиза веднага,
затова преди commit: два пъти refresh() върху копия на живата база - стария и новия код - и сравнение мач по мач: всички полета на
всяко изречение без "text_en"/"names_en" (kind, score, text, facts), has_lineups, model_pre. Също: всяко изречение има "text_en",
в него няма кирилица.
Изход: validation/ezik_tekst_bg_20261008.txt
Употреба: venv/bin/python3 validation/ezik_tekst_bg_20261008.py <празна папка> [стара ревизия]
"""
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, REPO)
os.chdir(REPO)
import config  # noqa: E402

CYR = re.compile(r"[А-Яа-яЁёЪъ]")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(mod, db):
    con = sqlite3.connect(db)
    con.execute("DELETE FROM match_text")
    con.commit()
    con.close()
    n, secs = mod.refresh(db_path=db)
    con = sqlite3.connect(db)
    rows = {r[0]: (r[1], json.loads(r[2] or "[]"), r[3]) for r in con.execute("SELECT fixture_id, has_lineups, sentences, model_pre FROM match_text")}
    con.close()
    return n, secs, rows


def main():
    work = sys.argv[1]
    rev = sys.argv[2] if len(sys.argv) > 2 else "6e8d333"
    os.makedirs(work, exist_ok=True)
    config.MATCH_TEXT = True
    old_py = os.path.join(work, "match_text_old.py")
    with open(old_py, "w") as fh:
        fh.write(subprocess.run(["git", "show", f"{rev}:match_text.py"], capture_output=True, text=True, check=True).stdout)
    out = []
    dbs = {}
    for tag in ("old", "new"):
        db = os.path.join(work, f"tekst_{tag}.db")
        s = sqlite3.connect(f"file:{os.path.join(REPO, 'predictions.db')}?mode=ro", uri=True)
        d = sqlite3.connect(db)
        s.backup(d)
        d.close()
        s.close()
        dbs[tag] = db
    old = load(old_py, "match_text_old")
    new = load(os.path.join(REPO, "match_text.py"), "match_text_new")
    old.LOG_PATH = os.path.join(work, "log_old.txt")       # не в живия match_text_log.txt
    new.LOG_PATH = os.path.join(work, "log_new.txt")
    n_o, t_o, r_o = run(old, dbs["old"])
    n_n, t_n, r_n = run(new, dbs["new"])
    out.append(f"стар код: {n_o} мача ({t_o:.0f} с); нов код: {n_n} мача ({t_n:.0f} с)")
    strip = lambda ss: [{k: v for k, v in s.items() if k not in ("text_en", "names_en")} for s in ss]
    diff = [f for f in set(r_o) | set(r_n) if f not in r_o or f not in r_n or r_o[f][0] != r_n[f][0] or r_o[f][2] != r_n[f][2]
            or strip(r_o[f][1]) != strip(r_n[f][1])]
    n_sent = sum(len(v[1]) for v in r_n.values())
    no_en = [(f, s["kind"]) for f, v in r_n.items() for s in v[1] if not s.get("text_en")]
    cyr = [(f, s["text_en"]) for f, v in r_n.items() for s in v[1] if s.get("text_en") and CYR.search(s["text_en"])]
    ok = not diff and n_o == n_n and not no_en and not cyr
    out.append(f"{'OK  ' if not diff and n_o == n_n else 'FAIL'} българският текст (kind/score/text/facts, has_lineups, model_pre) - еднакъв за "
               f"всичките {len(r_n)} мача; различни: {sorted(diff)[:10]}")
    out.append(f"{'OK  ' if not no_en else 'FAIL'} всяко изречение има text_en - {n_sent} изречения; без: {no_en[:10]}")
    out.append(f"{'OK  ' if not cyr else 'FAIL'} без кирилица в text_en - {cyr[:5]}")
    kinds = {}
    for v in r_n.values():
        for s in v[1]:
            kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    out.append("видове изречения: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    out.append(f"мачове след съставите: {sum(1 for v in r_n.values() if v[0])}")
    text = "ZADACHA_EZIK - match_text.py: българският текст непроменен (стар/нов код върху копия на живата база)\n\n" + "\n".join(out) + "\n"
    with open(os.path.join(REPO, "validation", "ezik_tekst_bg_20261008.txt"), "w") as fh:
        fh.write(text)
    print(text)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
