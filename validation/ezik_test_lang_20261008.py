"""validation/ezik_test_lang_20261008.py - ZADACHA_EZIK: тест на езика (бутон БГ | EN) на КОПИЕ на базата, отделно Flask приложение.
Вика се от validation/ezik_test_20261008.py (етап all). Старият код за сравнение = ревизия след т.0б, преди езика (b8a2d76).

1. LANG_SWITCH=0: всички публични страници байт по байт като стария код (PUBLIC_HIDE=0 и 1), и с ?lang=en / бисквитка lang=en.
2. LANG_SWITCH=1, bg: байт по байт като LANG_SWITCH=0, освен бутона, hreflang връзките (+ стила на бутона) и заглавката Vary: Cookie.
3. LANG_SWITCH=1, en: „/“, „/prognozi“ (двата таба, филтър по лига, „Покажи още“), всички мачове от снимката (вкл. bulgaria2 и мач с
   текст и надпис след съставите) - нула кирилски символи; i18n_missing_log празен; същите пазари и числа като на български.
4. Бисквитката: ?lang=en -> после без параметър = английски; ?lang=bg -> обратно; друга стойност -> bg. Бутонът пази day/status/league/limit.
5. Извън публичните страници (маршрут извън Blueprint-а, _tokens.html и филтъра bg_day) - с бисквитка lang=en байт по байт както без нея.
6. Всеки t("...") в шаблоните и всяко заглавие/етикет/причина от web/prognozi.py има превод.
"""
import json
import os
import re
import sqlite3
import subprocess

REPO = "/home/inkas/sportbg-predictor"
CYR = re.compile(r"[А-Яа-яЁёЪъ]")
NEW_PY = os.path.join(REPO, "web", "prognozi.py")


def strip_switch(h):
    """LANG_SWITCH=1 -> махаме само бутона и <link hreflang>+стила (това, което превключвателят добавя)."""
    h = re.sub(r'\n\n<link rel="alternate" hreflang="bg" href="[^"]*">\n<link rel="alternate" hreflang="en" href="[^"]*">\n<style>\n  \.langsw.*?</style>',
               "", h, flags=re.S)
    h = re.sub(r'\n    \n    <div class="langsw">.*?</div>', "", h, flags=re.S)
    return h


def numbers(h):
    """Пазарите и числата на страницата: процентите в клетките (мач) и 1/X/2 (списък) + връзките към мачовете, в реда им."""
    return (re.findall(r'<span class="opct">([^<]*)</span>', h), re.findall(r'<span class="op">([^<]*)</span>', h),
            re.findall(r'href="(/prognozi/match/\d+)"', h), len(re.findall(r'<div class="msection">', h)),
            len(re.findall(r'<div class="mrow">', h)))


def add_lineups_case(db, lg_pref=("bulgaria2", "bulgaria")):
    """Днес в снимката няма мач след съставите. В КОПИЕТО: на един предстоящ мач (bulgaria2, иначе bulgaria) добавяме изречението
    „след съставите“ - същата функция match_text.s_lineups, с процентите от снимката и измислени „преди“ (±3) - и has_lineups=1.
    -> fixture_id."""
    import match_text as mt
    con = sqlite3.connect(db)
    for lg in lg_pref:
        r = con.execute("SELECT m.fixture_id, m.sentences FROM match_text m JOIN predictions_snapshot s ON s.fixture_id = m.fixture_id "
                        "WHERE s.league = ? AND m.sentences LIKE '%text_en%' GROUP BY m.fixture_id ORDER BY m.fixture_id LIMIT 1", (lg,)).fetchone()
        if r:
            break
    fid, js = r
    ht, at = con.execute("SELECT home_team, away_team FROM predictions_snapshot WHERE fixture_id = ? LIMIT 1", (fid,)).fetchone()
    pc = {c: p for c, p in con.execute("SELECT market_code, pick_pct FROM predictions_snapshot WHERE fixture_id = ? AND market_code IN "
                                       "('home_win','draw','away_win')", (fid,))}
    pre = {"home_win": pc["home_win"] + 3, "draw": pc["draw"] - 1, "away_win": pc["away_win"] - 2}
    s = mt.s_lineups(mt.team_name(ht, lg), mt.team_name(at, lg), pc, pre, {"h": False, "a": True}, {"h": 4}, (ht, at))
    ss = [s] + json.loads(js)
    con.execute("UPDATE match_text SET sentences = ?, has_lineups = 1 WHERE fixture_id = ?", (json.dumps(ss, ensure_ascii=False), fid))
    con.commit()
    con.close()
    return fid


def run_lang(work, db, rev0, check, app_for, get_all, urls, old_code, rev="b8a2d76"):
    import config
    import i18n
    i18n.MISSING_LOG = os.path.join(work, "i18n_missing_log.txt")
    if os.path.exists(i18n.MISSING_LOG):
        os.remove(i18n.MISSING_LOG)
    i18n._missing_seen.clear()
    # текстът на мача с НОВИЯ match_text.refresh() върху копието (английските изречения "text_en"); логът - не в живия
    import match_text as mt
    config.MATCH_TEXT = True
    mt.LOG_PATH = os.path.join(work, "match_text_log.txt")
    n_txt, _secs = mt.refresh(db_path=db)
    check("0. текстът на мача пресметнат наново с новия код върху копието", n_txt > 0, f"{n_txt} мача")
    old_py, old_tpl = old_code(work, rev)
    lst, matches, league_of = urls(db)
    allu = lst + matches

    # 1. LANG_SWITCH=0
    for hide in (False, True):
        o = get_all(app_for(old_py, db, f"lo{hide}", hide, old_tpl), allu)
        n = get_all(app_for(NEW_PY, db, f"ln{hide}", hide, lang_switch=False), allu)
        d = [u for u in allu if o[u][:2] != n[u][:2]]
        check(f"1. LANG_SWITCH=0, PUBLIC_HIDE={int(hide)}: всички публични страници байт по байт като стария код", not d,
              f"{len(allu)} страници; различни: {d[:5]}")
        q = [u + ("&" if "?" in u else "?") + "lang=en" for u in allu]
        nq = get_all(app_for(NEW_PY, db, f"lq{hide}", hide, lang_switch=False), q)
        nc = get_all(app_for(NEW_PY, db, f"lc{hide}", hide, lang_switch=False), allu, cookie="en")
        d = [u for u, uq in zip(allu, q) if nq[uq][:2] != o[u][:2] or nc[u][:2] != o[u][:2]]
        check(f"1. LANG_SWITCH=0, PUBLIC_HIDE={int(hide)}: ?lang=en и бисквитка lang=en се пренебрегват (страниците като старите)", not d,
              ", ".join(d[:5]))
        sc = [u for u in allu if "Set-Cookie" in nq[u + ("&" if "?" in u else "?") + "lang=en"][2] or "Cookie" in n[u][2].get("Vary", "")]
        check(f"1. LANG_SWITCH=0, PUBLIC_HIDE={int(hide)}: без бисквитка и без Vary: Cookie", not sc, ", ".join(sc[:5]))

    # мач след съставите (в копието)
    import layer_live
    from datetime import datetime
    lu_fid = add_lineups_case(db)
    real_ft = layer_live.final_time
    layer_live.final_time = lambda f: datetime(2020, 1, 1, 12, 5) if int(f) == lu_fid else real_ft(f)
    matches_lu = matches + [f"/prognozi/match/{lu_fid}"]
    allu = lst + matches_lu

    for hide in (True, False):
        H = int(hide)
        a0 = get_all(app_for(NEW_PY, db, f"z{hide}", hide, lang_switch=False), allu)
        a1 = get_all(app_for(NEW_PY, db, f"b{hide}", hide, lang_switch=True), allu)
        # 2. bg
        d = [u for u in allu if a0[u][0] != a1[u][0] or a0[u][1] != strip_switch(a1[u][1].decode()).encode()]
        check(f"2. LANG_SWITCH=1, bg, PUBLIC_HIDE={H}: байт по байт като LANG_SWITCH=0 освен бутона, hreflang и стила му", not d,
              f"{len(allu)} страници; различни: {d[:5]}")
        btn = [u for u in allu if a1[u][0] == 200 and ('<div class="langsw">' not in a1[u][1].decode() or 'hreflang="en"' not in a1[u][1].decode()
                                                         or '<html lang="bg">' not in a1[u][1].decode())]
        check(f"2. LANG_SWITCH=1, bg, PUBLIC_HIDE={H}: бутон, hreflang и <html lang=\"bg\"> на всяка страница", not btn, ", ".join(btn[:5]))
        vary = [u for u in allu if "Cookie" not in a1[u][2].get("Vary", "")]
        check(f"2. LANG_SWITCH=1, PUBLIC_HIDE={H}: Vary: Cookie на всеки публичен отговор (вкл. 404)", not vary, ", ".join(vary[:5]))
        # 3. en
        e1 = get_all(app_for(NEW_PY, db, f"e{hide}", hide, lang_switch=True), allu, cookie="en")
        st_d = [u for u in allu if e1[u][0] != a1[u][0]]
        check(f"3. en, PUBLIC_HIDE={H}: същите кодове на отговор като на български", not st_d, ", ".join(st_d[:5]))
        cyr = {u: sorted(set(CYR.findall(e1[u][1].decode())))[:8] for u in allu if CYR.search(e1[u][1].decode())}
        check(f"3. en, PUBLIC_HIDE={H}: нула кирилски символи в {len(allu)} отговора (списък по дни, двата таба, лиги, „Покажи още“, "
              f"всички мачове)", not cyr, "; ".join(f"{u}: {''.join(v)}" for u, v in list(cyr.items())[:5]))
        nl = [u for u in allu if '<html lang="en">' not in e1[u][1].decode()]
        check(f"3. en, PUBLIC_HIDE={H}: <html lang=\"en\">", not nl, ", ".join(nl[:5]))
        nd = [u for u in allu if a1[u][0] == 200 and numbers(a1[u][1].decode()) != numbers(e1[u][1].decode())]
        check(f"3. en, PUBLIC_HIDE={H}: същите пазари и числа като на български (секции, редове, проценти, 1/X/2, мачовете в списъка)", not nd,
              ", ".join(nd[:5]))
        if hide:
            ml = sorted({league_of.get(int(u.rsplit("/", 1)[1])) for u in matches_lu if e1[u][0] == 200 and 'class="msection"' in e1[u][1].decode()} - {None})
            check("3. en: страници на мачове с пазари от поне 4 лиги, вкл. bulgaria2", len(ml) >= 4 and "bulgaria2" in ml, f"{len(ml)} лиги: {', '.join(ml)}")
            h = e1[f"/prognozi/match/{lu_fid}"][1].decode()
            ok = "After the line-ups were announced" in h and "updated after the line-ups" in h and "About the match" in h
            check("3. en: мач с текст след съставите - „After the line-ups were announced…“ и надписът „updated after the line-ups HH:MM“",
                  ok, f"мач {lu_fid} ({league_of.get(lu_fid)})")
            hb = a1[f"/prognozi/match/{lu_fid}"][1].decode()
            check("3. bg: същият мач - „След обявяването на съставите“ и „обновено след съставите“",
                  "След обявяването на съставите" in hb and "обновено след съставите" in hb)
            texts_en = sum(1 for u in matches_lu if "About the match" in e1[u][1].decode())
            texts_bg = sum(1 for u in matches_lu if "За мача" in a1[u][1].decode())
            check("3. en: текстът на мача е на английските страници там, където е и на българските", texts_en == texts_bg,
                  f"en {texts_en} / bg {texts_bg}")
            for u, words in (("/prognozi?day=0", ["Predictions", "Upcoming", "Finished"]),
                             ("/prognozi?status=finished&limit=50", ["Showing", "Show 25 more"])):
                hh = e1[u][1].decode()
                miss = [w for w in words if w not in hh]
                check(f"3. en: {u} - {', '.join(words)}", not miss, ", ".join(miss))
    miss_log = open(i18n.MISSING_LOG).read() if os.path.exists(i18n.MISSING_LOG) else ""
    check("3. i18n_missing_log празен (няма текст без превод)", not miss_log and not i18n._missing_seen, miss_log[:300])

    # 4. бисквитката и бутонът
    app = app_for(NEW_PY, db, "ck", True, lang_switch=True)
    c = app.test_client()
    r1 = c.get("/prognozi?lang=en")
    sc = r1.headers.get("Set-Cookie", "")
    r2 = c.get("/prognozi")
    r3 = c.get("/prognozi?lang=bg")
    r4 = c.get("/prognozi")
    ok = ("lang=en" in sc and "Max-Age=31536000" in sc and "SameSite=Lax" in sc and b'<html lang="en">' in r1.data
          and b'<html lang="en">' in r2.data and b'<html lang="bg">' in r3.data and b'<html lang="bg">' in r4.data)
    check("4. ?lang=en -> бисквитка (1 година, SameSite=Lax), после без параметър - английски; ?lang=bg -> обратно", ok, sc)
    m0 = matches[0]
    r5, r6 = c.get(m0 + "?lang=en"), c.get("/")
    check("4. бисквитката важи и между страниците (мач -> начална)", b'<html lang="en">' in r6.data and b'<html lang="en">' in r5.data)
    c2 = app.test_client()
    r7 = c2.get("/prognozi?lang=xx")
    c2.set_cookie("lang", "de")
    r8 = c2.get("/prognozi")
    check("4. друга стойност (?lang=xx, бисквитка lang=de) -> bg, без бисквитка", b'<html lang="bg">' in r7.data and b'<html lang="bg">' in r8.data
          and "Set-Cookie" not in r7.headers)
    r9 = app.test_client().get("/prognozi?day=2&status=finished&league=england&limit=50&lang=en&x=1").data.decode()
    want = ['href="/prognozi?day=2&amp;status=finished&amp;league=england&amp;limit=50&amp;lang=bg"',
            'href="/prognozi?day=2&amp;status=finished&amp;league=england&amp;limit=50&amp;lang=en"']
    check("4. бутонът: същият адрес със същите параметри (day, status, league, limit) + lang=, текущият удебелен",
          all(w in r9 for w in want) and 'lang="en" class="on"' in r9, "")
    r10 = app.test_client().get(m0 + "?lang=en").data.decode()
    check("4. бутонът на страницата на мача: същият адрес + lang=", f'href="{m0}?lang=bg"' in r10 and f'href="{m0}?lang=en"' in r10)

    # 5. извън Blueprint-а: _tokens.html и bg_day - с бисквитка lang=en като без нея (и като стария код)
    from flask import render_template_string
    tpl = '{% include "_tokens.html" %}|{{ "2026-10-09 18:00"|bg_day }}|{{ lang is defined }}'
    app = app_for(NEW_PY, db, "probe", True, lang_switch=True)
    app.add_url_rule("/_admin_probe", "admin_probe", lambda: render_template_string(tpl))
    ca = app.test_client()
    p0 = ca.get("/_admin_probe").data
    ca.set_cookie("lang", "en")
    p1 = ca.get("/_admin_probe?lang=en").data
    old_tokens = subprocess.run(["git", "show", f"{rev}:templates/_tokens.html"], capture_output=True, text=True).stdout
    check("5. маршрут извън публичните (като админа): с бисквитка lang=en и ?lang=en - байт по байт както без тях, на български",
          p0 == p1 and "|Пт, 9 окт|False" in p0.decode() and p0.decode().startswith(old_tokens.rstrip("\n")), p1.decode()[-40:])
    hp = ca.get("/_admin_probe?lang=en").headers
    check("5. админът не получава бисквитка и Vary", "Set-Cookie" not in hp and "Cookie" not in hp.get("Vary", ""))

    # 6. покритие на преводите
    import importlib.util
    spec = importlib.util.spec_from_file_location("pz_cov", NEW_PY)
    pz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pz)
    keys = set()
    for f in ("prognozi.html", "prognozi_match.html", "_all_sections.html", "_public_sections.html"):
        src = open(os.path.join(REPO, "templates", f), encoding="utf-8").read()
        keys |= set(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"', src)) | set(re.findall(r"\bt\('((?:[^'\\]|\\.)*)'", src))
    titles = {t for t, _m in pz.MARKET_SECTIONS + pz.ALL_SECTIONS + pz.EXTRA_SECTIONS} | {"Точен резултат", "Точен резултат (най-вероятните)",
                                                                                         "Корнери", "Картони", "няма данни"}
    badges = {"проверен", "експериментален"} | {r for _k, _v, r in pz.MARKET_STATUS if r} | {"слаб в лигата", "малко данни", "плах"}
    labels = {l for _t, ms in pz.ALL_SECTIONS + pz.EXTRA_SECTIONS for m in ms for _c, l in (m if isinstance(m, list) else m[0])}
    labels |= {l for _t, ms in pz.MARKET_SECTIONS for m, _s in ms for _c, l in m}
    no_tr = sorted(k for k in keys | titles | badges if k not in i18n.EN)
    i18n._missing_seen.clear()
    from flask import g
    with app.test_request_context("/"):
        g.lang = "en"
        bad_lab = sorted(l for l in labels if CYR.search(i18n.outcome_label(l)))
    check("6. всеки t(\"...\") в шаблоните, всяко заглавие на секция, етикет и причина има превод; всеки изход се превежда",
          not no_tr and not bad_lab, f"t(): {len(keys)}, заглавия {len(titles)}, етикети/причини {len(badges)}, изходи {len(labels)}; "
          f"без превод: {no_tr[:5]} {bad_lab[:5]}")
    layer_live.final_time = real_ft
    return {"keys": len(keys), "titles": len(titles), "badges": len(badges), "labels": len(labels), "en_dict": len(i18n.EN)}
