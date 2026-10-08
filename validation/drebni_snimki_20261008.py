"""validation/drebni_snimki_20261008.py - ZADACHA_DREBNI: снимки на телефон (375 и 320 px), БГ и EN, преди/след.

Тестово приложение (web/prognozi.py, копие на базата, LANG_SWITCH=1, PUBLIC_HIDE=1 - както на живо) на 127.0.0.1:8098;
снима Playwright (отделна среда - не е в живата venv). За всеки случай две снимки: горната част на екрана (заглавката с датата и
текста на мача) и секцията „Точен резултат“. Изход: validation/drebni_20261008/<before|after>_<мач>_<език>_<ширина>_<top|cs>.png
Употреба: venv/bin/python3 validation/drebni_snimki_20261008.py <before|after> <папка с test.db> <python с playwright> <мач>...
"""
import os
import subprocess
import sys
import threading
import time

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, os.path.join(REPO, "validation"))
OUT = os.path.join(REPO, "validation", "drebni_20261008")

CLIENT = r'''
import sys
from playwright.sync_api import sync_playwright
base, out, tag, fixtures = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
with sync_playwright() as p:
    b = p.chromium.launch()
    for w in (375, 320):
        for fx in fixtures:
            for lang in ("bg", "en"):
                ctx = b.new_context(viewport={"width": w, "height": 740}, is_mobile=True, device_scale_factor=2)
                pg = ctx.new_page()
                pg.goto(f"{base}/prognozi/match/{fx}?lang={lang}", wait_until="networkidle")
                pre = f"{out}/{tag}_{fx}_{lang}_{w}"
                pg.screenshot(path=f"{pre}_top.png")
                sec = pg.locator(".msection", has_text="Точен резултат" if lang == "bg" else "Correct score").first
                if sec.count():
                    sec.scroll_into_view_if_needed()
                    pg.screenshot(path=f"{pre}_cs.png")
                sw = pg.evaluate("document.documentElement.scrollWidth")
                print(f"{tag} {fx} {lang} {w}px: ширина на страницата {sw}px", "ИЗЛИЗА ВДЯСНО" if sw > w else "събира се")
                ctx.close()
    b.close()
'''


def main():
    tag, work, pw_python, fixtures = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    import ezik_test_20261008 as et
    import config
    config.SHOW_ALL = False
    app = et.app_for(os.path.join(REPO, "web", "prognozi.py"), os.path.join(work, "test.db"), f"shot_{tag}", True, lang_switch=True)
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=8098, threaded=True, use_reloader=False), daemon=True).start()
    time.sleep(2)
    os.makedirs(OUT, exist_ok=True)
    cl = os.path.join(work, "pw_client.py")
    open(cl, "w").write(CLIENT)
    r = subprocess.run([pw_python, cl, "http://127.0.0.1:8098", OUT, tag] + fixtures, check=True, capture_output=True, text=True)
    print(r.stdout)
    with open(os.path.join(OUT, f"{tag}_shirina.txt"), "w", encoding="utf-8") as fh:
        fh.write(r.stdout)


if __name__ == "__main__":
    main()
