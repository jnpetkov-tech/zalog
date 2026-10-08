"""ZADACHA_EZIK - проверка на живия сайт след рестарта (08.10.2026, 14:00 UTC, LANG_SWITCH=1).

Само чете: HTTP заявки към живия match-predictor-app (127.0.0.1:8001).
Проверява: трите публични страници 200 на bg и en; бутонът БГ|EN; <html lang>; Vary: Cookie; en без кирилица;
?lang=en пише бисквитка и следващата заявка без параметър е en; ?lang=bg връща обратно; /admin и /login не реагират на lang.
Изход: validation/ezik_zhivo_20261008.txt
"""
import os
import re
import http.cookiejar
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:8001"
OUT = os.path.join(REPO, "validation", "ezik_zhivo_20261008.txt")
CYR = re.compile(r"[А-Яа-яЁёЪъ]")
results = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def check(name, ok, detail=""):
    results.append(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


def opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect), jar


def get(op, url):
    try:
        r = op.open(BASE + url, timeout=60)
        return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, ""


op, _ = opener()
st, h, body = get(op, "/prognozi")
mids = list(dict.fromkeys(re.findall(r'href="/prognozi/match/(\d+)', body)))[:5]
pages = ["/", "/prognozi"] + [f"/prognozi/match/{m}" for m in mids]
check("има мачове в списъка", len(mids) > 0, f"{len(mids)} взети")

for lang in ("bg", "en"):
    for p in pages:
        o, _ = opener()
        sep = "&" if "?" in p else "?"
        st, h, body = get(o, f"{p}{sep}lang={lang}")
        check(f"{lang} {p} 200", st == 200, str(st))
        if st != 200:
            continue
        check(f"{lang} {p} <html lang={lang}>", f'<html lang="{lang}"' in body)
        check(f"{lang} {p} бутон БГ|EN", 'hreflang="en"' in body and 'hreflang="bg"' in body)
        check(f"{lang} {p} Vary: Cookie", "Cookie" in (h.get("Vary") or ""))
        if lang == "en":
            cyr = CYR.findall(body)
            check(f"en {p} без кирилица", not cyr, f"{len(cyr)} знака" if cyr else "")

o, jar = opener()
get(o, "/prognozi?lang=en")
check("?lang=en пише бисквитка lang=en", any(c.name == "lang" and c.value == "en" for c in jar))
st, h, body = get(o, "/prognozi")
check("след бисквитката /prognozi без параметър е en", '<html lang="en"' in body)
st, h, body = get(o, "/prognozi?lang=bg")
check("?lang=bg връща на bg", '<html lang="bg"' in body)

for p in ("/admin", "/login"):
    o1, _ = opener()
    a = get(o1, p)
    o2, _ = opener()
    b = get(o2, p + "?lang=en")
    check(f"{p} не зависи от lang", a[0] == b[0], f"{a[0]} / {b[0]}")

n_ok = sum(r.startswith("OK") for r in results)
results.append(f"\nОБЩО: {n_ok}/{len(results)} OK")
with open(OUT, "w") as f:
    f.write("\n".join(results) + "\n")
print("\n".join(results))
