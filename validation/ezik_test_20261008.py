"""validation/ezik_test_20261008.py - тест на ZADACHA_EZIK на КОПИЕ на базата, отделно Flask приложение (живото не се пипа).

Старият код = git ревизия (по подразбиране 6e8d333 - преди ZADACHA_EZIK): web/prognozi.py + templates/ от нея, в отделна папка.
Етапи (аргумент):
  0b  - т.0б: PUBLIC_HIDE=0 -> всички публични страници байт по байт като стария код; PUBLIC_HIDE=1 -> на списъка няма отчета
        (ред горе, „Вчера“, „Пълен отчет“, изречението в подзаглавието), страниците на мачовете - само връзката „Как да чета“
        сочи #howto (не #full-report); никъде висяща #full-report.
  all - т.0б + езикът (виж run_lang).
Изход: validation/ezik_test_20261008.txt
Употреба: venv/bin/python3 validation/ezik_test_20261008.py <празна папка> [0b|all] [стара ревизия]
"""
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, REPO)
os.chdir(REPO)
sys.path.insert(0, os.path.join(REPO, "validation"))
import config  # noqa: E402
import skorost_20260924 as sk  # noqa: E402

OUT_TXT = os.path.join(REPO, "validation", "ezik_test_20261008.txt")
RESULTS = []
CYR = re.compile(r"[А-Яа-яЁёЪъ]")


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(("OK   " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def copy_db(dst):
    s = sqlite3.connect(f"file:{os.path.join(REPO, 'predictions.db')}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    s.backup(d)
    d.close()
    s.close()


def old_code(work, rev):
    """web/prognozi.py + templates/ от git ревизия rev -> (път до prognozi.py, папка с шаблоните)."""
    d = os.path.join(work, f"old_{rev}")
    if not os.path.isdir(d):
        os.makedirs(d)
        subprocess.run(f"git archive {rev} templates web/prognozi.py | tar -x -C {d}", shell=True, check=True)
    return os.path.join(d, "web", "prognozi.py"), os.path.join(d, "templates")


def point_to(db):
    import extra_markets
    import match_text
    import market_visibility as mv
    extra_markets.DB_PATH = db
    match_text.DB_PATH = db
    mv.DB_PATH = db
    mv._cache.update(at=0.0, rows=None)


def app_for(prognozi_path, db, tag, hide, templates=None, lang_switch=False):
    config.PUBLIC_HIDE = hide
    config.LANG_SWITCH = lang_switch
    point_to(db)
    app = sk.make_app(prognozi_path, os.path.join(REPO, "system_tracker.py"), db, tag)
    if templates:
        app.template_folder = templates
        app.jinja_loader.searchpath = [templates]
    return app


def get_all(app, urls, cookie=None):
    c = app.test_client()
    if cookie:
        c.set_cookie("lang", cookie)
    return {u: (r.status_code, r.data, dict(r.headers)) for u in urls for r in [c.get(u)]}


def urls(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    snap = con.execute("SELECT fixture_id, league, MIN(match_date) FROM predictions_snapshot GROUP BY fixture_id ORDER BY 3, 1").fetchall()
    fin = [r[0] for r in con.execute("SELECT fixture_id FROM predictions_log WHERE status IN ('won','lost') GROUP BY fixture_id "
                                     "ORDER BY MAX(match_date) DESC LIMIT 6")]
    con.close()
    leagues = sorted({lg for _f, lg, _d in snap})
    lst = ["/", "/prognozi"] + [f"/prognozi?day={d}" for d in range(7)] + [f"/prognozi?day={d}&status=finished" for d in (0, 3)]
    lst += ["/prognozi?status=finished&limit=50", "/prognozi?status=finished&league=bulgaria", "/prognozi?status=finished&league=england&limit=50"]
    lst += [f"/prognozi?day={d}&league={lg}" for d in (0, 1, 2) for lg in leagues]
    lst += ["/prognozi?day=xx", "/prognozi?status=skipped", "/prognozi?league=nope"]
    matches = [f"/prognozi/match/{f}" for f, _lg, _d in snap] + [f"/prognozi/match/{f}" for f in fin] + ["/prognozi/match/1"]
    return lst, matches, {f: lg for f, lg, _d in snap}


def run_0b(work, db, rev):
    old_py, old_tpl = old_code(work, rev)
    lst, matches, _lg = urls(db)
    allu = lst + matches
    o0 = get_all(app_for(old_py, db, "o0", False, old_tpl), allu)
    n0 = get_all(app_for(os.path.join(REPO, "web", "prognozi.py"), db, "n0", False), allu)
    diff = [u for u in allu if o0[u][:2] != n0[u][:2]]
    check("0б. PUBLIC_HIDE=0: всички публични страници байт по байт като стария код", not diff,
          f"{len(allu)} страници; различни: {diff[:5]}")
    o1 = get_all(app_for(old_py, db, "o1", True, old_tpl), allu)
    n1 = get_all(app_for(os.path.join(REPO, "web", "prognozi.py"), db, "n1", True), allu)
    status = [u for u in allu if o1[u][0] != n1[u][0]]
    check("0б. PUBLIC_HIDE=1: същите кодове на отговор", not status, ", ".join(status[:5]))
    gone = ['class="summary-line"', 'class="summary-link"', '#full-report"', 'id="full-report"', 'class="metrics"', "виж пълния отчет", "Вчера: познахме", "Пълен отчет", "обещахме",
            "познахме", "проверени прогнози", "Показваме и какво сме познали", "уредени прогнози до момента", "колко точни са"]
    for w in gone:
        hit = [u for u in allu if n1[u][0] == 200 and w in n1[u][1].decode()]
        check(f"0б. PUBLIC_HIDE=1: никъде „{w}“", not hit, ", ".join(hit[:5]))
    was = sum(1 for u in lst if "обещахме" in o1[u][1].decode())
    check("0б. (за сведение) старият код при PUBLIC_HIDE=1 имаше „обещахме“ на списъка", was > 0, f"{was} от {len(lst)} страници")
    # единствената разлика: махнатите блокове. Махаме ги от стария HTML по същите граници и сравняваме.
    def strip_old(h):
        h = h.replace(" Показваме и какво сме познали, и какво не.", "")
        h = re.sub(r'    <div class="summary-line">.*?</div>\n\n(    \n    <div class="yesterday-line">.*?</div>\n    \n)?', "    ", h, flags=re.S)
        h = re.sub(r'    <div class="report-label" id="full-report">.*?\n    </div>\n\n', "    \n\n", h, flags=re.S)
        h = h.replace('<details class="howto">', '<details class="howto" id="howto">')
        h = h.replace("    </details>\n", '    </details>\n    <script>if (location.hash === "#howto") document.getElementById("howto").open = true;</script>\n')
        h = h.replace('href="/prognozi#full-report"', 'href="/prognozi#howto"')
        return h
    norm = lambda h: re.sub(r"\s+", " ", h)
    other = [u for u in allu if o1[u][0] == 200 and norm(strip_old(o1[u][1].decode())) != norm(n1[u][1].decode())]
    check("0б. PUBLIC_HIDE=1: освен махнатото (и #howto) - всичко останало е както в стария код (без разлика в празните места)", not other,
          ", ".join(other[:5]))
    howto = [u for u in matches if n1[u][0] == 200 and 'href="/prognozi#howto"' not in n1[u][1].decode()]
    check("0б. PUBLIC_HIDE=1: на страницата на мача „Как да чета“ сочи /prognozi#howto, на списъка има id=\"howto\"",
          not howto and all('id="howto"' in n1[u][1].decode() for u in lst if n1[u][0] == 200), ", ".join(howto[:5]))
    # „Вчера“ в админа (web/daily.py) = числото, което беше на публичния списък (стария код, PUBLIC_HIDE=0)
    import system_tracker as st_live
    import evaluation
    import prediction_policy as policy
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    st_live.DB_PATH = db
    y_str = (datetime.now(ZoneInfo("Europe/Sofia")).date() - timedelta(days=1)).isoformat()
    y_rows = [p for p in evaluation.published_picks(st_live.list_predictions(), policy)
              if p["status"] in ("won", "lost") and str(p["match_date"])[:10] == y_str]
    adm = f"Вчера: познахме {sum(p['status'] == 'won' for p in y_rows)} от {len(y_rows)}" if y_rows else None
    pub = re.search(r"Вчера: познахме \d+ от \d+", o0["/prognozi"][1].decode())
    check("0б. „Вчера“ в /admin (сметката на web/daily.py) = числото от публичния списък (стария код)",
          (pub.group(0) if pub else None) == adm, f"публично: {pub.group(0) if pub else 'няма'}; админ: {adm or 'няма'}")
    # и за всеки от последните 30 дни: сметката на админа = сметката на публичния списък (web/prognozi.py: само мачове с уреден ред)
    allp = st_live.list_predictions()
    pub_pk = evaluation.published_picks([r for r in allp if r["fixture_id"] in {x["fixture_id"] for x in allp if x["status"] in ("won", "lost")}], policy)
    adm_pk = evaluation.published_picks(allp, policy)
    def by_day(pk):
        out = {}
        for p in pk:
            if p["status"] in ("won", "lost"):
                d = out.setdefault(str(p["match_date"])[:10], [0, 0])
                d[0] += 1
                d[1] += p["status"] == "won"
        return out
    bp_, ba_ = by_day(pub_pk), by_day(adm_pk)
    days = [(datetime.now(ZoneInfo("Europe/Sofia")).date() - timedelta(days=i)).isoformat() for i in range(1, 31)]
    bad = [d for d in days if bp_.get(d) != ba_.get(d)]
    check("0б. „Вчера“: двете сметки съвпадат за всеки от последните 30 дни", not bad,
          f"дни с уредени: {sum(1 for d in days if d in ba_)}; различни: {bad[:5]}")
    keep = [u for u in lst if n1[u][0] == 200 and ("Как да чета тези числа" not in n1[u][1].decode() or "Приключили" not in n1[u][1].decode())]
    check("0б. PUBLIC_HIDE=1: „Как да чета тези числа“ и табът „Приключили“ остават", not keep, ", ".join(keep[:5]))


def write():
    ok = sum(1 for _n, o, _d in RESULTS if o)
    with open(OUT_TXT, "w", encoding="utf-8") as fh:
        fh.write(f"ZADACHA_EZIK тест на копие ({len(RESULTS)} проверки, {ok} OK)\n\n")
        for n, o, d in RESULTS:
            fh.write(("OK   " if o else "FAIL ") + n + (f" - {d}" if d else "") + "\n")
    print(f"{ok}/{len(RESULTS)} OK")
    return ok == len(RESULTS)


def main():
    work = sys.argv[1]
    stage = sys.argv[2] if len(sys.argv) > 2 else "all"
    rev = sys.argv[3] if len(sys.argv) > 3 else "6e8d333"
    os.makedirs(work, exist_ok=True)
    db = os.path.join(work, "test.db")
    if not os.path.exists(db):
        copy_db(db)
    run_0b(work, db, rev)
    if stage == "all":
        import ezik_test_lang_20261008 as tl
        tl.run_lang(work, db, rev, check, app_for, get_all, urls, old_code)
    sys.exit(0 if write() else 1)


if __name__ == "__main__":
    main()
