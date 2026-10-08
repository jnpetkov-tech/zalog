"""validation/drebni_test_20261008.py - ZADACHA_DREBNI: тест на КОПИЕ на базата, отделно Flask приложение (живото не се пипа).

Етапи:
  before <папка> - пуска СЕГАШНИЯ код (преди промяната) и пази HTML-а в <папка>/before/
  after  <папка> [стъпки] - пуска новия код, пази HTML-а в <папка>/after/ и сравнява с before; стъпки - кои от 1,2,3 са направени
         (по подразбиране 123; при commit след всяка стъпка - 1, 12, 123)
Три настройки: PUBLIC_HIDE=1 (както на живо, _public_sections), PUBLIC_HIDE=0 + SHOW_ALL=1 (_all_sections),
PUBLIC_HIDE=0 + SHOW_ALL=0 (обичайният изглед); всяка на bg и en (LANG_SWITCH=1). Страници: всички мачове от снимката
+ 6 приключили + „/“, „/prognozi“, „/prognozi?day=1..3“.
Разрешени разлики (старият HTML се преобразува по тях и трябва да съвпадне байт по байт с новия):
  1. заглавката на мача: „<ден>, dd.mm ЧЧ:ММ“ -> „<ден> · ЧЧ:ММ“ (ако денят е празен - без промяна)
  2. няма <p class="mtext-note">…</p> и CSS реда .mtext .mtext-note
  3. .mrow: grid-auto-columns minmax(0,1fr); редове с >4 изхода - клас „many“; под 480 px .mrow.many на 3 колони
Изход: validation/drebni_test_20261008.txt
"""
import os
import re
import sys

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, os.path.join(REPO, "validation"))
import ezik_test_20261008 as et  # noqa: E402
import config  # noqa: E402

OUT_TXT = os.path.join(REPO, "validation", "drebni_test_20261008.txt")
CONFIGS = {"hide1": (True, False), "hide0_all": (False, True), "hide0": (False, False)}
CYR = re.compile(r"[А-Яа-яЁёЪъ]")
NOTE_BG = "Текстът е съставен автоматично"
NOTE_EN = "This text is put together automatically"


def snap(work, tag):
    db = os.path.join(work, "test.db")
    if not os.path.exists(db):
        et.copy_db(db)
    lst, matches, _lg = et.urls(db)
    pages = ["/", "/prognozi", "/prognozi?day=1", "/prognozi?day=2", "/prognozi?day=3"] + matches
    out = {}
    for cname, (hide, show_all) in CONFIGS.items():
        config.SHOW_ALL = show_all
        app = et.app_for(os.path.join(REPO, "web", "prognozi.py"), db, f"{tag}_{cname}", hide, lang_switch=True)
        for lang in ("bg", "en"):
            res = et.get_all(app, pages, cookie=lang)
            for u, (code, data, _h) in res.items():
                key = f"{cname}|{lang}|{u}"
                out[key] = (code, data.decode("utf-8", "replace"))
                fn = os.path.join(work, tag, re.sub(r"[^A-Za-z0-9_]+", "_", key) + ".html")
                os.makedirs(os.path.dirname(fn), exist_ok=True)
                open(fn, "w", encoding="utf-8").write(f"{code}\n" + out[key][1])
    return out


def load(work, tag):
    out = {}
    for fn in os.listdir(os.path.join(work, tag)):
        s = open(os.path.join(work, tag, fn), encoding="utf-8").read()
        code, body = s.split("\n", 1)
        out[fn] = (int(code), body)
    return out


def expect(old, steps="123"):
    """старият HTML -> какъвто трябва да е новият (само разрешените разлики на направените стъпки)."""
    h = old
    if "1" in steps:
        h = re.sub(r'(<div class="hero-meta">.*?· )([^<,]+, \d+ [^<,]+), \d\d\.\d\d (\d\d:\d\d)',
               lambda m: f"{m.group(1)}{m.group(2)} · {m.group(3)}", h, count=1, flags=re.S)
    if "3" in steps:
        h = re.sub(r'\n      <p class="mtext-note">.*?</p>', "", h)
        h = h.replace("  .mtext .mtext-note{ font-size:11.5px; color:var(--text-faint); margin:8px 0 0; }\n", "")
    if "2" not in steps:
        return h
    h = h.replace("grid-auto-columns:1fr;", "grid-auto-columns:minmax(0,1fr);")
    h = h.replace("    .mcell .opct{ font-size:16px; }\n  }\n",
                  "    .mcell .opct{ font-size:16px; }\n  }\n"
                  "  @media (max-width: 479px){\n"
                  "    .mrow.many{ grid-auto-flow:row; grid-template-columns:repeat(3, minmax(0,1fr)); }\n  }\n")
    # клас „many“ на редовете с повече от 4 изхода
    def row(m):
        return ('<div class="mrow many">' if m.group(2).count('<div class="mcell">') > 4 else '<div class="mrow">') + m.group(2)
    h = re.sub(r'(<div class="mrow">)(.*?\n      </div>)', row, h, flags=re.S)
    return h


def compare(work, steps="123"):
    res = []
    check = lambda n, ok, d="": res.append(("OK   " if ok else "FAIL ") + n + (f" - {d}" if d else ""))
    b, a = load(work, "before"), load(work, "after")
    check("същите страници преди и след", set(b) == set(a), f"{len(a)} отговора")
    match = [k for k in a if "_prognozi_match_" in k]
    ok200 = [k for k in match if a[k][0] == 200]
    check("страници на мачове 200 (bg и en, трите настройки)", len(ok200) >= 30,
          f"{len(ok200)} от {len(match)} със 200; мачове на en 200: {sum('_en_' in k for k in ok200)}")
    check("кодовете на отговор - както преди", not [k for k in a if a[k][0] != b[k][0]])
    cyr = [k for k in a if "_en_" in k and a[k][0] == 200 and CYR.search(a[k][1])]
    check("en: нула кирилица", not cyr, ", ".join(cyr[:5]))
    dup = []
    for k in ok200:
        m = re.search(r'<div class="hero-meta">(.*?)</div>', a[k][1], re.S)
        meta = m.group(1) if m else ""
        if re.search(r"\b\d\d\.\d\d \d\d:\d\d", meta) and re.search(r"[A-Za-zА-Яа-я]{2}, \d+ ", meta):
            dup.append(k)
    if "1" in steps:
      check("заглавката на мача: датата веднъж (няма „ден, dd.mm“)", not dup, ", ".join(dup[:5]))
      with_day = sum(1 for k in ok200 if re.search(r'<div class="hero-meta">.*?· [A-Za-zА-Яа-я]{2,3}, \d+ \S+ · \d\d:\d\d', a[k][1], re.S))
      check("заглавката: „<ден> · ЧЧ:ММ“", with_day == len([k for k in ok200 if "Мачът не е намерен" not in a[k][1]
                                                          and "Match not found" not in a[k][1]]), f"{with_day} страници")
    if "3" in steps:
      note = [k for k in a if NOTE_BG in a[k][1] or NOTE_EN in a[k][1] or "mtext-note" in a[k][1]]
      check("бележката под текста я няма никъде (и класа mtext-note)", not note, ", ".join(note[:5]))
      had = sum(1 for k in b if NOTE_BG in b[k][1] or NOTE_EN in b[k][1])
      check("(за сведение) преди бележката я имаше", had > 0, f"{had} страници")
    if "2" in steps:
      many = sum(a[k][1].count('class="mrow many"') for k in a)
      check("(за сведение) редове с >4 изхода (клас many)", many > 0, f"{many} реда")
    other = [k for k in a if b[k][0] == 200 and expect(b[k][1], steps) != a[k][1]]
    check(f"нищо друго не е променено: старият HTML + разрешените разлики (стъпки {steps}) = новият, байт по байт", not other, ", ".join(other[:5]))
    lists = [k for k in a if "_prognozi_match_" not in k]
    check("списъкът и началната страница - байт по байт както преди", not [k for k in lists if a[k] != b[k]], f"{len(lists)} страници")
    ok = sum(r.startswith("OK") for r in res)
    with open(OUT_TXT, "w", encoding="utf-8") as fh:
        fh.write(f"ZADACHA_DREBNI тест на копие, стъпки {steps} ({len(res)} проверки, {ok} OK)\n\n" + "\n".join(res) + "\n")
    print("\n".join(res))
    print(f"{ok}/{len(res)} OK")
    return ok == len(res)


def main():
    stage, work = sys.argv[1], sys.argv[2]
    os.makedirs(work, exist_ok=True)
    snap(work, stage)
    if stage == "after":
        sys.exit(0 if compare(work, sys.argv[3] if len(sys.argv) > 3 else "123") else 1)


if __name__ == "__main__":
    main()
