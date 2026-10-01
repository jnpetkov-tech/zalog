"""Б1б: емпирична проба на всеки endpoint на API-Football върху малка извадка (01.10.2026).
Пише validation/api_probe_20261001.csv (по заявка) и validation/api_probe_fields_20261001.json (полетата по endpoint).
Сурови отговори: api_raw/probe/*.json.gz (извън git). Всичките заявки минават през backfill_request (етикет в api_calls.log)."""
import os, sys, json, gzip, csv, time, re
import pandas as pd
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO); os.chdir(REPO)
import backfill_common as bc

SAMPLES = {"england": (39, 2025), "england2": (40, 2025), "bulgaria": (172, 2025), "champions_league": (2, 2025), "bulgaria2": (173, 2025)}
rows, fields, n = [], {}, [0]
calls = [0]

def flat(o, prefix="", depth=0, out=None):
    out = set() if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            flat(v, f"{prefix}.{k}" if prefix else k, depth + 1, out)
    elif isinstance(o, list):
        if o and isinstance(o[0], (dict, list)):
            for it in o[:3]: flat(it, prefix + "[]", depth + 1, out)
        else: out.add(prefix + "[]")
    else:
        out.add(prefix)
    return out

def probe(ep, params, sample, tag=""):
    n[0] += 1; calls[0] += 1
    time.sleep(0.3)
    r = bc.backfill_request(ep, params=params, timeout=30)
    if r.status_code == 429: sys.exit("HTTP 429 - спирам")
    try: d = r.json()
    except ValueError: d = {"errors": f"HTTP {r.status_code} не е JSON", "results": 0, "response": []}
    errs = d.get("errors"); errs = json.dumps(errs, ensure_ascii=False) if errs else ""
    if "rateLimit" in errs: sys.exit("rateLimit - спирам: " + errs)
    resp = d.get("response") or []
    pg = (d.get("paging") or {})
    fn = f"api_raw/probe/{n[0]:03d}_{re.sub('[^a-z0-9]+','_',ep.lower()).strip('_')}_{sample}{tag}.json.gz"
    with gzip.open(fn, "wt", encoding="utf-8") as g: json.dump(d, g, ensure_ascii=False)
    fl = sorted(flat(resp[:3])) if isinstance(resp, list) and resp else (sorted(flat(resp)) if resp else [])
    key = ep
    if fl: fields.setdefault(key, set()).update(fl)
    rows.append({"endpoint": ep, "params": json.dumps(params, sort_keys=True), "sample": sample + tag, "http": r.status_code,
                 "results": d.get("results"), "paging_total": pg.get("total"), "errors": errs[:200], "n_fields": len(fl), "raw": fn})
    return d

def local_fixture(league, season):
    m = pd.read_csv(f"{league}_merged_full.csv", usecols=["fixture_id", "season", "date"])
    m = m[(m.season == season) & (m.date < "2026-05-01")].sort_values("date")
    return int(m.fixture_id.iloc[len(m) // 2]) if len(m) else None

ids = {}
for name, (lid, season) in SAMPLES.items():
    F = local_fixture(name, season)
    fx = probe("/fixtures", {"id": F}, name)["response"][0]
    home, away = fx["teams"]["home"]["id"], fx["teams"]["away"]["id"]
    P = None
    pc = f"{name}_player_stats_extra.csv"
    if os.path.exists(pc) and os.path.getsize(pc):
        e = pd.read_csv(pc, usecols=["fixture_id", "player_id", "minutes"]); e = e[(e.fixture_id == F) & (e.minutes > 60)]
        P = int(e.player_id.iloc[0]) if len(e) else None
    ids[name] = dict(L=lid, S=season, F=F, home=home, away=away, P=P, venue=(fx["fixture"].get("venue") or {}).get("id"))
    print(name, ids[name], flush=True)

for name, i in ids.items():
    L, S, F, T, P = i["L"], i["S"], i["F"], i["home"], i["P"]
    for ep, pr in [("/fixtures/statistics", {"fixture": F}), ("/fixtures/events", {"fixture": F}), ("/fixtures/lineups", {"fixture": F}),
                   ("/fixtures/players", {"fixture": F}), ("/fixtures/headtohead", {"h2h": f"{T}-{i['away']}"}),
                   ("/fixtures/rounds", {"league": L, "season": S}), ("/fixtures", {"league": L, "season": S}),
                   ("/injuries", {"league": L, "season": S}), ("/injuries", {"fixture": F}),
                   ("/predictions", {"fixture": F}), ("/odds", {"fixture": F}), ("/odds", {"league": L, "season": S, "page": 1}),
                   ("/teams", {"league": L, "season": S}), ("/teams/statistics", {"league": L, "season": S, "team": T}),
                   ("/teams/seasons", {"team": T}), ("/standings", {"league": L, "season": S}),
                   ("/players", {"league": L, "season": S, "page": 1}), ("/players/squads", {"team": T}),
                   ("/players/topscorers", {"league": L, "season": S}), ("/players/topassists", {"league": L, "season": S}),
                   ("/players/topyellowcards", {"league": L, "season": S}), ("/players/topredcards", {"league": L, "season": S}),
                   ("/transfers", {"team": T}), ("/coachs", {"team": T})]:
        d = probe(ep, pr, name)
        if ep == "/coachs" and d.get("response"): i["C"] = d["response"][0]["id"]
    if P:
        for ep, pr in [("/players", {"id": P, "season": S}), ("/players/seasons", {"player": P}), ("/players/teams", {"player": P}),
                       ("/players/profiles", {"player": P}), ("/sidelined", {"player": P}), ("/transfers", {"player": P}), ("/trophies", {"player": P})]:
            probe(ep, pr, name)
    if i.get("C"):
        probe("/sidelined", {"coach": i["C"]}, name); probe("/trophies", {"coach": i["C"]}, name)
    if i["venue"]: probe("/venues", {"id": i["venue"]}, name)

# глобални списъци (без извадка по лига)
for ep, pr in [("/odds/live", {}), ("/odds/live/bets", {}), ("/odds/bookmakers", {}), ("/odds/bets", {}), ("/odds/mapping", {"page": 1}),
               ("/leagues/seasons", {}), ("/teams/countries", {})]:
    probe(ep, pr, "global")

# най-стар сезон с данни: england (39), по сезони
e = ids["england"]
for Y in [2008, 2010, 2012, 2014, 2016, 2018, 2020, 2022]:
    d = probe("/fixtures", {"league": 39, "season": Y}, "england", f"_s{Y}")
    fxs = [x for x in d.get("response") or [] if x["fixture"]["status"]["short"] == "FT"]
    for ep, pr in [("/standings", {"league": 39, "season": Y}), ("/players/topscorers", {"league": 39, "season": Y}),
                   ("/teams", {"league": 39, "season": Y}), ("/injuries", {"league": 39, "season": Y}),
                   ("/players", {"league": 39, "season": Y, "page": 1}), ("/odds", {"league": 39, "season": Y, "page": 1})]:
        probe(ep, pr, "england", f"_s{Y}")
    if fxs:
        F = fxs[len(fxs) // 2]["fixture"]["id"]
        for ep in ["/fixtures/statistics", "/fixtures/events", "/fixtures/lineups", "/fixtures/players", "/predictions", "/odds"]:
            probe(ep, {"fixture": F}, "england", f"_s{Y}")

with open("validation/api_probe_20261001.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
json.dump({k: sorted(v) for k, v in fields.items()}, open("validation/api_probe_fields_20261001.json", "w"), ensure_ascii=False, indent=0)
json.dump(ids, open("api_raw/probe_ids.json", "w"))
print("готово; заявки:", calls[0])
