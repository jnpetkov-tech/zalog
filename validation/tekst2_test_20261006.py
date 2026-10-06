"""validation/tekst2_test_20261006.py - тест на Flask частта на ZADACHA_TEKST_2 на КОПИЕ на базата (живото не се пипа).

Старото = web/prognozi.py отпреди задачата (data_backups/20261006_tekst2/prognozi.py), новото = сегашният; и двете - с новия match_text.py
и една и съща таблица match_text (напълнена от match_text.refresh с новия код).
1. MATCH_TEXT=0 -> всички страници байт по байт като старото.
2. MATCH_TEXT=1: списъкът (/prognozi?day=...) - байт по байт като старото (картата показва същото, най-силното изречение);
   страницата на мача - същите изречения, но изречението за модела ("Моделът ...") е последно; всичко друго на страницата - същото.
3. Грешка: без таблица match_text / повредени редове -> страниците 200, без текст.
Употреба: venv/bin/python3 validation/tekst2_test_20261006.py <копие на predictions.db>
"""
import html as H
import json
import os
import re
import shutil
import sqlite3
import sys

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, REPO)
os.chdir(REPO)
sys.path.insert(0, os.path.join(REPO, "validation"))
import config  # noqa: E402
import skorost_20260924 as sk  # noqa: E402

OLD = os.path.join(REPO, "data_backups", "20261006_tekst2", "prognozi.py")
NEW = os.path.join(REPO, "web", "prognozi.py")
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(("OK   " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def pages(path, db, tag, text, urls):
    config.SHOW_EXP_IN_LIST = True
    config.MATCH_TEXT = text
    import match_text
    match_text.DB_PATH = db
    c = sk.make_app(path, os.path.join(REPO, "system_tracker.py"), db, tag).test_client()
    return {u: (r.status_code, r.data.decode()) for u in urls for r in [c.get(u)]}


def mtext(page):
    m = re.search(r'<div class="mtext">.*?class="mtext-note".*?</div>', page, re.S)
    return (re.findall(r"<p>(.*?)</p>", m.group(0), re.S) if m else []), (page.replace(m.group(0), "") if m else page)


def main(db):
    con = sqlite3.connect(db)
    days = sorted({r[0][:10] for r in con.execute("SELECT match_date FROM predictions_snapshot")})
    tx = {r[0]: json.loads(r[1]) for r in con.execute("SELECT fixture_id, sentences FROM match_text")}
    con.close()
    from datetime import date
    offs = sorted({(date.fromisoformat(d) - date.today()).days for d in days if 0 <= (date.fromisoformat(d) - date.today()).days < 7})
    fx = sorted(tx)[:60]
    urls = ["/prognozi", "/prognozi?status=finished"] + [f"/prognozi?day={o}" for o in offs] + [f"/prognozi/match/{f}" for f in fx]
    list_urls = [u for u in urls if not u.startswith("/prognozi/match/")]

    o0, n0 = pages(OLD, db, "o0", False, urls), pages(NEW, db, "n0", False, urls)
    check(f"MATCH_TEXT=0: {len(urls)} страници байт по байт като старото", all(o0[u] == n0[u] for u in urls))

    o1, n1 = pages(OLD, db, "o1", True, urls), pages(NEW, db, "n1", True, urls)
    check("MATCH_TEXT=1: списъкът байт по байт като старото (картата - най-силното изречение)", all(o1[u] == n1[u] for u in list_urls),
          f"{len(list_urls)} страници, {sum(n1[u][1].count('class=\"pred-text\"') for u in list_urls)} карти с текст")
    bad_order, bad_rest, n_model = [], [], 0
    for f in fx:
        u = f"/prognozi/match/{f}"
        (po, ro), (pn, rn) = mtext(o1[u][1]), mtext(n1[u][1])
        if ro != rn or o1[u][0] != n1[u][0]:
            bad_rest.append(f)
        want = [s["text"] for s in tx[f] if s["kind"] != "model"] + [s["text"] for s in tx[f] if s["kind"] == "model"]
        po, pn = [H.unescape(p) for p in po], [H.unescape(p) for p in pn]
        n_model += any(s["kind"] == "model" for s in tx[f])
        if sorted(po) != sorted(pn) or [p.strip() for p in pn] != [w.strip() for w in want] or \
                (any(s["kind"] == "model" for s in tx[f]) and not pn[-1].strip().startswith("Моделът")):
            bad_order.append(f)
    check("страницата на мача: същите изречения, изречението за модела - последно", not bad_order,
          f"{len(fx)} страници, {n_model} с изречение за модела" + (f"; лоши: {bad_order[:5]}" if bad_order else ""))
    check("страницата на мача: всичко извън блока „За мача“ - същото", not bad_rest, ", ".join(map(str, bad_rest[:5])))

    db2 = db + ".notable"
    shutil.copy(db, db2)
    c2 = sqlite3.connect(db2); c2.execute("DROP TABLE match_text"); c2.commit(); c2.close()
    r = pages(NEW, db2, "notab", True, urls)
    check("грешка: без таблица match_text -> 200, без текст", all(r[u][0] == 200 for u in urls)
          and not any('class="mtext"' in r[u][1] or 'class="pred-text"' in r[u][1] for u in urls))
    c2 = sqlite3.connect(db2); c2.execute("CREATE TABLE match_text (fixture_id INTEGER PRIMARY KEY, sentences TEXT)")
    c2.executemany("INSERT INTO match_text VALUES (?, ?)", [(f, "{не е json") for f in fx]); c2.commit(); c2.close()
    r = pages(NEW, db2, "bad", True, urls)
    check("грешка: повредени редове -> 200", all(r[u][0] == 200 for u in urls))
    os.remove(db2)
    n_ok = sum(ok for _, ok, _ in RESULTS)
    print(f"\n{n_ok}/{len(RESULTS)} OK")
    return n_ok == len(RESULTS)


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1]) else 1)
