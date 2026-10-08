"""market_visibility.py - ZADACHA_SKRIVANE (08.10.2026): кои пазари се показват на публичните страници (PUBLIC_HIDE=1).

Единица: лига × пазар. Таблица market_visibility в predictions.db (лигата "*" = всички лиги заедно). Админът не се влияе.

Данни (невидени мачове от последните WINDOW_DAYS дни):
  - проверката назад: ядро + слой AB (живите настройки), walk-forward - validation/pazar_ab_late_20261002.csv (lam1/mu1/rho);
    матрицата - football_lib.adjust_matrix (същата като живата и като pazar_lib_20261002.matrix, проверено - разлика 3e-17);
    калибрацията - като на сайта за мачове през слоя (layer_live.calibrate: 1X2, над/под 2.5, двата вкарват, голове на отбор);
    полувреме и пръв гол - методът от validation/pazar_poluvreme_20261002.py; корнери 9.5 - сегашният жив модел, walk-forward
    validation/final_v_20260924_matches.csv, калибриран (a = 0.855), както се показва;
  - уредените живи мачове от extra_markets_log (първата записана стойност, т.е. показаното число).
Мерило: D = Brier(модел) − Brier(средно); "средно" = честотата на изходите в същата лига през WINDOW_DAYS дни ПРЕДИ началото на мерения
период. Brier = средното от (процент − реалност)² по изходите (като pazar_lib.brier). a = Σ(p−b)(y−b)/Σ(p−b)² (като pazar_lib.calib_a).
Правила (по реда на проверка):
  г) HIDDEN_LEAGUES (portugal2) - лигата изцяло скрита (и от списъка /prognozi);
  в) лига под MIN_LEAGUE_N невидени мача (по 1X2) - всичките ѝ пазари скрити;
  а) за всички лиги заедно: горна граница на 95% bootstrap интервала на D ≥ 0, или a извън A_RANGE -> пазарът скрит навсякъде;
  б) по лига: z = D / стандартна грешка (bootstrap) > Z_HIDE -> скрит в лигата; връща се, когато D < 0 (задържане по предишната таблица);
     по лигата под MIN_MARKET_N мача за пазара ("няма данни") -> важи решението за всички лиги заедно.
  Двоен шанс следва 1X2. Полувреме/край, корнери извън 9.5, картони - винаги скрити (не са мерени на живия модел).
Флъск чете таблицата с кеш CACHE_TTL секунди (седмичната смяна влиза без рестарт). Липсва таблицата -> само постоянните правила
(г и винаги скритите), измерените пазари се показват.

Употреба: venv/bin/python3 market_visibility.py [--no-git] [--db ПЪТ] [--today ГГГГ-ММ-ДД]
  (седмично от cron: пише таблицата, validation/vidimost_<дата>.md, ред в notify_log.txt при промяна, commit+push само на отчета).
"""
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "predictions.db")
LOG_PATH = os.path.join(ROOT, "market_visibility_log.txt")

WINDOW_DAYS = 365
HIDDEN_LEAGUES = ("portugal2",)
MIN_LEAGUE_N = 150
MIN_MARKET_N = 30
Z_HIDE = 0.84
A_RANGE = (0.8, 1.25)
BOOT_N = 2000
CACHE_TTL = 300
ALL = "*"

# ключ, име, кодове (точни или префикс, завършващ на ":" или "_")
MARKETS = [
    ("1x2", "1X2", ("home_win", "draw", "away_win")),
    ("dc", "двоен шанс", ("dc_1x", "dc_12", "dc_x2")),
    ("ou15", "над/под 1.5", ("over15", "under15")),
    ("ou25", "над/под 2.5", ("over25", "under25")),
    ("ou35", "над/под 3.5", ("over35", "under35")),
    ("btts", "двата вкарват", ("btts_yes", "btts_no")),
    ("home_o15", "домакин над 1.5", ("home_over15", "home_under15")),
    ("away_o15", "гост над 1.5", ("away_over15", "away_under15")),
    ("home_cs", "чиста мрежа домакин", ("home_clean_sheet",)),
    ("away_cs", "чиста мрежа гост", ("away_clean_sheet",)),
    ("cs", "точен резултат", ("cs:",)),
    ("ht", "полувреме 1/X/2", ("ht:",)),
    ("first", "пръв гол", ("first:",)),
    ("corners95", "корнери общо 9.5", ("corners_total_over_9.5", "corners_total_under_9.5")),
]
FOLLOWS = {"dc": "1x2"}
# винаги скрити (не са мерени на живия модел): ключ, име, префикси
ALWAYS_HIDDEN = [
    ("htft", "полувреме/край", ("htft:", "htftall:")),
    ("corners_other", "корнери (освен общо 9.5)", ("corners_", "cornall:")),
    ("cards", "картони", ("cardall:", "cards_")),
]
MARKET_NAMES = {k: n for k, n, _ in MARKETS + ALWAYS_HIDDEN}


def _match(code, keys):
    return any(code == k or ((k.endswith(":") or k.endswith("_")) and code.startswith(k)) for k in keys)


def market_of(code):
    """код на изход -> ключ на пазара (MARKETS или ALWAYS_HIDDEN) или None (непознат)."""
    for k, _n, keys in MARKETS:
        if _match(code, keys):
            return k
    for k, _n, keys in ALWAYS_HIDDEN:
        if _match(code, keys):
            return k
    return None


# ----------------------------------------------------------------------------------------------- четене (Flask, леко)
DDL = """CREATE TABLE IF NOT EXISTS market_visibility (
    league TEXT NOT NULL, market TEXT NOT NULL, n INTEGER, d REAL, d_lo REAL, d_hi REAL, se REAL, z REAL, a REAL,
    brier_model REAL, brier_base REAL, visible INTEGER NOT NULL, rule TEXT, reason TEXT,
    window_from TEXT, window_to TEXT, computed_at TEXT, PRIMARY KEY (league, market))"""

_cache = {"at": 0.0, "rows": None}


def load(db_path=None):
    """{(лига, пазар): ред-речник} или None (няма таблица/празна/грешка). Без кеш."""
    try:
        con = sqlite3.connect("file:" + (db_path or DB_PATH) + "?mode=ro", uri=True, timeout=10)
        try:
            cur = con.execute("SELECT * FROM market_visibility")
            cols = [d[0] for d in cur.description]
            rows = {(r[0], r[1]): dict(zip(cols, r)) for r in cur.fetchall()}
            return rows or None
        finally:
            con.close()
    except Exception:
        return None


def table():
    """Като load(), с кеш CACHE_TTL секунди; при грешка - последната успешно прочетена."""
    now = time.time()
    if _cache["rows"] is None or now - _cache["at"] > CACHE_TTL:
        rows = load()
        _cache["at"] = now
        if rows is not None or _cache["rows"] is None:
            _cache["rows"] = rows
    return _cache["rows"]


def league_hidden(league):
    """Лигата изцяло скрита от публичните страници (правило г)."""
    return league in HIDDEN_LEAGUES


def market_visible(league, key, rows=None):
    if league_hidden(league) or key is None:
        return False
    if any(key == k for k, _n, _c in ALWAYS_HIDDEN):
        return False
    key = FOLLOWS.get(key, key)
    rows = table() if rows is None else rows
    if not rows:
        return True                      # няма таблица - само постоянните правила
    r = rows.get((league, key))
    if r is None:
        r = rows.get((ALL, key))
        if r is None or not r["visible"]:
            return False
        return (league, "1x2") in rows   # лига извън таблицата (нова) - скрита, докато не бъде мерена
    return bool(r["visible"])


def visible(league, code, rows=None):
    """Изходът (market_code) видим ли е публично за лигата."""
    return market_visible(league, market_of(code), rows)


# ----------------------------------------------------------------------------------------------- смятане (седмично, тежко)
def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass


LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal", "champions_league", "europa_league",
           "conference_league", "france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
G = 10
SHARE_DAYS = 730
CS_MAX = 3
WF_PATH = os.path.join(ROOT, "validation", "pazar_ab_late_20261002.csv")
CORNERS_PATH = os.path.join(ROOT, "validation", "final_v_20260924_matches.csv")


def _load_fixtures(pd):
    parts = []
    for lg in LEAGUES:
        f = os.path.join(ROOT, f"{lg}_fixtures.csv")
        if os.path.exists(f):
            d = pd.read_csv(f, low_memory=False, usecols=["fixture_id", "status", "timestamp", "home_id", "ht_home", "ht_away",
                                                          "ft_home", "ft_away", "fetched_at"])
            d["league"] = lg
            parts.append(d)
    fx = pd.concat(parts, ignore_index=True).sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["status"].isin(["FT", "AET", "PEN"])].copy()
    for c in ("ht_home", "ht_away", "ft_home", "ft_away", "timestamp", "home_id"):
        fx[c] = pd.to_numeric(fx[c], errors="coerce")
    return fx.dropna(subset=["ft_home", "ft_away", "timestamp"])


def _first_scorer(pd):
    """fixture_id -> ('h'/'a' за първия гол, брой голове в събитията) - като pazar_poluvreme_20261002.first_scorer (без отбора още)."""
    out = {}
    for lg in LEAGUES:
        for name in (f"{lg}_events.csv", f"{lg}_events_pre2024.csv"):
            f = os.path.join(ROOT, name)
            if not os.path.exists(f):
                continue
            ev = pd.read_csv(f, low_memory=False, usecols=["fixture_id", "event_index", "team_id", "type", "detail"])
            ev = ev[(ev["type"] == "Goal") & (ev["detail"] != "Missed Penalty")].sort_values(["fixture_id", "event_index"])
            for fid, g in ev.groupby("fixture_id"):
                out[int(fid)] = (int(g["team_id"].iloc[0]), g["detail"].iloc[0], len(g))
    return out


def _corners(pd):
    """fixture_id -> общо корнери (от {лига}_merged_full.csv)."""
    out = {}
    for lg in LEAGUES:
        f = os.path.join(ROOT, f"{lg}_merged_full.csv")
        if not os.path.exists(f):
            continue
        d = pd.read_csv(f, low_memory=False, usecols=lambda c: c in ("fixture_id", "home_corners", "away_corners"))
        if "home_corners" not in d:
            continue
        d = d.dropna(subset=["fixture_id", "home_corners", "away_corners"])
        out.update(zip(d["fixture_id"].astype(int), (d["home_corners"] + d["away_corners"]).astype(float)))
    return out


def _y_first(fid, hg, ag, home_id, fs):
    """[домакин, никой, гост] или None (няма събития / броят им ≠ резултата)."""
    if hg + ag == 0:
        return [0.0, 1.0, 0.0]
    e = fs.get(int(fid))
    if e is None or e[2] != hg + ag or home_id != home_id:          # home_id NaN
        return None
    team, detail, _n = e
    home_first = (team == int(home_id)) != (detail == "Own Goal")
    return [1.0, 0.0, 0.0] if home_first else [0.0, 0.0, 1.0]


def _outcomes_from_score(np, hg, ag):
    """Реалността по пазар (без полувреме/пръв гол/корнери) от крайния резултат; hg, ag - масиви."""
    o = lambda x: np.column_stack([x, 1 - x]).astype(float)  # noqa: E731
    cs = np.column_stack([((hg == i) & (ag == j)) for i in range(CS_MAX + 1) for j in range(CS_MAX + 1)]).astype(float)
    return {"1x2": np.column_stack([hg > ag, hg == ag, hg < ag]).astype(float),
            "ou15": o(hg + ag > 1.5), "ou25": o(hg + ag > 2.5), "ou35": o(hg + ag > 3.5),
            "btts": o((hg > 0) & (ag > 0)), "home_o15": o(hg > 1.5), "away_o15": o(ag > 1.5),
            "home_cs": o(ag == 0), "away_cs": o(hg == 0), "cs": np.column_stack([cs, 1 - cs.sum(1)])}


def _calibrate(np, p, code):
    """Вектор p (0-1) -> както layer_live.calibrate за мачове през слоя (показаното число)."""
    import layer_live
    out = np.array([layer_live.calibrate(x * 100.0, code) / 100.0 for x in p])
    return out


def _probs_from_matrix(np, pm, lam, mu, sh, sa):
    """Матрици (N,G,G) -> вероятностите на пазарите, както на сайта (калибрирани там, където сайтът калибрира)."""
    X, Y = np.meshgrid(np.arange(G), np.arange(G), indexing="ij")
    hw, dr, aw = pm[:, X > Y].sum(1), pm[:, X == Y].sum(1), pm[:, X < Y].sum(1)
    c = lambda p, code: _calibrate(np, p, code)  # noqa: E731
    two = lambda p: np.column_stack([p, 1 - p])  # noqa: E731
    o15, o25, o35 = pm[:, X + Y > 1.5].sum(1), pm[:, X + Y > 2.5].sum(1), pm[:, X + Y > 3.5].sum(1)
    bt = pm[:, 1:, 1:].sum((1, 2))
    ho, ao = pm[:, 2:, :].sum((1, 2)), pm[:, :, 2:].sum((1, 2))
    cells = np.column_stack([pm[:, i, j] for i in range(CS_MAX + 1) for j in range(CS_MAX + 1)])
    p00 = pm[:, 0, 0]
    share = lam / (lam + mu)
    from scipy.stats import poisson
    lh, la = lam * sh, mu * sa
    ph, pa = poisson.pmf(np.arange(G)[None, :], lh[:, None]), poisson.pmf(np.arange(G)[None, :], la[:, None])
    m = ph[:, :, None] * pa[:, None, :]
    ht = np.column_stack([m[:, X > Y].sum(1), m[:, X == Y].sum(1), m[:, X < Y].sum(1)])
    ht = ht / ht.sum(1, keepdims=True)
    return {"1x2": np.column_stack([c(hw, "home_win"), c(dr, "draw"), c(aw, "away_win")]),
            "ou15": two(o15), "ou25": np.column_stack([c(o25, "over25"), c(1 - o25, "under25")]), "ou35": two(o35),
            "btts": np.column_stack([c(bt, "btts_yes"), c(1 - bt, "btts_no")]),
            "home_o15": np.column_stack([c(ho, "home_over15"), c(1 - ho, "home_under15")]),
            "away_o15": np.column_stack([c(ao, "away_over15"), c(1 - ao, "away_under15")]),
            "home_cs": two(pm[:, :, 0].sum(1)), "away_cs": two(pm[:, 0, :].sum(1)),
            "cs": np.column_stack([cells, 1 - cells.sum(1)]),
            "ht": ht, "first": np.column_stack([(1 - p00) * share, p00, (1 - p00) * (1 - share)])}


LIVE_CODES = {
    "1x2": ["home_win", "draw", "away_win"], "ou15": ["over15", "under15"], "ou25": ["over25", "under25"], "ou35": ["over35", "under35"],
    "btts": ["btts_yes", "btts_no"], "home_o15": ["home_over15", "home_under15"], "away_o15": ["away_over15", "away_under15"],
    "home_cs": ["home_clean_sheet"], "away_cs": ["away_clean_sheet"],
    "cs": [f"cs:{i}-{j}" for i in range(CS_MAX + 1) for j in range(CS_MAX + 1)] + ["cs:other"],
    "ht": ["ht:1", "ht:X", "ht:2"], "first": ["first:home", "first:none", "first:away"],
    "corners95": ["corners_total_over_9.5", "corners_total_under_9.5"],
}


def gather(today, db_path=None):
    """-> (данни, база, прозорец): данни[пазар] = списък от (лига, fixture_id, P ред, Y ред, източник);
    база[(лига, пазар)] = вектор b; прозорец = (от, до) като дати."""
    import numpy as np
    import pandas as pd
    import football_lib as fl
    from scipy.stats import poisson

    t_to = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    t_from = t_to - timedelta(days=WINDOW_DAYS)
    b_from = t_from - timedelta(days=WINDOW_DAYS)
    fx = _load_fixtures(pd)
    fxi = fx.set_index("fixture_id")
    fs = _first_scorer(pd)
    corn = _corners(pd)
    data = {k: [] for k, _n, _c in MARKETS if k not in FOLLOWS}

    # --- проверката назад (ядро + слой AB)
    wf = pd.read_csv(WF_PATH)
    wf["d"] = pd.to_datetime(wf["date"]).dt.tz_localize("UTC")
    wf = wf[(wf["d"] >= t_from) & (wf["d"] < t_to)].reset_index(drop=True)
    lam, mu, rho = wf["lam1"].to_numpy(float), wf["mu1"].to_numpy(float), wf["rho"].to_numpy(float)
    pm = np.stack([fl.adjust_matrix(np.outer(poisson.pmf(range(G), lam[i]), poisson.pmf(range(G), mu[i])), lam[i], mu[i], rho[i])
                   for i in range(len(wf))]) if len(wf) else np.zeros((0, G, G))
    # дял на головете на полувремето: по седмица, само от мачове преди нея (последните SHARE_DAYS дни) - като pazar_poluvreme
    week = (wf["d"] - pd.to_timedelta(wf["d"].dt.weekday, unit="D")).dt.normalize()
    sh, sa = np.full(len(wf), 0.44), np.full(len(wf), 0.44)
    for wk, idx in wf.groupby(week).groups.items():
        ts = wk.timestamp()
        h = fx[(fx["timestamp"] < ts) & (fx["timestamp"] >= ts - SHARE_DAYS * 86400)].dropna(subset=["ht_home", "ht_away"])
        s = {lg: (g["ht_home"].sum() / max(g["ft_home"].sum(), 1), g["ht_away"].sum() / max(g["ft_away"].sum(), 1))
             for lg, g in h.groupby("league")}
        for i in idx:
            sh[i], sa[i] = s.get(wf.at[i, "league"], (0.44, 0.44))
    P = _probs_from_matrix(np, pm, lam, mu, sh, sa) if len(wf) else {}
    hg, ag = wf["hg"].to_numpy(int), wf["ag"].to_numpy(int)
    Ys = _outcomes_from_score(np, hg, ag)
    for i, r in enumerate(wf.itertuples()):
        lg, fid = r.league, int(r.fixture_id)
        for k in Ys:
            data[k].append((lg, fid, P[k][i], Ys[k][i], "wf"))
        f = fxi.loc[fid] if fid in fxi.index else None
        if f is not None and f["ht_home"] == f["ht_home"] and f["ht_away"] == f["ht_away"]:
            hh, ha = f["ht_home"], f["ht_away"]
            data["ht"].append((lg, fid, P["ht"][i], np.array([hh > ha, hh == ha, hh < ha], float), "wf"))
        yf = _y_first(fid, int(r.hg), int(r.ag), f["home_id"] if f is not None else float("nan"), fs) if (f is not None or r.hg + r.ag == 0) else None
        if yf is not None:
            data["first"].append((lg, fid, P["first"][i], np.array(yf), "wf"))
    # корнери 9.5: сегашният жив модел (walk-forward от final_v), калибриран както се показва
    if os.path.exists(CORNERS_PATH):
        cv = pd.read_csv(CORNERS_PATH, usecols=["league", "fixture_id", "date", "p_corners_total_over_9.5", "y_corners_total_over_9.5"]).dropna()
        cv["d"] = pd.to_datetime(cv["date"]).dt.tz_localize("UTC")
        cv = cv[(cv["d"] >= t_from) & (cv["d"] < t_to)]
        pc = _calibrate(np, cv["p_corners_total_over_9.5"].to_numpy(float), "corners_total_over_9.5")
        for lg, fid, p, y in zip(cv["league"], cv["fixture_id"], pc, cv["y_corners_total_over_9.5"].to_numpy(float)):
            data["corners95"].append((lg, int(fid), np.array([p, 1 - p]), np.array([y, 1 - y]), "wf"))

    # --- уредените живи мачове (extra_markets_log - първата записана стойност)
    n_live = 0
    try:
        con = sqlite3.connect("file:" + (db_path or DB_PATH) + "?mode=ro", uri=True, timeout=30)
        try:
            lg_rows = con.execute("SELECT fixture_id, league, match_date, market_code, pick_pct FROM extra_markets_log").fetchall()
        finally:
            con.close()
    except Exception as e:
        log(f"extra_markets_log не се чете: {e}")
        lg_rows = []
    by_fx = {}
    for fid, lg, md, code, pct in lg_rows:
        by_fx.setdefault(int(fid), {"league": lg, "date": md, "p": {}})["p"][code] = pct
    have = {k: {x[1] for x in v} for k, v in data.items()}
    for fid, e in by_fx.items():
        if fid not in fxi.index:
            continue
        f = fxi.loc[fid]
        ts = datetime.fromtimestamp(float(f["timestamp"]), timezone.utc)
        if not (t_from <= ts < t_to):
            continue
        hg_, ag_ = int(f["ft_home"]), int(f["ft_away"])
        Ys1 = {k: v[0] for k, v in _outcomes_from_score(np, np.array([hg_]), np.array([ag_])).items()}
        if f["ht_home"] == f["ht_home"] and f["ht_away"] == f["ht_away"]:
            Ys1["ht"] = np.array([f["ht_home"] > f["ht_away"], f["ht_home"] == f["ht_away"], f["ht_home"] < f["ht_away"]], float)
        yf = _y_first(fid, hg_, ag_, f["home_id"], fs)
        if yf is not None:
            Ys1["first"] = np.array(yf)
        if fid in corn:
            Ys1["corners95"] = np.array([corn[fid] > 9.5, corn[fid] <= 9.5], float)
        used = False
        for k, codes in LIVE_CODES.items():
            if k not in Ys1 or fid in have[k] or any(e["p"].get(c) is None for c in codes):
                continue
            p = np.array([e["p"][c] for c in codes], float) / 100.0
            if k == "cs":
                p = np.append(p[:-1], max(0.0, 1 - p[:-1].sum()))
            if len(codes) == 1:
                p = np.array([p[0], 1 - p[0]])
            data[k].append((e["league"], fid, p, Ys1[k], "live"))
            used = True
        n_live += used

    # --- база: честотите в лигата през WINDOW_DAYS дни преди началото на мерения период
    base = {}
    bx = fx[(fx["timestamp"] >= b_from.timestamp()) & (fx["timestamp"] < t_from.timestamp())]
    for lg, g in bx.groupby("league"):
        hg_, ag_ = g["ft_home"].to_numpy(int), g["ft_away"].to_numpy(int)
        for k, Y in _outcomes_from_score(np, hg_, ag_).items():
            base[(lg, k)] = (Y.mean(0), len(Y))
        gh = g.dropna(subset=["ht_home", "ht_away"])
        if len(gh):
            hh, ha = gh["ht_home"].to_numpy(), gh["ht_away"].to_numpy()
            base[(lg, "ht")] = (np.column_stack([hh > ha, hh == ha, hh < ha]).astype(float).mean(0), len(gh))
        yfs = [y for y in (_y_first(r.fixture_id, int(r.ft_home), int(r.ft_away), r.home_id, fs) for r in g.itertuples()) if y is not None]
        if yfs:
            base[(lg, "first")] = (np.array(yfs).mean(0), len(yfs))
        cc = np.array([corn[int(x)] for x in g["fixture_id"] if int(x) in corn])
        if len(cc):
            base[(lg, "corners95")] = (np.array([(cc > 9.5).mean(), (cc <= 9.5).mean()]), len(cc))
    info = {"from": t_from.date().isoformat(), "to": (t_to - timedelta(days=1)).date().isoformat(),
            "base_from": b_from.date().isoformat(), "n_wf": int(len(wf)), "n_live": int(n_live)}
    return data, base, info


def _stats(np, P, Y, B):
    """-> речник с числата: D (средно), интервал, SE, z, a, Brier модел/база."""
    bm = ((P - Y) ** 2).mean(1)
    bb = ((B - Y) ** 2).mean(1)
    x = bm - bb
    rng = np.random.default_rng(42)
    means = np.empty(BOOT_N)
    for s in range(0, BOOT_N, 200):                     # на части - паметта остава малка и при ~6000 мача
        idx = rng.integers(0, len(x), size=(min(200, BOOT_N - s), len(x)))
        means[s:s + len(idx)] = x[idx].mean(1)
    se = float(means.std(ddof=1))
    d = float(x.mean())
    dp = P - B
    den = float((dp * dp).sum())
    a = float((dp * (Y - B)).sum() / den) if den > 0 else float("nan")
    return {"n": int(len(x)), "d": d, "d_lo": float(np.percentile(means, 2.5)), "d_hi": float(np.percentile(means, 97.5)),
            "se": se, "z": (d / se) if se > 0 else float("nan"), "a": a, "brier_model": float(bm.mean()), "brier_base": float(bb.mean())}


def compute(today=None, prev=None, db_path=None):
    """-> (редове за таблицата, инфо). prev - предишната таблица (за задържането по б)); None -> load()."""
    import numpy as np
    today = today or datetime.now(timezone.utc).date()
    prev = load(db_path) if prev is None else prev
    data, base, info = gather(today, db_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    common = {"window_from": info["from"], "window_to": info["to"], "computed_at": now}
    out = []
    n1x2 = {}
    for lg, *_ in data["1x2"]:
        n1x2[lg] = n1x2.get(lg, 0) + 1
    info["n_by_league"] = n1x2
    pooled = {}
    for k, name, _c in MARKETS:
        if k in FOLLOWS:
            continue
        rows = [r for r in data[k] if (r[0], k) in base]
        if not rows:
            pooled[k] = None
            out.append({"league": ALL, "market": k, "n": 0, "visible": 0, "rule": "а", "reason": "няма данни", **common})
            continue
        P = np.array([r[2] for r in rows])
        Y = np.array([r[3] for r in rows])
        B = np.array([base[(r[0], k)][0] for r in rows])
        s = _stats(np, P, Y, B)
        why = []
        if s["d_hi"] >= 0:
            why.append(f"горната граница на D е {s['d_hi']:+.5f} ≥ 0 (не е сигурно по-добър от средното)")
        if not (A_RANGE[0] <= s["a"] <= A_RANGE[1]):
            why.append(f"калибрация a = {s['a']:.3f} извън {A_RANGE[0]}–{A_RANGE[1]}")
        pooled[k] = (not why, "; ".join(why))
        out.append({"league": ALL, "market": k, **s, "visible": int(not why), "rule": "а" if why else "",
                    "reason": "скрит навсякъде: " + "; ".join(why) if why else "по-добър от средното за всички лиги заедно", **common})
        by_lg = {}
        for r in rows:
            by_lg.setdefault(r[0], []).append(r)
        for lg in sorted(set(LEAGUES) | set(by_lg)):
            lr = by_lg.get(lg, [])
            s = _stats(np, np.array([r[2] for r in lr]), np.array([r[3] for r in lr]),
                       np.array([base[(lg, k)][0] for r in lr])) if len(lr) >= 2 else {"n": len(lr)}
            row = {"league": lg, "market": k, **s, **common}
            prev_row = (prev or {}).get((lg, k))
            if league_hidden(lg):
                vis, rule, reason = False, "г", "лигата е скрита от публичните страници"
            elif n1x2.get(lg, 0) < MIN_LEAGUE_N:
                vis, rule, reason = False, "в", f"под {MIN_LEAGUE_N} невидени мача в лигата ({n1x2.get(lg, 0)})"
            elif not pooled[k][0]:
                vis, rule, reason = False, "а", "скрит навсякъде: " + pooled[k][1]
            elif len(lr) < MIN_MARKET_N:
                vis, rule, reason = True, "", f"по лигата няма данни ({len(lr)} мача) - важи решението за всички лиги"
            elif s["z"] > Z_HIDE:
                vis, rule, reason = False, "б", f"по-зле от средното за лигата (z = {s['z']:.2f} > {Z_HIDE})"
            elif prev_row is not None and prev_row.get("rule") in ("б", "б*") and s["d"] >= 0:
                vis, rule, reason = False, "б*", f"скрит от преди; връща се, когато D < 0 (сега D = {s['d']:+.5f})"
            else:
                vis, rule, reason = True, "", "видим"
            row.update(visible=int(vis), rule=rule, reason=reason)
            out.append(row)
    # двоен шанс - следва 1X2
    for r in [r for r in out if r["market"] == "1x2"]:
        out.append({**{k: None for k in ("n", "d", "d_lo", "d_hi", "se", "z", "a", "brier_model", "brier_base")}, **common,
                    "league": r["league"], "market": "dc", "visible": r["visible"], "rule": r["rule"],
                    "reason": "следва 1X2" + (f" ({r['reason']})" if not r["visible"] else "")})
    for k, name, _c in ALWAYS_HIDDEN:
        out.append({"league": ALL, "market": k, "visible": 0, "rule": "винаги", "reason": "не е мерен на живия модел", **common})
    return out, info


COLS = ["league", "market", "n", "d", "d_lo", "d_hi", "se", "z", "a", "brier_model", "brier_base", "visible", "rule", "reason",
        "window_from", "window_to", "computed_at"]


def save(rows, db_path=None):
    """Заменя таблицата атомарно (една транзакция)."""
    con = sqlite3.connect(db_path or DB_PATH, timeout=60)
    try:
        con.execute("PRAGMA busy_timeout=60000")
        con.execute(DDL)
        with con:
            con.execute("DELETE FROM market_visibility")
            con.executemany(f"INSERT INTO market_visibility ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                            [tuple((None if (isinstance(r.get(c), float) and r.get(c) != r.get(c)) else r.get(c)) for c in COLS)
                             for r in rows])
    finally:
        con.close()


def changes(prev, rows):
    """[(лига, пазар, било, става)] - само смените видим/скрит."""
    out = []
    for r in rows:
        p = (prev or {}).get((r["league"], r["market"]))
        if p is not None and bool(p["visible"]) != bool(r["visible"]):
            out.append((r["league"], r["market"], bool(p["visible"]), bool(r["visible"])))
    return out


def _f(x, fmt):
    return "—" if x is None or x != x else format(x, fmt)


def report(rows, info, chg, first_run):
    """Текстът на validation/vidimost_<дата>.md."""
    L = [f"# Видимост на пазарите — {info['to_day']}", "",
         "Автоматично от `market_visibility.py` (ZADACHA_SKRIVANE). Методът — в докстринга на модула.", "",
         f"- Мерен период (невидени мачове): {info['from']} – {info['to']}; „средно“ = честотата в лигата {info['base_from']} – {info['from']} (без последния ден).",
         f"- Мачове: проверката назад {info['n_wf']}, уредени живи (extra_markets_log) {info['n_live']}.",
         f"- Правила: а) всички лиги — горна граница на 95% интервала на D ≥ 0 или a извън {A_RANGE[0]}–{A_RANGE[1]}; "
         f"б) лига — z > {Z_HIDE} (връща се при D < 0); в) лига под {MIN_LEAGUE_N} мача; г) {', '.join(HIDDEN_LEAGUES)} изцяло скрита. "
         f"Пазар с под {MIN_MARKET_N} мача в лигата — важи решението за всички лиги.", ""]
    L += ["## Промени спрямо предишната таблица", ""]
    if first_run:
        L += ["Първо изчисляване — няма предишна таблица.", ""]
    elif chg:
        L += [f"- {lg if lg != ALL else 'всички лиги'} / {MARKET_NAMES.get(m, m)}: {'видим' if a else 'скрит'} → {'видим' if b else 'скрит'}"
              for lg, m, a, b in chg] + [""]
    else:
        L += ["Няма промени.", ""]
    L += ["## Всички лиги заедно (правило а)", "", "| пазар | мачове | D [95%] | a | решение |", "|---|---|---|---|---|"]
    for r in rows:
        if r["league"] == ALL:
            L.append(f"| {MARKET_NAMES.get(r['market'], r['market'])} | {r.get('n') or '—'} | {_f(r.get('d'), '+.5f')} "
                     f"[{_f(r.get('d_lo'), '+.5f')}; {_f(r.get('d_hi'), '+.5f')}] | {_f(r.get('a'), '.3f')} | "
                     f"{'видим' if r['visible'] else '**скрит**'} — {r['reason']} |")
    hidden = [r for r in rows if r["league"] != ALL and not r["visible"] and r["rule"] not in ("г",)]
    L += ["", "## Скрити по лиги (без изцяло скритите по г)", ""]
    L += ([f"- {r['league']} / {MARKET_NAMES.get(r['market'], r['market'])}: {r['reason']}" for r in hidden] or ["Няма."]) + [""]
    L += ["## Пълна таблица по лиги", "", "| лига | пазар | мачове | D | 95% | SE | z | a | видим | правило / причина |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted((r for r in rows if r["league"] != ALL), key=lambda r: (r["league"], [k for k, *_ in MARKETS].index(r["market"]))):
        L.append(f"| {r['league']} | {MARKET_NAMES.get(r['market'], r['market'])} | {r.get('n') if r.get('n') is not None else '—'} | "
                 f"{_f(r.get('d'), '+.5f')} | [{_f(r.get('d_lo'), '+.5f')}; {_f(r.get('d_hi'), '+.5f')}] | {_f(r.get('se'), '.5f')} | "
                 f"{_f(r.get('z'), '+.2f')} | {_f(r.get('a'), '.3f')} | {'да' if r['visible'] else '**не**'} | "
                 f"{(r['rule'] + ': ') if r['rule'] else ''}{r['reason']} |")
    return "\n".join(L) + "\n"


def run(today=None, db_path=None, do_git=True, report_dir=None):
    """Седмичното преизчисляване. Грешка -> таблицата остава последната (нищо не се пише), ред в лога + известие. -> код (0/1)."""
    import subprocess
    today = today or datetime.now(timezone.utc).date()
    try:
        prev = load(db_path)
        rows, info = compute(today, prev, db_path)
        info["to_day"] = today.isoformat()
        if not any(r["league"] != ALL for r in rows):
            raise RuntimeError("празна таблица по лиги")
        chg = changes(prev, rows)
        save(rows, db_path)
        rd = report_dir or os.path.join(ROOT, "validation")
        path = os.path.join(rd, f"vidimost_{today.strftime('%Y%m%d')}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(report(rows, info, chg, prev is None))
        log(f"OK: {len(rows)} реда, проверка назад {info['n_wf']}, живи {info['n_live']}, промени {len(chg)} -> {path}")
        if chg:
            import notify
            notify.send("Видимост на пазарите: " + "; ".join(
                f"{lg if lg != ALL else 'всички лиги'} / {MARKET_NAMES.get(m, m)} - {'върнат' if b else 'скрит'}" for lg, m, _a, b in chg)
                + f" (validation/{os.path.basename(path)})")
        if do_git:
            rel = os.path.relpath(path, ROOT)
            for cmd in (["git", "add", "--", rel],
                        ["git", "commit", "-m", f"ВИДИМОСТ: седмично преизчисляване ({today.isoformat()})\n\n"
                         "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", "--", rel],
                        ["git", "push", "origin", "master"]):
                p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
                if p.returncode != 0:
                    log(f"{' '.join(cmd[:2])}: {(p.stdout + p.stderr).strip()[:300]}")
                    break
        return 0
    except Exception as e:
        import traceback
        log(f"ГРЕШКА (таблицата остава последната): {type(e).__name__}: {e} | {traceback.format_exc()[-600:]}")
        try:
            import notify
            notify.send(f"Видимост на пазарите: ГРЕШКА при седмичното преизчисляване ({type(e).__name__}: {e}) - остава последната таблица")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    args = sys.argv[1:]
    db = args[args.index("--db") + 1] if "--db" in args else None
    td = datetime.strptime(args[args.index("--today") + 1], "%Y-%m-%d").date() if "--today" in args else None
    rdir = args[args.index("--report-dir") + 1] if "--report-dir" in args else None
    sys.exit(run(td, db, do_git="--no-git" not in args, report_dir=rdir))
