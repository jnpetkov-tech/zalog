"""validation/sastavi_budzhet_20261002.py - ZADACHA_SASTAVI_BARZO т.3 (02.10.2026): заявки на ден за търсенето на съставите.

Симулация върху ИСТИНСКИЯ график (началата на изиграните мачове от {лига}_fixtures.csv, 17-те лиги, 01.08.2025-31.05.2026):
- СТАРО (layer_shadow.py без флаг, cron :04/:19/:34/:49): за мач в прозореца 15..100 мин преди началото, без състави -> 1 заявка
  /fixtures/lineups на пуск; при намерени - + 1 /injuries.
- НОВО (layer_shadow.py --final-only, cron на 5 мин): мачовете в прозореца 1..75 мин без състави -> ceil(n/20) заявки /fixtures?ids= на
  пуск; при намерени - + 1 /injuries на мач. /status не се брои в квотата (API-Football).
Съставите излизат L минути преди началото: L = 60 (обичайното) и L = 20 (късно, като Eldense-Oviedo 02.10 - 26 мин).
Изход: validation/sastavi_budzhet_20261002.md
"""
import math
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from layer_shadow import LEAGUE_IDS  # noqa: E402

FROM, TO = "2025-08-01", "2026-06-01"


def kickoffs():
    parts = []
    for lg in LEAGUE_IDS:
        p = f"{lg}_fixtures.csv"
        if os.path.exists(p):
            d = pd.read_csv(p, low_memory=False)
            parts.append(d[["fixture_id", "timestamp", "status", "date_utc"]])
    fx = pd.concat(parts).drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["status"].isin(["FT", "AET", "PEN"]) & (fx["date_utc"] >= FROM) & (fx["date_utc"] < TO)]
    return np.sort(fx["timestamp"].astype("int64").to_numpy())


def simulate(ko, L, mode):
    """-> pd.Series заявки по ден (UTC). ko - секунди."""
    day = lambda t: pd.Timestamp(t, unit="s").strftime("%Y-%m-%d")  # noqa: E731
    out = {}
    lineup_at = ko - L * 60
    if mode == "old":
        t0 = (ko.min() // 900) * 900 - 6000
        ticks = np.arange(t0 + 240, ko.max() + 900, 900)            # :04/:19/:34/:49
        lo, hi = 15 * 60, 100 * 60
    else:
        t0 = (ko.min() // 300) * 300 - 6000
        ticks = np.arange(t0, ko.max() + 300, 300)
        lo, hi = 1 * 60, 75 * 60
    found = np.zeros(len(ko), bool)
    i0 = 0
    for t in ticks:
        while i0 < len(ko) and ko[i0] < t + lo:
            i0 += 1
        i1 = np.searchsorted(ko, t + hi, side="right")
        if i1 <= i0:
            continue
        idx = np.arange(i0, i1)
        idx = idx[~found[idx]]
        if not len(idx):
            continue
        n_req = len(idx) if mode == "old" else math.ceil(len(idx) / 20)
        new = idx[lineup_at[idx] <= t]
        found[new] = True
        out[day(t)] = out.get(day(t), 0) + n_req + len(new)     # + /injuries за всеки нов
    return pd.Series(out)


def main():
    ko = kickoffs()
    per_day = pd.Series(ko).map(lambda t: pd.Timestamp(t, unit="s").strftime("%Y-%m-%d")).value_counts()
    res = {}
    for L in (60, 20):
        for mode in ("old", "new"):
            res[(mode, L)] = simulate(ko, L, mode)
    L_ = ["# Търсене на съставите — заявки на ден (ZADACHA_SASTAVI_BARZO т.3, 02.10.2026)", "",
          f"Скрипт: `validation/sastavi_budzhet_20261002.py`. График: {len(ko)} изиграни мача от 17-те лиги, {FROM} – {TO} "
          f"({per_day.size} дни с мачове; на ден средно {per_day.mean():.1f}, най-много {per_day.max()} — {per_day.idxmax()}).",
          "Старо: `/fixtures/lineups` по мач на 15 мин (15–100 мин преди началото); ново: `/fixtures?ids=` до 20 мача на 5 мин (1–75 мин).",
          "И в двата: + 1 `/injuries` на мач при намерени състави. `/status` не се брои в квотата.", "",
          "| съставите излизат | начин | средно на ден с мачове | пиков ден | общо за сезона |", "|---|---|---|---|---|"]
    for L in (60, 20):
        for mode in ("old", "new"):
            s = res[(mode, L)]
            L_.append(f"| {L} мин преди | {'старо' if mode == 'old' else 'ново'} | {s.mean():.0f} | {s.max()} ({s.idxmax()}) | {s.sum()} |")
    L_.append("")
    open("validation/sastavi_budzhet_20261002.md", "w", encoding="utf-8").write("\n".join(L_) + "\n")
    print("\n".join(L_))


if __name__ == "__main__":
    main()
