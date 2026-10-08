"""validation/ezik_snimki_20261008.py - ZADACHA_EZIK: снимки на екрана (Playwright) на списъка и на мач, БГ и EN, компютър и телефон.

Тестово приложение (само web/prognozi.py, копие на базата, LANG_SWITCH=1, PUBLIC_HIDE=1 - както ще е на живо) на 127.0.0.1:8099;
снима Playwright (отделна среда - не е в живата venv). Изход: validation/ezik_20261008/*.png
Употреба: venv/bin/python3 validation/ezik_snimki_20261008.py <папка с test.db от ezik_test_20261008.py> <python с playwright>
"""
import os
import subprocess
import sys
import threading
import time

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, os.path.join(REPO, "validation"))
OUT = os.path.join(REPO, "validation", "ezik_20261008")

CLIENT = r'''
import sys
from playwright.sync_api import sync_playwright
base, out, pages = sys.argv[1], sys.argv[2], sys.argv[3:]
with sync_playwright() as p:
    b = p.chromium.launch()
    for dev, vp, mobile in (("desktop", {"width": 1280, "height": 900}, False), ("phone", {"width": 375, "height": 812}, True)):
        for spec in pages:
            name, url = spec.split("=", 1)
            for lang in ("bg", "en"):
                ctx = b.new_context(viewport=vp, is_mobile=mobile, device_scale_factor=2 if mobile else 1)
                pg = ctx.new_page()
                pg.goto(base + url + ("&" if "?" in url else "?") + "lang=" + lang, wait_until="networkidle")
                pg.screenshot(path=f"{out}/{name}_{lang}_{dev}.png", full_page=not name.startswith("spisak"))
                if name.startswith("spisak"):
                    pg.screenshot(path=f"{out}/{name}_{lang}_{dev}.png", full_page=False)
                ctx.close()
    b.close()
'''


def main():
    work, pw_python = sys.argv[1], sys.argv[2]
    import ezik_test_20261008 as et
    import sqlite3
    db = os.path.join(work, "test.db")
    app = et.app_for(os.path.join(REPO, "web", "prognozi.py"), db, "shot", True, lang_switch=True)
    con = sqlite3.connect(db)
    lu = con.execute("SELECT fixture_id FROM match_text WHERE has_lineups = 1 LIMIT 1").fetchone()
    day = con.execute("SELECT MIN(substr(match_date, 1, 10)) FROM predictions_snapshot WHERE match_date >= date('now')").fetchone()[0]
    con.close()
    from datetime import date
    off = (date.fromisoformat(day) - date.today()).days
    import layer_live
    from datetime import datetime
    layer_live.final_time = lambda f: datetime(2020, 1, 1, 12, 5) if lu and int(f) == lu[0] else None
    th = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=8099, threaded=True, use_reloader=False), daemon=True)
    th.start()
    time.sleep(2)
    os.makedirs(OUT, exist_ok=True)
    cl = os.path.join(work, "pw_client.py")
    open(cl, "w").write(CLIENT)
    pages = [f"spisak=/prognozi?day={off}", f"mach=/prognozi/match/{lu[0]}"]
    subprocess.run([pw_python, cl, "http://127.0.0.1:8099", OUT] + pages, check=True)
    print(sorted(os.listdir(OUT)))


if __name__ == "__main__":
    main()
