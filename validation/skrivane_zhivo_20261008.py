"""ZADACHA_SKRIVANE - проверка на живия сайт след рестарта (08.10.2026).

Само чете: HTTP заявки към живия match-predictor-app (127.0.0.1:8001) и базата в режим ro.
Същите проверки като теста на копие (skrivane_test_20261008.py, т.3 и т.5), но върху живото.
Изход: validation/skrivane_zhivo_20261008.txt
"""
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.parse
import http.cookiejar
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
BASE = "http://127.0.0.1:8001"
OUT = os.path.join(REPO, "validation", "skrivane_zhivo_20261008.txt")
results = []


def check(name, ok, detail=""):
    results.append(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


def get(opener, url):
    try:
        r = opener.open(BASE + url, timeout=60)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def titles(html):
    return re.findall(r'<div class="msection-title">(.*?)</div>', html)


def section(html, title):
    m = re.search(r'<div class="msection-title">' + re.escape(title) + r'</div>(.*?)(?=<div class="msection">|<div class="howto-link">)', html, re.S)
    return m.group(1) if m else ""


def main():
    pub = urllib.request.build_opener()
    con = sqlite3.connect(f"file:{os.path.join(REPO, 'predictions.db')}?mode=ro", uri=True)
    snap = con.execute("SELECT fixture_id, league, MIN(match_date) FROM predictions_snapshot GROUP BY fixture_id ORDER BY 3, 1").fetchall()
    vis_n = con.execute("SELECT count(*) FROM market_visibility").fetchone()[0]
    hidden = con.execute("SELECT league, market FROM market_visibility WHERE visible=0").fetchall()
    con.close()
    check("0. таблица market_visibility на живо", vis_n > 0, f"{vis_n} реда; скрити: {hidden}")

    days = sorted({r[2][:10] for r in snap})
    offs = sorted({(date.fromisoformat(d) - date.today()).days for d in days if 0 <= (date.fromisoformat(d) - date.today()).days < 7})

    # списъкът
    list_urls = ["/", "/prognozi"] + [f"/prognozi?day={o}" for o in offs]
    lst = {}
    for u in list_urls:
        lst[u] = get(pub, u)
    bad = [u for u, (s, _h) in lst.items() if s != 200]
    check("1. списъкът - всички 200", not bad, f"{len(lst)} страници; не 200: {bad}")
    exp = [u for u, (_s, h) in lst.items() if re.search(r"експ\.|exp-tag", h)]
    check("1. списъкът - без „експ.“", not exp, ", ".join(exp))
    p2 = [f for f, lg, _d in snap if lg == "portugal2"]
    p2_in = [u for u, (_s, h) in lst.items() if any(f'/prognozi/match/{f}"' in h for f in p2) or "league=portugal2" in h]
    check("1. списъкът - portugal2 я няма (мачове и меню)", not p2_in, f"мачове на portugal2 в снимката: {len(p2)}; виждат се в: {p2_in}")
    b2 = [f for f, lg, _d in snap if lg == "bulgaria2"]
    b2_rows = sum(any(f'/prognozi/match/{f}"' in h for f in b2) for u, (_s, h) in lst.items() if u.startswith("/prognozi?day="))
    check("1. списъкът - bulgaria2 присъства", b2_rows > 0 or not b2, f"дни с мачове на bulgaria2: {b2_rows}")

    # страниците на мачовете - всички мачове в снимката
    pages = {}
    for f, lg, _d in snap:
        pages[f] = (lg,) + get(pub, f"/prognozi/match/{f}")
    not_ok = [(f, lg, s) for f, (lg, s, _h) in pages.items() if (s != 404 if lg == "portugal2" else s != 200)]
    check("2. страниците на мачовете: 200 (portugal2 - 404)", not not_ok, f"{len(pages)} мача; разминавания: {not_ok[:5]}")
    shown = {f: h for f, (lg, s, h) in pages.items() if s == 200}
    for word in ("mbadge", r"проверен(?![а-я])", "експериментален", "Показваме всичко", r"\(експериментално", "exp-tag", r"експ\.", "няма данни"):
        hit = [f for f, h in shown.items() if re.search(word, h)]
        check(f"2. никъде „{word}“", not hit, ", ".join(map(str, hit[:5])))
    foot = "Не са гаранция за резултат."
    miss = [f for f, h in shown.items() if foot not in h]
    check("2. изречението долу на всяка страница", not miss, f"{len(shown)} страници; без: {miss[:5]}")
    for t in ("Полувреме / край", "Картони"):
        hit = [f for f, h in shown.items() if t in titles(h)]
        check(f"2. няма секция „{t}“", not hit, ", ".join(map(str, hit[:5])))
    corner_bad = []
    for f, h in shown.items():
        labels = re.findall(r'<span class="olabel">(.*?)</span>', section(h, "Корнери"))
        if any("9.5" not in l for l in labels):
            corner_bad.append(f)
    check("2. корнери - само общо 9.5", not corner_bad, ", ".join(map(str, corner_bad[:5])))
    empty = [f for f, h in shown.items() if re.search(r'<div class="msection-title">[^<]*</div>\s*</div>', h)]
    check("2. няма празни секции", not empty, ", ".join(map(str, empty[:5])))
    eu = [f for f, (lg, s, h) in pages.items() if lg == "europa_league" and s == 200]
    eu35 = [f for f in eu if "Над 3.5" in section(shown[f], "Голове")]
    euc = [f for f in eu if "Корнери" in titles(shown[f])]
    check("2. europa_league - няма над/под 3.5", not eu35, f"{len(eu)} страници; с 3.5: {len(eu35)}")
    check("2. europa_league - няма корнери 9.5", not euc, f"{len(eu)} страници; с корнери: {len(euc)}")
    leagues = sorted({lg for f, (lg, s, h) in pages.items() if s == 200 and titles(h)})
    check("2. страници с пазари по лиги", len(leagues) >= 4 and ("bulgaria2" in leagues or not b2), f"{len(leagues)} лиги: {', '.join(leagues)}")

    # админът
    cj = http.cookiejar.CookieJar()
    adm = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    import config
    data = urllib.parse.urlencode({"password": config.LOGIN_PASSWORD}).encode()
    try:
        adm.open(BASE + "/1", data=data, timeout=30)
    except urllib.error.HTTPError:
        pass
    s, h = get(adm, "/admin/model")
    check("3. /admin/model с паролата: 200, „Видимост на пазарите“", s == 200 and "Видимост на пазарите" in h, f"код {s}")
    noauth = urllib.request.build_opener(type("NoRedir", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *a, **k: None})())
    s2, _ = get(noauth, "/admin/model")
    check("3. /admin/model без парола - не се показва", s2 in (302, 401, 403), f"код {s2}")
    for u in ("/admin", "/results"):
        s3, _ = get(adm, u)
        check(f"3. {u} (админ) - 200", s3 == 200, f"код {s3}")
    con = sqlite3.connect(f"file:{os.path.join(REPO, 'predictions.db')}?mode=ro", uri=True)
    rows = con.execute("SELECT fixture_id, league, home_team, away_team, MIN(match_date) FROM predictions_snapshot "
                       "WHERE league IN ('bulgaria', 'europa_league', 'portugal2') GROUP BY fixture_id ORDER BY 5").fetchall()
    con.close()
    picked = {}
    for f, lg, ht, at, d in rows:
        picked.setdefault(lg, (f, lg, ht, at, d))
    for f, lg, ht, at, d in picked.values():
        q = urllib.parse.urlencode({"league": lg, "fixture_id": f, "home": ht, "away": at, "date": d})
        s4, h4 = get(adm, f"/match_detail?{q}")
        check(f"3. админската страница на мач ({lg}) - 200, пълният изглед", s4 == 200, f"код {s4}")

    ok = sum(r.startswith("OK") for r in results)
    head = f"ZADACHA_SKRIVANE - проверка на живия сайт след рестарта ({time.strftime('%d.%m.%Y %H:%M UTC', time.gmtime())}), {len(results)} проверки, {ok} OK\n"
    with open(OUT, "w") as fh:
        fh.write(head + "\n" + "\n".join(results) + "\n")
    print(head)
    print("\n".join(results))


if __name__ == "__main__":
    main()
