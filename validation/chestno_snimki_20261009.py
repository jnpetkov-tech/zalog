"""validation/chestno_snimki_20261009.py - ZADACHA_CHESTNO: снимки на разгънатото „Как да чета тези числа“ на /prognozi,
БГ и EN, компютър (1280 px) и телефон (375 px).

Тестово приложение (web/prognozi.py, копие на базата, LANG_SWITCH=1, PUBLIC_HIDE=1 - както на живо) на 127.0.0.1:8098;
снима Playwright (отделна среда - не е в живата venv). Отваря /prognozi?lang=..#howto (котвата разгъва блока) и снима самия блок.
Изход: validation/chestno_20261009/<tag>_howto_<език>_<ширина>.png
Употреба: venv/bin/python3 validation/chestno_snimki_20261009.py <tag> <папка с test.db> <python с playwright> [база на сайта]
          (с база, напр. http://127.0.0.1:8001 - снима живия сайт, без тестово приложение)
"""
import os
import subprocess
import sys
import threading
import time

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, os.path.join(REPO, "validation"))
OUT = os.path.join(REPO, "validation", "chestno_20261009")

CLIENT = r'''
import sys
from playwright.sync_api import sync_playwright
base, out, tag = sys.argv[1], sys.argv[2], sys.argv[3]
with sync_playwright() as p:
    b = p.chromium.launch()
    for w, mob in ((1280, False), (375, True)):
        for lang in ("bg", "en"):
            ctx = b.new_context(viewport={"width": w, "height": 900}, is_mobile=mob, device_scale_factor=2 if mob else 1)
            pg = ctx.new_page()
            pg.goto(f"{base}/prognozi?lang={lang}#howto", wait_until="networkidle")
            el = pg.locator("details.howto")
            print(tag, lang, w, "разгънато" if el.get_attribute("open") is not None else "СГЪНАТО",
                  "ширина", pg.evaluate("document.documentElement.scrollWidth"))
            el.scroll_into_view_if_needed()
            el.screenshot(path=f"{out}/{tag}_howto_{lang}_{w}.png")
            ctx.close()
    b.close()
'''


def main():
    tag, work, pw_python = sys.argv[1], sys.argv[2], sys.argv[3]
    base = sys.argv[4] if len(sys.argv) > 4 else None
    if not base:
        import ezik_test_20261008 as et
        import config
        config.SHOW_ALL = False
        app = et.app_for(os.path.join(REPO, "web", "prognozi.py"), os.path.join(work, "test.db"), f"shot_{tag}", True, lang_switch=True)
        threading.Thread(target=lambda: app.run(host="127.0.0.1", port=8098, threaded=True, use_reloader=False), daemon=True).start()
        time.sleep(2)
        base = "http://127.0.0.1:8098"
    os.makedirs(OUT, exist_ok=True)
    cl = os.path.join(work, "pw_client.py")
    open(cl, "w").write(CLIENT)
    r = subprocess.run([pw_python, cl, base, OUT, tag], check=True, capture_output=True, text=True)
    print(r.stdout)
    with open(os.path.join(OUT, f"{tag}_snimki.txt"), "w", encoding="utf-8") as fh:
        fh.write(r.stdout)


if __name__ == "__main__":
    main()
