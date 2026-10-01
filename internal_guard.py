"""internal_guard.py - вътрешен предпазител при избора на публикувана прогноза, БЕЗ пазарен коефициент (ZADACHA_TABLICA ст.5а, 01.10.2026).

Заменя MAX_TRUSTWORTHY_EV в pick_selection.rank_logged_rows(): преди изборът изключваше кандидат с implied EV > 40% (т.е. ползваше пазарния
коефициент). Пазарът е само мерило - изборът да не зависи от него. Основание: validation/pazar_vun_osnovanie_20261001.md (уверените прогнози
при малко история са преувеличени: обещано 0.744, реално 0.723 при К<10) и validation/pazar_vun_20261001.md (симулация).

Правило: кандидат с pick_pct >= HI_PCT на мач, в който най-малкият брой изиграни мачове на двата отбора в последните 365 дни (всички 17 лиги,
{лига}_fixtures.csv от fetch_api_sets.py) е под K_MIN, се изключва от избора (мачът запазва по-предпазлива прогноза, ако има такава).
Чисто четене на CSV; кеш в паметта (презарежда се на 15 мин). Липсващи данни -> не флагва (предпазителят никога не спъва избор, който не може да прецени).
Незадължително (X): ако редът носи lam и mu (не са в predictions_log днес), екстремно ядро (извън [0.35; 3.2]) също флагва.
"""
import bisect
import csv
import os
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal", "champions_league", "europa_league",
           "conference_league", "france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
K_MIN = 10
HI_PCT = 65.0
LAM_RANGE = (0.35, 3.2)
RELOAD_SECONDS = 900
FINISHED = {"FT", "AET", "PEN"}
_cache = {"at": 0.0, "min_prior": {}}


def _load():
    latest = {}
    for lg in LEAGUES:
        path = os.path.join(ROOT, f"{lg}_fixtures.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not r.get("timestamp"):
                    continue
                prev = latest.get(r["fixture_id"])
                if prev is None or r.get("fetched_at", "") >= prev.get("fetched_at", ""):
                    latest[r["fixture_id"]] = r
    by_team = {}
    for r in latest.values():
        if r["status"] in FINISHED:
            for t in (r["home_id"], r["away_id"]):
                by_team.setdefault(t, []).append(int(float(r["timestamp"])))
    for t in by_team:
        by_team[t].sort()
    out = {}
    for fid, r in latest.items():
        ts = int(float(r["timestamp"]))

        def n_prior(team):
            lst = by_team.get(team, [])
            return bisect.bisect_left(lst, ts) - bisect.bisect_left(lst, ts - 365 * 86400)
        out[int(float(fid))] = min(n_prior(r["home_id"]), n_prior(r["away_id"]))
    _cache.update(at=time.time(), min_prior=out)


def min_prior(fixture_id):
    if time.time() - _cache["at"] > RELOAD_SECONDS:
        try:
            _load()
        except Exception:
            _cache["at"] = time.time()
    return _cache["min_prior"].get(int(fixture_id))


def flagged(row):
    """True -> кандидатът се изключва от избора на публикувана прогноза."""
    if (row.get("pick_pct") or 0) < HI_PCT:
        return False
    lam, mu = row.get("lam"), row.get("mu")
    if lam is not None and mu is not None and not (LAM_RANGE[0] <= lam <= LAM_RANGE[1] and LAM_RANGE[0] <= mu <= LAM_RANGE[1]):
        return True
    n = min_prior(row["fixture_id"])
    return n is not None and n < K_MIN
