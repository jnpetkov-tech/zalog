"""validation/skrivane_test_20261008.py - тест на ZADACHA_SKRIVANE на КОПИЕ на базата, отделно Flask приложение (живото не се пипа).

1. market_visibility.run() върху копието -> таблицата market_visibility (+ отчет в папка извън git).
2. PUBLIC_HIDE=0 -> всяка публична страница (списъкът по дни/табове/лиги + всички мачове от снимката) байт по байт като стария код
   (data_backups/20261008_skrivane/: prognozi.py + шаблоните).
3. PUBLIC_HIDE=1 -> страниците на мачовете: без етикети/бележката, само видимите пазари, без празни секции, изречението долу;
   portugal2 -> 404 и я няма в списъка; в списъка няма „експ.“; скритите комбинации (правило б) ги няма на страницата.
4. Грешка: таблицата липсва -> страниците 200, само постоянните правила.
5. /admin/model: секцията „Видимост на пазарите“ (с таблица; без таблица - бележка).
Изход: validation/skrivane_test_20261008.txt, validation/skrivane_pazari_20261008.csv (брой пазари на мач по лиги, преди/след).
Употреба: venv/bin/python3 validation/skrivane_test_20261008.py <празна папка за копията>
"""
import os
import re
import shutil
import sqlite3
import sys
import warnings
from collections import defaultdict

warnings.filterwarnings("ignore")
REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, REPO)
os.chdir(REPO)
sys.path.insert(0, os.path.join(REPO, "validation"))
import config  # noqa: E402
import skorost_20260924 as sk  # noqa: E402

BACKUP = os.path.join(REPO, "data_backups", "20261008_skrivane")
OUT_TXT = os.path.join(REPO, "validation", "skrivane_test_20261008.txt")
OUT_CSV = os.path.join(REPO, "validation", "skrivane_pazari_20261008.csv")
RESULTS = []
FOOT = "Прогнозите са вероятности, изчислени от модел. Не са гаранция за резултат."


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(("OK   " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def copy_db(dst):
    s = sqlite3.connect(f"file:{os.path.join(REPO, 'predictions.db')}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    s.backup(d)
    d.close()
    s.close()


def point_to(db):
    import extra_markets
    import match_text
    import market_visibility as mv
    extra_markets.DB_PATH = db
    match_text.DB_PATH = db
    mv.DB_PATH = db
    mv._cache.update(at=0.0, rows=None)


def app_for(prognozi_path, db, tag, hide, templates=None):
    config.PUBLIC_HIDE = hide
    point_to(db)
    app = sk.make_app(prognozi_path, os.path.join(REPO, "system_tracker.py"), db, tag)
    if templates:
        app.template_folder = templates
        app.jinja_loader.searchpath = [templates]
    return app


def get_all(app, urls):
    c = app.test_client()
    return {u: (r.status_code, r.data) for u in urls for r in [c.get(u)]}


def titles(html):
    return re.findall(r'<div class="msection-title">(.*?)</div>', html)


def section(html, title):
    m = re.search(r'<div class="msection-title">' + re.escape(title) + r'</div>(.*?)(?=<div class="msection">|<div class="howto-link">)', html, re.S)
    return m.group(1) if m else ""


def main(work):
    import market_visibility as mv
    os.makedirs(work, exist_ok=True)
    db = os.path.join(work, "test.db")
    copy_db(db)
    rc = mv.run(db_path=db, do_git=False, report_dir=work)
    vis = mv.load(db)
    check("1. market_visibility.run() върху копието", rc == 0 and bool(vis), f"код {rc}, {len(vis or {})} реда")
    live = sqlite3.connect(f"file:{os.path.join(REPO, 'predictions.db')}?mode=ro", uri=True)
    has_live_tbl = live.execute("SELECT count(*) FROM sqlite_master WHERE name='market_visibility'").fetchone()[0]
    live.close()
    check("1. живата база не е пипната (няма таблица market_visibility в нея)", has_live_tbl == 0)

    con = sqlite3.connect(db)
    snap = con.execute("SELECT fixture_id, league, MIN(match_date) FROM predictions_snapshot GROUP BY fixture_id ORDER BY 3, 1").fetchall()
    days = sorted({r[2][:10] for r in snap})
    con.close()
    league_of = {f: lg for f, lg, _d in snap}
    from datetime import date
    offs = sorted({(date.fromisoformat(d) - date.today()).days for d in days if 0 <= (date.fromisoformat(d) - date.today()).days < 7})
    list_urls = [u for u, _ in sk.urls_for(db) if not u.startswith("/prognozi/match/")]
    list_urls += [f"/prognozi?day={o}" for o in offs] + [f"/prognozi?day={o}&league={lg}" for o in offs[:2] for lg in ("bulgaria2", "portugal2", "europa_league")]
    match_urls = [f"/prognozi/match/{f}" for f, _lg, _d in snap] + [u for u, _ in sk.urls_for(db) if u.startswith("/prognozi/match/")]
    urls = list(dict.fromkeys(list_urls + match_urls))

    # --- 2. PUBLIC_HIDE=0 байт по байт като стария код
    old_tpl = os.path.join(work, "old_tpl")
    shutil.rmtree(old_tpl, ignore_errors=True)
    shutil.copytree(os.path.join(REPO, "templates"), old_tpl)
    for f in ("prognozi.html", "prognozi_match.html", "_all_sections.html"):
        shutil.copy(os.path.join(BACKUP, f), os.path.join(old_tpl, f))
    os.remove(os.path.join(old_tpl, "_public_sections.html"))
    old = get_all(app_for(os.path.join(BACKUP, "prognozi.py"), db, "old", False, old_tpl), urls)
    new0 = get_all(app_for(os.path.join(REPO, "web", "prognozi.py"), db, "new0", False), urls)
    diff = [u for u in urls if old[u] != new0[u]]
    n200 = sum(1 for u in urls if old[u][0] == 200)
    check(f"2. PUBLIC_HIDE=0: {len(urls)} страници ({n200} с 200) байт по байт като старото", not diff, ", ".join(diff[:5]))

    # --- 3. PUBLIC_HIDE=1
    new1 = get_all(app_for(os.path.join(REPO, "web", "prognozi.py"), db, "new1", True), urls)
    m_urls = [u for u in match_urls if u in new1]
    bad_status = [u for u in m_urls if new1[u][0] != (404 if league_of.get(int(u.rsplit("/", 1)[1])) == "portugal2" else old[u][0])]
    check("3. страниците на мачовете: 200 (portugal2 - 404)", not bad_status, ", ".join(bad_status[:5]))
    p2 = [u for u in m_urls if league_of.get(int(u.rsplit("/", 1)[1])) == "portugal2"]
    check("3. portugal2: страницата на мача - 404 („няма такъв мач“)", p2 and all(new1[u][0] == 404 for u in p2), f"{len(p2)} мача")
    shown = {u: new1[u][1].decode() for u in urls if new1[u][0] == 200}
    # „проверен“ като отделна дума (етикетът); „проверени прогнози“ в отчета горе в списъка не е етикет
    for word in ("mbadge", r"проверен(?![а-я])", "експериментален", "Показваме всичко", r"\(експериментално", "exp-tag", r"експ\.", "няма данни"):
        hit = [u for u, h in shown.items() if re.search(word, h)]
        check(f"3. никъде „{word}“", not hit, ", ".join(hit[:3]))
    no_foot = [u for u in m_urls if new1[u][0] == 200 and FOOT not in new1[u][1].decode()]
    check("3. изречението долу на всяка страница на мач", not no_foot, f"{len(m_urls) - len(no_foot)} страници; без: {', '.join(no_foot[:3])}")
    check("3. на PUBLIC_HIDE=0 изречението го няма", not any(FOOT in new0[u][1].decode() for u in urls if new0[u][0] == 200))
    for t in ("Полувреме / край", "Картони"):
        hit = [u for u in m_urls if new1[u][0] == 200 and t in titles(new1[u][1].decode())]
        check(f"3. няма секция „{t}“ (не е мерен)", not hit, ", ".join(hit[:3]))
    corner_bad = []
    for u in m_urls:
        if new1[u][0] == 200:
            c = section(new1[u][1].decode(), "Корнери")
            labels = re.findall(r'<span class="olabel">(.*?)</span>', c)
            if labels and sorted(labels) != ["Над 9.5", "Под 9.5"]:
                corner_bad.append(u)
    check("3. корнери - само общо 9.5", not corner_bad, ", ".join(corner_bad[:3]))
    empty = [u for u in m_urls if new1[u][0] == 200 and re.search(r'<div class="msection-title">[^<]*</div>\s*</div>', new1[u][1].decode())]
    check("3. няма празни секции", not empty, ", ".join(empty[:3]))

    # скритите комбинации (правило б) - пазарът го няма на страниците на лигата; видимите - ги има
    hidden_b = [(lg, m) for (lg, m), r in vis.items() if lg != mv.ALL and r["rule"] in ("б", "б*")]
    probe = {"ou35": ("Голове", "Над 3.5"), "btts": ("Двата отбора отбелязват", None), "corners95": ("Корнери", None),
             "ou15": ("Голове", "Над 1.5"), "ou25": ("Голове", "Над 2.5"), "1x2": ("Краен резултат", None), "ht": ("Полувреме", None),
             "first": ("Пръв гол", None), "cs": ("Точен резултат (най-вероятните)", None)}
    for lg, m in hidden_b:
        if m not in probe:
            continue
        sec_t, lab = probe[m]
        pages = [u for u in m_urls if league_of.get(int(u.rsplit("/", 1)[1])) == lg and new1[u][0] == 200]
        olds = [u for u in pages if (sec_t in titles(old[u][1].decode())) and (lab is None or lab in section(old[u][1].decode(), sec_t))]
        still = [u for u in pages if (sec_t in titles(new1[u][1].decode())) and (lab is None or lab in section(new1[u][1].decode(), sec_t))]
        check(f"3. скрита комбинация {lg} / {mv.MARKET_NAMES[m]}: я няма на страниците", bool(olds) and not still,
              f"преди на {len(olds)} от {len(pages)} страници, сега на {len(still)}")

    # списъкът
    lst = {u: shown[u] for u in list_urls if u in shown}
    p2_in_list = [u for u, h in lst.items() if any(f"/prognozi/match/{f}\"" in h for f in (x for x, lg_, _d in snap if lg_ == "portugal2"))
                  or 'value="portugal2"' in h]
    check("3. списъкът: portugal2 я няма (нито мачове, нито в менюто)", not p2_in_list, ", ".join(p2_in_list[:3]))
    p2_before = [u for u in list_urls if old[u][0] == 200 and 'value="portugal2"' in old[u][1].decode()]
    check("3. (за сведение) portugal2 в менюто на списъка преди", True,
          f"{len(p2_before)} страници (0 = и досега не е в списъка: нито един неин пазар не минава доверието)")
    b2 = [f for f, lg, _d in snap if lg == "bulgaria2"]
    b2_rows = sum(h.count(f"/prognozi/match/{f}\"") > 0 for u, h in lst.items() if u.startswith("/prognozi?day=") and "league" not in u for f in b2)
    x12_vis = mv.visible("bulgaria2", "home_win", vis)
    check("3. списъкът: bulgaria2 с 1/X/2 без „експ.“ (1X2 видим за bulgaria2)" if x12_vis else "3. списъкът: bulgaria2 без 1X2",
          b2_rows > 0, f"{b2_rows} реда на bulgaria2 в дните")
    rows_old = sum(old[u][1].decode().count('class="predrow"') for u in list_urls if u.startswith("/prognozi?day=") and "league" not in u)
    rows_new = sum(new1[u][1].decode().count('class="predrow"') for u in list_urls if u.startswith("/prognozi?day=") and "league" not in u)
    check("3. (за сведение) редове в списъка по дни преди/след", True, f"{rows_old} / {rows_new}")

    # лиги и бройки пазари на мач (преди = PUBLIC_HIDE=0, т.е. сегашният пълен изглед; след = PUBLIC_HIDE=1)
    per = defaultdict(lambda: [0, 0, 0])
    for u in m_urls:
        f = int(u.rsplit("/", 1)[1])
        lg = league_of.get(f)
        if lg is None or new0[u][0] != 200:
            continue
        per[lg][0] += 1
        per[lg][1] += new0[u][1].decode().count('<div class="mrow">')
        per[lg][2] += new1[u][1].decode().count('<div class="mrow">') if new1[u][0] == 200 else 0
    with open(OUT_CSV, "w", encoding="utf-8") as fo:
        fo.write("league,matches,markets_per_match_before,markets_per_match_after\n")
        for lg in sorted(per):
            n, a, b = per[lg]
            fo.write(f"{lg},{n},{a / n:.1f},{b / n:.1f}\n")
    leagues_ok = [lg for lg in per if per[lg][2] > 0]
    check("3. страници на мачове от поне 4 лиги (вкл. bulgaria2) с пазари", len(leagues_ok) >= 4 and "bulgaria2" in leagues_ok,
          f"{len(leagues_ok)} лиги: {', '.join(sorted(leagues_ok))}")

    # текстът
    txt_bad = [u for u in m_urls if new1[u][0] == 200 and "Моделът (експериментално" in new1[u][1].decode()]
    txt_before = [u for u in m_urls if new0[u][0] == 200 and "Моделът (експериментално" in new0[u][1].decode()]
    txt_after = [u for u in txt_before if "Моделът дава" in new1[u][1].decode()]
    check("3. текстът: „Моделът (експериментално…)“ -> „Моделът“", not txt_bad and len(txt_after) == len([u for u in txt_before if new1[u][0] == 200]),
          f"преди с „експериментално“: {len(txt_before)}; сега „Моделът дава“ на {len(txt_after)}")

    # --- 4. таблицата липсва
    db2 = os.path.join(work, "test_notbl.db")
    shutil.copy(db, db2)
    c2 = sqlite3.connect(db2)
    c2.execute("DROP TABLE market_visibility")
    c2.commit()
    c2.close()
    nt = get_all(app_for(os.path.join(REPO, "web", "prognozi.py"), db2, "notbl", True), urls)
    bad = [u for u in urls if nt[u][0] not in (200, 404) or nt[u][0] != new1[u][0]]
    check("4. без таблица: страниците 200 (portugal2 - 404), както с таблицата", not bad, ", ".join(bad[:3]))
    leak = [u for u in m_urls if nt[u][0] == 200 and any(t in titles(nt[u][1].decode()) for t in ("Полувреме / край", "Картони"))]
    check("4. без таблица: постоянните правила важат (няма полувреме/край, картони)", not leak)

    # --- 5. админът
    from flask import Flask
    from web.model_admin import register_model_admin_routes
    for dbx, label, want in ((db, "с таблица", "Скрити и защо"), (db2, "без таблица", "още не е смятана")):
        app = Flask(f"adm_{label}", template_folder=os.path.join(REPO, "templates"))
        app.secret_key = "test"
        app.config.update(TESTING=True, VISIBILITY_DB=dbx)
        register_model_admin_routes(app, {})
        r = app.test_client().get("/admin/model")
        h = r.data.decode()
        check(f"5. /admin/model {label}: 200, „Видимост на пазарите“", r.status_code == 200 and "Видимост на пазарите" in h and want in h,
              f"{r.status_code}")
        if label == "с таблица":
            with open(os.path.join(work, "admin_model.html"), "w", encoding="utf-8") as fo:
                fo.write(h)
    for u in [u for u in m_urls if new1[u][0] == 200][:1]:
        with open(os.path.join(work, "match_public.html"), "wb") as fo:
            fo.write(new1[u][1])

    ok = sum(1 for _n, o, _d in RESULTS if o)
    lines = [f"ZADACHA_SKRIVANE тест на копие ({len(RESULTS)} проверки, {ok} OK)", ""] + [
        ("OK   " if o else "FAIL ") + n + (f" - {d}" if d else "") for n, o, d in RESULTS]
    lines += ["", "Брой пазари на мач по лиги (преди = PUBLIC_HIDE=0, пълният изглед сега; след = PUBLIC_HIDE=1): " + os.path.basename(OUT_CSV)]
    with open(OUT_TXT, "w", encoding="utf-8") as fo:
        fo.write("\n".join(lines) + "\n")
    print(f"\n{ok}/{len(RESULTS)} OK")
    return ok == len(RESULTS)


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1]) else 1)
