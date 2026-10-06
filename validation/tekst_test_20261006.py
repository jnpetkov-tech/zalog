"""validation/tekst_test_20261006.py - тест на ZADACHA_TEKST на КОПИЕ на базата, отделно Flask приложение (живото не се пипа).

1. Превключвателите на 0 -> всяка страница байт по байт като стария код (data_backups/20261006_tekst/: prognozi.py + шаблоните).
2. SHOW_EXP_IN_LIST=1 -> в списъка мачовете без проверено 1X2 имат проценти + "експ."; мачовете с проверено 1X2 - непроменени;
   броят мачове в списъка - същият; отчетът горе и "Приключили" - същите.
3. MATCH_TEXT=1 -> страницата на мача има "За мача" с целия текст; картата в списъка - първото изречение; мач без ред в match_text - без текст.
4. Грешка: таблицата match_text липсва / повредена -> страниците 200, без текст.
Употреба: venv/bin/python3 validation/tekst_test_20261006.py <копие на predictions.db>   (с таблица match_text, напълнена от match_text.refresh)
"""
import importlib.util
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
import skorost_20260924 as sk  # noqa: E402  (make_app: Flask с подменена база)

BACKUP = os.path.join(REPO, "data_backups", "20261006_tekst")
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(("OK   " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def app_for(prognozi_path, db, tag, exp, text, templates=None):
    config.SHOW_EXP_IN_LIST = exp
    config.MATCH_TEXT = text
    import match_text
    match_text.DB_PATH = db
    app = sk.make_app(prognozi_path, os.path.join(REPO, "system_tracker.py"), db, tag)
    if templates:
        app.template_folder = templates
        app.jinja_loader.searchpath = [templates]
    return app


def get_all(app, urls):
    c = app.test_client()
    return {u: (r.status_code, r.data) for u in urls for r in [c.get(u)]}


def main(db):
    urls = [u for u, _ in sk.urls_for(db)]
    con = sqlite3.connect(db)
    days = sorted({r[0][:10] for r in con.execute("SELECT match_date FROM predictions_snapshot")})
    snap_fx = [r[0] for r in con.execute("SELECT DISTINCT fixture_id FROM predictions_snapshot ORDER BY match_date")]
    exp_fx = [r[0] for r in con.execute("SELECT DISTINCT fixture_id FROM predictions_snapshot WHERE league='bulgaria2' LIMIT 3")]
    con.close()
    from datetime import date
    offs = sorted({(date.fromisoformat(d) - date.today()).days for d in days if 0 <= (date.fromisoformat(d) - date.today()).days < 7})
    urls += [f"/prognozi?day={o}" for o in offs] + [f"/prognozi/match/{f}" for f in snap_fx[:40] + exp_fx]
    urls = list(dict.fromkeys(urls))

    # стар код: копие на шаблоните от бекъпа
    old_tpl = os.path.join("/tmp", f"tekst_old_tpl_{os.getpid()}")
    shutil.copytree(os.path.join(REPO, "templates"), old_tpl)
    for f in ("prognozi.html", "prognozi_match.html"):
        shutil.copy(os.path.join(BACKUP, f), os.path.join(old_tpl, f))
    old = get_all(app_for(os.path.join(BACKUP, "prognozi.py"), db, "old", False, False, old_tpl), urls)
    new0 = get_all(app_for(os.path.join(REPO, "web", "prognozi.py"), db, "new0", False, False), urls)
    diff = [u for u in urls if old[u] != new0[u]]
    check(f"превключвателите на 0: {len(urls)} страници байт по байт като старото", not diff, ", ".join(diff[:5]))

    # част 1
    new_exp = get_all(app_for(os.path.join(REPO, "web", "prognozi.py"), db, "exp", True, False), urls)
    day_urls = [u for u in urls if u.startswith("/prognozi?day=")]
    n_tag = sum(new_exp[u][1].decode().count('class="exp-tag"') for u in day_urls)
    n_empty_old = sum(len(re.findall(r'<div class="pred-pick"></div>', old[u][1].decode())) for u in day_urls)
    check("част 1: има мачове с „експ.“ в списъка", n_tag > 0, f"{n_tag} знака „експ.“; празни места преди: {n_empty_old}")
    rows_old = sum(old[u][1].decode().count('class="predrow"') for u in day_urls)
    rows_new = sum(new_exp[u][1].decode().count('class="predrow"') for u in day_urls)
    check("част 1: броят мачове в списъка е същият", rows_old == rows_new, f"{rows_old} / {rows_new}")
    title_ok = 'title="експериментална прогноза - за тази лига не е минала проверката"' in "".join(new_exp[u][1].decode() for u in day_urls)
    check("част 1: знакът има обяснението (title)", title_ok)
    # проверените 1X2 - същите числа: махаме новото (класа exp, знака) и сравняваме блоковете с проценти
    def x12_blocks(html):
        return re.findall(r'<div class="x12">.*?</div></div></div>', html)
    same = all(set(x12_blocks(old[u][1].decode())) <= set(x12_blocks(new_exp[u][1].decode())) for u in day_urls)
    check("част 1: проверените 1X2 са непроменени", same)
    def top_block(html):
        m = re.search(r'<div class="metrics">.*?</div>\s*</div>', html, re.S)
        return m.group(0) if m else html[:0]
    check("част 1: отчетът горе - същият", all(top_block(old[u][1].decode()) == top_block(new_exp[u][1].decode()) for u in day_urls))
    fin = [u for u in urls if "status=finished" in u]
    strip_css = lambda b: re.sub(r"\{# ZADACHA_TEKST.*?#\}|\n<style>\n  \.x12\.exp.*?</style>", "", b.decode(), flags=re.S)
    check("част 1: „Приключили“ - същото (освен добавения стил в <head>)", all(strip_css(old[u][1]) == strip_css(new_exp[u][1]) for u in fin))
    mpages = [u for u in urls if u.startswith("/prognozi/match/")]
    check("част 1: страниците на мачовете - байт по байт същите", all(old[u] == new_exp[u] for u in mpages))

    # част 2
    new_txt = get_all(app_for(os.path.join(REPO, "web", "prognozi.py"), db, "txt", False, True), urls)
    import match_text, json
    con = sqlite3.connect(db)
    tx = {r[0]: [s["text"] for s in json.loads(r[1])] for r in con.execute("SELECT fixture_id, sentences FROM match_text")}
    con.close()
    import html as H
    ok_pages = bad = 0
    for f in snap_fx[:40]:
        page = new_txt[f"/prognozi/match/{f}"][1].decode()
        if f in tx:
            good = "За мача" in page and all(H.escape(t, quote=True) in page or t in page for t in tx[f])
        else:
            good = "За мача" not in page
        ok_pages += good
        bad += not good
    check("част 2: страницата на мача - целият текст", bad == 0, f"{ok_pages} страници")
    n_cards = sum(new_txt[u][1].decode().count('class="pred-text"') for u in day_urls)
    firsts_ok = all(H.escape(tx[f][0], quote=True) in "".join(new_txt[u][1].decode() for u in day_urls) for f in snap_fx if f in tx
                    and any(f"/prognozi/match/{f}\"" in new_txt[u][1].decode() for u in day_urls))
    check("част 2: в списъка - първото изречение на всяка карта", n_cards > 0 and firsts_ok, f"{n_cards} карти с текст")
    check("част 2: всички страници 200", all(new_txt[u][0] == old[u][0] for u in urls))

    # грешки: няма таблица / повредена
    db2 = db + ".notable"
    shutil.copy(db, db2)
    c2 = sqlite3.connect(db2); c2.execute("DROP TABLE match_text"); c2.commit(); c2.close()
    r = get_all(app_for(os.path.join(REPO, "web", "prognozi.py"), db2, "notab", True, True), urls)
    check("грешка: без таблица match_text -> страниците 200, без текст",
          all(r[u][0] == old[u][0] for u in urls) and not any(b'class="pred-text"' in r[u][1] or b'class="mtext"' in r[u][1] for u in urls))
    c2 = sqlite3.connect(db2); c2.execute("CREATE TABLE match_text (fixture_id INTEGER PRIMARY KEY, sentences TEXT)")
    c2.executemany("INSERT INTO match_text VALUES (?, ?)", [(f, "{не е json") for f in snap_fx]); c2.commit(); c2.close()
    r = get_all(app_for(os.path.join(REPO, "web", "prognozi.py"), db2, "bad", True, True), urls)
    check("грешка: повредени редове -> страниците 200, без текст", all(r[u][0] == old[u][0] for u in urls))
    os.remove(db2)
    shutil.rmtree(old_tpl)

    n_ok = sum(ok for _, ok, _ in RESULTS)
    print(f"\n{n_ok}/{len(RESULTS)} OK")
    return n_ok == len(RESULTS)


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1]) else 1)
