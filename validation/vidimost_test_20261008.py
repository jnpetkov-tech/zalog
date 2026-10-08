"""validation/vidimost_test_20261008.py - седмичното преизчисляване (market_visibility.run) на КОПИЕ на базата; живата база и notify_log.txt
не се пипат (известията - в списък). Изход: validation/vidimost_test_20261008.txt.
1. второ пускане без промяна в данните -> "Няма промени", без известие; 2. пазар, скрит по б) от предишната таблица, с D ≥ 0 -> остава скрит
(б*), с D < 0 -> връща се + известие; 3. грешка в смятането -> таблицата е същата, известие за грешката.
Употреба: venv/bin/python3 validation/vidimost_test_20261008.py <празна папка>"""
import os
import sqlite3
import sys
import warnings

warnings.filterwarnings("ignore")
REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, REPO)
os.chdir(REPO)
import market_visibility as mv  # noqa: E402
import notify  # noqa: E402

RESULTS, SENT = [], []
notify.send = lambda text, *a, **k: SENT.append(text) or "тест"


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(("OK   " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def main(work):
    os.makedirs(work, exist_ok=True)
    db = os.path.join(work, "t.db")
    s = sqlite3.connect(f"file:{REPO}/predictions.db?mode=ro", uri=True)
    d = sqlite3.connect(db)
    s.backup(d)
    d.close()
    s.close()
    check("0. първо пускане", mv.run(db_path=db, do_git=False, report_dir=work) == 0 and not SENT)
    t1 = mv.load(db)
    mv.run(db_path=db, do_git=False, report_dir=work)
    rep = open(os.path.join(work, os.listdir(work)[[f.startswith("vidimost_") for f in os.listdir(work)].index(True)]), encoding="utf-8").read()
    check("1. второ пускане: „Няма промени“, без известие", "Няма промени." in rep and not SENT)
    # 2. задържане: пазар с D ≥ 0, който сега е видим (z ≤ 0.84) -> предишната таблица го отбелязва скрит по б)
    cand = [(k, r) for k, r in t1.items() if k[0] != mv.ALL and r["rule"] == "" and r.get("d") is not None and r["d"] >= 0
            and (r.get("n") or 0) >= mv.MIN_MARKET_N]
    neg = [(k, r) for k, r in t1.items() if k[0] != mv.ALL and r["rule"] == "" and r.get("d") is not None and r["d"] < 0
           and (r.get("n") or 0) >= mv.MIN_MARKET_N]
    (k1, _r1), (k2, _r2) = cand[0], neg[0]
    con = sqlite3.connect(db)
    con.executemany("UPDATE market_visibility SET visible=0, rule='б' WHERE league=? AND market=?", [k1, k2])
    con.commit()
    con.close()
    SENT.clear()
    mv.run(db_path=db, do_git=False, report_dir=work)
    t2 = mv.load(db)
    check(f"2. {k1[0]}/{k1[1]} (D = {t2[k1]['d']:+.5f} ≥ 0), скрит от преди -> остава скрит (б*)", not t2[k1]["visible"] and t2[k1]["rule"] == "б*",
          t2[k1]["reason"])
    check(f"2. {k2[0]}/{k2[1]} (D = {t2[k2]['d']:+.5f} < 0), скрит от преди -> връща се", bool(t2[k2]["visible"]))
    check("2. известие за върнатия пазар (един ред)", len(SENT) == 1 and k2[0] in SENT[0] and "върнат" in SENT[0], SENT[0] if SENT else "няма")
    # 3. грешка -> таблицата остава
    before = mv.load(db)
    SENT.clear()
    orig = mv.WF_PATH
    mv.WF_PATH = os.path.join(work, "няма_такъв.csv")
    rc = mv.run(db_path=db, do_git=False, report_dir=work)
    mv.WF_PATH = orig
    after = mv.load(db)
    check("3. грешка: код 1, таблицата непроменена, известие за грешка",
          rc == 1 and before == after and len(SENT) == 1 and "ГРЕШКА" in SENT[0], SENT[0][:120] if SENT else "")
    ok = sum(1 for _n, o, _d in RESULTS if o)
    with open(os.path.join(REPO, "validation", "vidimost_test_20261008.txt"), "w", encoding="utf-8") as f:
        f.write(f"market_visibility.run - седмичният ход на копие ({ok}/{len(RESULTS)} OK)\n\n" + "\n".join(
            ("OK   " if o else "FAIL ") + n + (f" - {d}" if d else "") for n, o, d in RESULTS) + "\n")
    print(f"{ok}/{len(RESULTS)} OK")
    return ok == len(RESULTS)


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1]) else 1)
