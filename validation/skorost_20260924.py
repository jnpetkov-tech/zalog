"""ZADACHA_GOLQMA.md, Етап 1 (24.09.2026): скоростта на /prognozi.

Тестова среда по образец на archive/prazno_harness_20260924.py: регистрира
САМО web/prognozi.py (подаден като път) върху базата (подадена като път) и
реалните шаблони, БЕЗ да импортира match_predictor_app (импортът пише в
model_cache). system_tracker също се подава като път - така "стар" и "нов"
код се мерят върху една и съща база в един и същи процес.

Употреба:
  python validation/skorost_20260924.py measure <prognozi.py> <system_tracker.py> <db> <етикет> [csv]
  python validation/skorost_20260924.py compare <prognozi_a> <st_a> <prognozi_b> <st_b> <db>
  python validation/skorost_20260924.py profile <prognozi.py> <system_tracker.py> <db> <url>
"""
import ast
import csv
import cProfile
import importlib.util
import io
import os
import pstats
import sqlite3
import statistics
import sys
import time

REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, REPO)
os.chdir(REPO)

from flask import Flask  # noqa: E402

N_RUNS = 7


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _league_registry():
    src = open(f"{REPO}/match_predictor_app.py", encoding="utf-8").read()
    ns = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) in ("ALL_LEAGUES", "LEAGUE_FLAGS"):
            exec(compile(ast.Module([node], []), "x", "exec"), ns)
    return ns["ALL_LEAGUES"], ns["LEAGUE_FLAGS"]


ROW_COUNTS = {}


def _count_rows(st):
    """Обвива всяка публична функция на system_tracker, която връща
    списък/речник - брои колко реда е върнала (приблизително "колко реда
    чете страницата")."""
    for name in dir(st):
        fn = getattr(st, name)
        if name.startswith("_") or not callable(fn) or getattr(fn, "__module__", None) != st.__name__:
            continue

        def wrap(fn=fn, name=name):
            def inner(*a, **k):
                res = fn(*a, **k)
                if isinstance(res, (list, dict)):
                    ROW_COUNTS[name] = ROW_COUNTS.get(name, 0) + len(res)
                return res
            return inner
        setattr(st, name, wrap())


def make_app(prognozi_path, st_path, db_path, tag):
    import system_tracker as st_live  # prediction_policy го ползва лениво за trust_derived
    import prediction_policy as policy
    import pick_selection as ps
    import evaluation
    from bg_names import to_cyrillic
    st = _load(st_path, f"st_{tag}")
    st.DB_PATH = db_path
    st_live.DB_PATH = db_path
    _count_rows(st)
    m = _load(prognozi_path, f"prognozi_{tag}")
    all_leagues, flags = _league_registry()
    app = Flask(f"t_{tag}", template_folder=f"{REPO}/templates", static_folder=f"{REPO}/static")
    m.register_prognozi_routes(app, {"ALL_LEAGUES": all_leagues, "LEAGUE_FLAGS": flags,
                                     "st": st, "evaluation": evaluation, "ps": ps, "policy": policy,
                                     "to_cyrillic": to_cyrillic, "_market_info_for_pick": None,
                                     "MARKET_COPY_CODES": None, "MARKET_COPY_NOTE": None})
    return app


def urls_for(db_path):
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    snap = [r[0] for r in c.execute(
        "SELECT DISTINCT fixture_id FROM predictions_snapshot ORDER BY match_date, fixture_id LIMIT 3")]
    fin = [r[0] for r in c.execute(
        "SELECT fixture_id FROM predictions_log WHERE status IN ('won','lost') "
        "GROUP BY fixture_id ORDER BY MAX(match_date) DESC LIMIT 2")]
    leagues = [r[0] for r in c.execute(
        "SELECT league FROM predictions_log WHERE status IN ('won','lost') GROUP BY league ORDER BY COUNT(*) DESC LIMIT 1")]
    snap_league = [r[0] for r in c.execute("SELECT league FROM predictions_snapshot LIMIT 1")]
    c.close()
    urls = [
        ("/prognozi", "по подразбиране (днес празно -> първия ден с мачове)"),
        ("/prognozi?day=0", "празен ден (днес)"),
        ("/prognozi?day=3", "ден с мачове"),
        ("/prognozi?day=2", "ден с мачове 2"),
        ("/prognozi?status=finished", "таб Приключили"),
        ("/prognozi?status=finished&limit=100", "таб Приключили, 100 реда"),
    ]
    if leagues:
        urls.append((f"/prognozi?status=finished&league={leagues[0]}", "Приключили, филтър лига"))
    if snap_league:
        urls.append((f"/prognozi?day=3&league={snap_league[0]}", "ден с мачове, филтър лига"))
    for f in snap:
        urls.append((f"/prognozi/match/{f}", "мач от снимката"))
    for f in fin:
        urls.append((f"/prognozi/match/{f}", "приключил мач (от дневника)"))
    urls.append(("/prognozi/match/1", "несъществуващ мач"))
    return urls


def measure(prognozi_path, st_path, db_path, label, csv_path=None):
    app = make_app(prognozi_path, st_path, db_path, "m")
    client = app.test_client()
    out = []
    for url, what in urls_for(db_path):
        client.get(url)  # загрявка (шаблони, trust_derived кеш)
        times = []
        for _ in range(N_RUNS):
            ROW_COUNTS.clear()
            t0 = time.perf_counter()
            resp = client.get(url)
            times.append((time.perf_counter() - t0) * 1000)
        rows = sum(ROW_COUNTS.values())
        detail = ";".join(f"{k}={v}" for k, v in sorted(ROW_COUNTS.items()))
        rec = {"label": label, "url": url, "what": what, "status": resp.status_code,
               "median_ms": round(statistics.median(times), 1), "min_ms": round(min(times), 1),
               "max_ms": round(max(times), 1), "rows_read": rows, "rows_detail": detail}
        out.append(rec)
        print(f"{rec['median_ms']:8.1f} ms  {rows:7d} реда  {resp.status_code}  {url}  ({what})  {detail}")
    if csv_path:
        new = not os.path.exists(csv_path)
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
            if new:
                w.writeheader()
            w.writerows(out)
    return out


def compare(pa, sa, pb, sb, db_path):
    """Еднакви ли са HTML отговорите на стария и новия код върху една база."""
    a = make_app(pa, sa, db_path, "a").test_client()
    b = make_app(pb, sb, db_path, "b").test_client()
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    leagues = [r[0] for r in c.execute("SELECT DISTINCT league FROM predictions_log")]
    snap_ids = [r[0] for r in c.execute("SELECT DISTINCT fixture_id FROM predictions_snapshot ORDER BY fixture_id LIMIT 3")]
    fin_ids = [r[0] for r in c.execute(
        "SELECT fixture_id FROM predictions_log GROUP BY fixture_id ORDER BY fixture_id LIMIT 2")]
    fin_ids += [r[0] for r in c.execute(
        "SELECT fixture_id FROM predictions_log WHERE status='won' GROUP BY fixture_id ORDER BY MAX(match_date) DESC LIMIT 2")]
    c.close()
    urls = []
    for day in ["", "day=0", "day=1", "day=2", "day=3", "day=4", "day=6"]:
        for league in ["", "league=all", "league=bulgaria2", "league=spain2", "league=england"]:
            q = "&".join(x for x in [day, league] if x)
            urls.append("/prognozi" + (f"?{q}" if q else ""))
    for league in ["all"] + sorted(leagues):
        for lim in ["", "&limit=50", "&limit=2000"]:
            urls.append(f"/prognozi?status=finished&league={league}{lim}")
    urls += ["/prognozi?status=skipped", "/prognozi?day=abc", "/prognozi?limit=abc&status=finished"]
    urls += [f"/prognozi/match/{f}" for f in snap_ids + fin_ids + [1]]
    n_same, diffs = 0, []
    for u in urls:
        ra, rb = a.get(u), b.get(u)
        if ra.status_code == rb.status_code and ra.data == rb.data:
            n_same += 1
        else:
            diffs.append(u)
    print(f"еднакви: {n_same}/{len(urls)}")
    for u in diffs:
        print("  РАЗЛИКА:", u)
    return n_same, len(urls), diffs, urls


def profile(prognozi_path, st_path, db_path, url):
    app = make_app(prognozi_path, st_path, db_path, "p")
    client = app.test_client()
    client.get(url)
    pr = cProfile.Profile()
    pr.enable()
    client.get(url)
    pr.disable()
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(30)
    print(s.getvalue())


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "measure":
        measure(*sys.argv[2:6], csv_path=sys.argv[6] if len(sys.argv) > 6 else None)
    elif cmd == "compare":
        compare(*sys.argv[2:7])
    elif cmd == "profile":
        profile(*sys.argv[2:6])
