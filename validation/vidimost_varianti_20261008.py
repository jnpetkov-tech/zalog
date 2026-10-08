"""validation/vidimost_varianti_20261008.py - защо днешната таблица на видимостта се различава от очакваното (мереното в claude.ai):
същият market_visibility.compute() при два периода (последните 12 месеца от днес / цялата късна половина 23.09.2025-22.09.2026) и с
калибрация (както сайтът показва) / без. Само на копие на базата. Изход: validation/vidimost_varianti_20261008.txt
Употреба: venv/bin/python3 validation/vidimost_varianti_20261008.py <копие на predictions.db>"""
import sys
import warnings
from datetime import date

warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/inkas/sportbg-predictor")
import market_visibility as mv  # noqa: E402

db = sys.argv[1]
out = ["Варианти на таблицата на видимостта (скрити по правило б; всички лиги заедно - скрити по а; z на „двата вкарват“)", ""]
orig = mv._calibrate
for cal in (True, False):
    mv._calibrate = orig if cal else (lambda np, p, code: p)
    for td, lab in ((date(2026, 10, 8), "последните 12 месеца: 2025-10-08..2026-10-07"), (date(2026, 9, 23), "късната половина: 2025-09-23..2026-09-22")):
        rows, info = mv.compute(td, prev={}, db_path=db)
        hid = [f"{r['league']}/{r['market']} (z {r['z']:.2f})" for r in rows if r["league"] != mv.ALL and not r["visible"] and r["rule"] == "б"]
        pool = [r["market"] for r in rows if r["league"] == mv.ALL and not r["visible"] and r["rule"] == "а"]
        bt = {r["league"]: round(r["z"], 2) for r in rows if r["market"] == "btts" and r["league"] in ("bulgaria", "germany2")}
        out.append(f"{'калибрирано (показаното)' if cal else 'сурово'}, {lab}, мачове от проверката назад {info['n_wf']}: "
                   f"скрити по лиги: {', '.join(hid) or 'няма'}; всички лиги: {', '.join(pool) or 'няма'}; z двата вкарват: {bt}")
open("/home/inkas/sportbg-predictor/validation/vidimost_varianti_20261008.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("\n".join(out))
