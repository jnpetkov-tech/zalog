"""validation/chestno_test_20261009.py - ZADACHA_CHESTNO: тест на КОПИЕ на базата, отделно Flask приложение (живото не се пипа).

Етапи:
  before <папка> - пуска СЕГАШНИЯ код (преди промяната) и пази HTML-а в <папка>/before/
  after  <папка> - пуска новия код, пази HTML-а в <папка>/after/ и сравнява с before
Три настройки: PUBLIC_HIDE=1 (както на живо), PUBLIC_HIDE=0 + SHOW_ALL=1, PUBLIC_HIDE=0 + SHOW_ALL=0; всяка на bg и en (LANG_SWITCH=1).
Страници: списъкът (всички варианти от ezik_test.urls) + всички мачове от снимката + 6 приключили + несъществуващ.
Единствената разрешена разлика: при PUBLIC_HIDE=1 кутията „⚠️ Честно казано засега“ (<div class="box warn">…</div> в „Как да чета“)
е заменена с обикновена кутия „Добре е да знаеш“ (NEW_BOX). При PUBLIC_HIDE=0 - байт по байт както преди.
Изход: validation/chestno_test_20261009.txt
"""
import os
import re
import sys

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, os.path.join(REPO, "validation"))
import ezik_test_20261008 as et  # noqa: E402
import config  # noqa: E402

OUT_TXT = os.path.join(REPO, "validation", "chestno_test_20261009.txt")
CONFIGS = {"hide1": (True, False), "hide0_all": (False, True), "hide0": (False, False)}
CYR = re.compile(r"[А-Яа-яЁёЪъ]")
OLD_WORDS = ["печелившо", "отрицателен", "описателни", "Честно казано", "profitable", "negative", "descriptive", "To be honest"]
NEW_BOX = {
    "bg": ('<div class="box">\n          <h2 style="margin-top:0;">Добре е да знаеш</h2>\n'
           '          <p>Часовете са българско време.</p>\n'
           '          <p>Процентите са оценка на вероятността за всеки изход, изчислена от нашия статистически модел. '
           'Обновяват се, когато излязат нови данни, включително съставите преди мача.</p>\n'
           '          <p style="margin-bottom:0;">Това е статистика, а не съвет за залагане или гаранция за резултат.</p>\n'
           '        </div>'),
    "en": ('<div class="box">\n          <h2 style="margin-top:0;">Good to know</h2>\n'
           '          <p>Times are Bulgarian time.</p>\n'
           "          <p>The percentages are our statistical model&#39;s estimate of the probability of each outcome. "
           'They are updated when new data comes in, including the line-ups before the match.</p>\n'
           '          <p style="margin-bottom:0;">These are statistics, not betting advice or a guarantee of any result.</p>\n'
           '        </div>'),
}
OLD_BOX = re.compile(r'<div class="box warn">\n.*?\n        </div>', re.S)


def snap(work, tag):
    db = os.path.join(work, "test.db")
    if not os.path.exists(db):
        et.copy_db(db)
    lst, matches, _lg = et.urls(db)
    pages = lst + matches
    for cname, (hide, show_all) in CONFIGS.items():
        config.SHOW_ALL = show_all
        app = et.app_for(os.path.join(REPO, "web", "prognozi.py"), db, f"{tag}_{cname}", hide, lang_switch=True)
        for lang in ("bg", "en"):
            res = et.get_all(app, pages, cookie=lang)
            for u, (code, data, _h) in res.items():
                key = f"{cname}|{lang}|{u}"
                fn = os.path.join(work, tag, re.sub(r"[^A-Za-z0-9_]+", "_", key) + ".html")
                os.makedirs(os.path.dirname(fn), exist_ok=True)
                open(fn, "w", encoding="utf-8").write(f"{code}\n" + data.decode("utf-8", "replace"))


def load(work, tag):
    out = {}
    for fn in os.listdir(os.path.join(work, tag)):
        s = open(os.path.join(work, tag, fn), encoding="utf-8").read()
        code, body = s.split("\n", 1)
        out[fn] = (int(code), body)
    return out


def expect(fn, old):
    """старият HTML -> какъвто трябва да е новият."""
    if not fn.startswith("hide1_"):
        return old
    lang = "en" if fn.startswith("hide1_en_") else "bg"
    return OLD_BOX.sub(lambda _m: NEW_BOX[lang], old, count=1)


def compare(work):
    res = []
    check = lambda n, ok, d="": res.append(("OK   " if ok else "FAIL ") + n + (f" - {d}" if d else ""))
    b, a = load(work, "before"), load(work, "after")
    check("същите страници преди и след", set(b) == set(a), f"{len(a)} отговора")
    check("кодовете на отговор - както преди", not [k for k in a if a[k][0] != b[k][0]])
    lists = [k for k in a if "_prognozi_match_" not in k and a[k][0] == 200]
    for lang in ("bg", "en"):
        main = f"hide1_{lang}_prognozi.html"
        check(f"/prognozi на {lang} (PUBLIC_HIDE=1) - 200", a.get(main, (0,))[0] == 200)
    h1 = [k for k in a if k.startswith("hide1_") and a[k][0] == 200]
    h1_lists = [k for k in lists if k.startswith("hide1_")]
    for lang in ("bg", "en"):
        has = [k for k in h1_lists if f"hide1_{lang}_" in k and NEW_BOX[lang] in a[k][1]]
        tot = [k for k in h1_lists if f"hide1_{lang}_" in k and 'class="howto"' in a[k][1]]
        check(f"PUBLIC_HIDE=1, {lang}: новата кутия „{'Добре е да знаеш' if lang == 'bg' else 'Good to know'}“ на всяка страница с „Как да чета“",
              tot and len(has) == len(tot), f"{len(has)} от {len(tot)}")
    for w in OLD_WORDS:
        hit = [k for k in h1 if w in a[k][1]]
        check(f"PUBLIC_HIDE=1: никъде „{w}“ (списък и мачове, bg и en)", not hit, ", ".join(hit[:5]))
    warn = [k for k in h1 if 'class="box warn"' in a[k][1] or "⚠️" in re.sub(r"<style.*?</style>", "", a[k][1], flags=re.S)]
    check("PUBLIC_HIDE=1: без ⚠️ и без жълтата кутия (box warn)", not warn, ", ".join(warn[:5]))
    age = [k for k in h1_lists if 'class="howto"' in a[k][1] and
           (a[k][1].count('<div class="box age">') != 1 or a[k][1].count('class="foot-note"') != 1)]
    check("PUBLIC_HIDE=1: „🔞 Отговорна игра“ и долният ред за 18+ - на място", not age, ", ".join(age[:5]))
    agesame = [k for k in h1_lists if re.search(r'<div class="box age">.*?</div>', a[k][1], re.S).group(0)
               != re.search(r'<div class="box age">.*?</div>', b[k][1], re.S).group(0)] if h1_lists else ["няма"]
    check("PUBLIC_HIDE=1: „Отговорна игра“ - байт по байт както преди", not agesame, ", ".join(agesame[:5]))
    cyr = [k for k in a if "_en_" in k and a[k][0] == 200 and CYR.search(a[k][1])]
    check("en: нула кирилица (всички настройки)", not cyr, ", ".join(cyr[:5]))
    h0 = [k for k in a if k.startswith("hide0")]
    check("PUBLIC_HIDE=0 (и с SHOW_ALL=1): байт по байт както преди", not [k for k in h0 if a[k] != b[k]], f"{len(h0)} отговора")
    had = sum(1 for k in h0 if a[k][0] == 200 and ("печелившо" in a[k][1] or "profitable" in a[k][1]))
    check("(за сведение) при PUBLIC_HIDE=0 старата кутия си стои", had > 0, f"{had} страници")
    other = [k for k in a if k.startswith("hide1_") and expect(k, b[k][1]) != a[k][1]]
    check("PUBLIC_HIDE=1: старият HTML със сменена само кутията = новият, байт по байт", not other, ", ".join(other[:5]))
    ok = sum(r.startswith("OK") for r in res)
    with open(OUT_TXT, "w", encoding="utf-8") as fh:
        fh.write(f"ZADACHA_CHESTNO тест на копие ({len(res)} проверки, {ok} OK)\n\n" + "\n".join(res) + "\n")
    print("\n".join(res))
    print(f"{ok}/{len(res)} OK")
    return ok == len(res)


def main():
    stage, work = sys.argv[1], sys.argv[2]
    os.makedirs(work, exist_ok=True)
    snap(work, stage)
    if stage == "after":
        sys.exit(0 if compare(work) else 1)


if __name__ == "__main__":
    main()
