#!/usr/bin/env python3
import sqlite3
import os
import glob
import time

SRC_DIR = "/home/inkas/sportbg-predictor"
BACKUP_DIR = os.path.join(SRC_DIR, "db_backups")
os.makedirs(BACKUP_DIR, exist_ok=True)
stamp = time.strftime("%Y-%m-%d_%H%M")

for name in ("predictions", "bets"):
    src_path = os.path.join(SRC_DIR, f"{name}.db")
    dst_path = os.path.join(BACKUP_DIR, f"{name}_{stamp}.db")
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    print(f"Backed up {name}.db -> {dst_path}")

cutoff = time.time() - 14 * 86400
for pattern in ("predictions_*.db", "bets_*.db"):
    for f in glob.glob(os.path.join(BACKUP_DIR, pattern)):
        if os.path.getmtime(f) < cutoff:
            os.remove(f)
            print(f"Removed old backup: {f}")

print(f"Backup done: {stamp}")
