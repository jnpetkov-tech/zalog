"""Трие ТОЧНИТЕ повторени редове в *_player_stats.csv и *_player_stats_extra.csv (01.10.2026).
Пази първото срещане, редът и форматът на останалите редове се запазват байт по байт (чете се суров CSV, не през pandas).
Безопасност: същия flock като crontab на fetch_player_stats.py; бекъп с дата; временен файл; проверка; os.replace.
Употреба: venv/bin/python3 archive/dubliakti_20261001/chisti.py [--dry-run]
Пише validation/dubliakti_20261001.csv."""
import csv, fcntl, glob, hashlib, os, shutil, sys, time
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(REPO)
dry = "--dry-run" in sys.argv
BACKUP = os.path.join(REPO, "data_backups", "20261001_dubliakti")

lock = open("/tmp/fetch_player_stats.lock", "w")
t0 = time.time()
while True:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); break
    except BlockingIOError:
        if time.time() - t0 > 600: sys.exit("не взех лока за 10 мин")
        time.sleep(2)

files = sorted(glob.glob("*_player_stats.csv") + glob.glob("*_player_stats_extra.csv"))
report = []
for f in files:
    with open(f, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    if not rows: continue
    header, body = rows[0], rows[1:]
    import io
    buf = io.StringIO(newline=""); csv.writer(buf).writerows(rows)
    with open(f, newline="", encoding="utf-8") as fh:
        assert fh.read() == buf.getvalue(), f"кръговият тест не мина за {f} - форматът не се възпроизвежда"
    seen, kept = set(), []
    for r in body:
        t = tuple(r)
        if t in seen: continue
        seen.add(t); kept.append(r)
    removed = len(body) - len(kept)
    report.append((f, len(body), len(kept), removed))
    if removed == 0 or dry: continue
    os.makedirs(BACKUP, exist_ok=True)
    shutil.copy2(f, os.path.join(BACKUP, f))
    tmp = f + ".tmp_dedup"
    with open(tmp, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out); w.writerow(header); w.writerows(kept)
    # проверка: нов файл = същите уникални редове, без нито една точна повторка, същата заглавка
    with open(tmp, newline="", encoding="utf-8") as fh:
        chk = list(csv.reader(fh))
    assert chk[0] == header and len(chk) - 1 == len(kept) == len(set(map(tuple, body))), f
    assert len(set(map(tuple, chk[1:]))) == len(chk) - 1, f
    assert set(map(tuple, chk[1:])) == set(map(tuple, body)), f
    os.replace(tmp, f)
    print("изчистен", f, removed)
out = os.path.join(REPO, "validation", "dubliakti_20261001.csv")
if not dry:
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["file", "rows_before", "rows_after", "removed"]); w.writerows(report)
for r in report:
    if r[3]: print(r)
print("общо изтрити:", sum(r[3] for r in report), "(dry-run)" if dry else "")
