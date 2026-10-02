"""extra_markets.py - новите пазари на страницата на мача (ZADACHA_RAZVITIE т.5, 02.10.2026). Само показване - не влизат в predictions_log,
в избора на главната прогноза, нито в метриките (снимката ги пише с is_candidate=0, като останалата пълна таблица).

Влизат само пазарите, минали проверката (walk-forward, калибрация 0.9-1.1 на късната половина, по-информативни от честотата):
  над/под 1.5 гола и точен резултат         - validation/pazar_goli_20261002.md   (над/под 3.5 НЕ мина: a = 0.884)
  полувреме 1/X/2 и кой вкарва пръв        - validation/pazar_poluvreme_20261002.md
Методът е ТОЧНО този от проверката: матрицата на мача (Поасон + football_lib.adjust_matrix - същата като 1X2 на сайта) от lam/mu след слоя;
полувремето - Поасон с lam·s_д, mu·s_г (s = дял на головете на полувремето в лигата, последните 730 дни, от {лига}_fixtures.csv);
пръв гол - P(никой) = P(0-0), иначе по lam/(lam+mu). Без калибрация (проверката е на некалибрираните числа).
Превключвател EXTRA_MARKETS в .env (0/липсва = нищо не се добавя). Всяка грешка -> [] (страницата е като преди).
Таблици (predictions.db), ОТДЕЛНИ от predictions_snapshot (така никой съществуващ читател на снимката - /daily, /prognozi - не ги вижда):
  extra_markets_snapshot - текущите стойности по мач (заменят се при всеки цикъл на снимката), чете ги само страницата на мача;
  extra_markets_log      - само добавяне, първата стойност на мач и пазар - за бъдещо мерене на живо.
"""
import os
import sqlite3
import time
from datetime import datetime

import numpy as np
from scipy.stats import poisson

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "predictions.db")
MAX_G = 10
SHARE_DAYS = 730
DEFAULT_SHARE = 0.44
CS_MAX = 3                       # точен резултат: клетките 0-0 ... 3-3 + "друг" (както в проверката)
_shares = {"at": 0.0, "by_league": {}}


def enabled():
    try:
        import config
        return bool(getattr(config, "EXTRA_MARKETS", False)) or show_all()
    except Exception:
        return False


def show_all():
    """ZADACHA_VSICHKO (02.10.2026): SHOW_ALL=1 - страницата на мача показва ВСИЧКО, което моделът смята (с етикет), не само проверените."""
    try:
        import config
        return bool(getattr(config, "SHOW_ALL", False))
    except Exception:
        return False


# ----------------------------------------------------------------------------------------------- само за SHOW_ALL
CORNER_TOTAL_LINES = [7.5, 8.5, 9.5, 10.5, 11.5, 12.5]
CORNER_TEAM_LINES = [3.5, 4.5, 5.5, 6.5]
CARD_TOTAL_LINES = [2.5, 3.5, 4.5, 5.5, 6.5]
CARDS_MIN_COVERAGE = 0.7          # като CORNERS_MIN_COVERAGE: под 70% мачове с картони -> няма модел ("няма данни")
CACHE_DIR = os.path.join(ROOT, "extra_cache")      # НЕ model_cache/ - живият кеш на моделите не се пипа
_cards = {}


def cards_model(league):
    """Поасон по отбор (football_lib.fit_total_model) за картоните (жълти + червени) от {лига}_merged_full.csv - както беше живият cards_model
    до 25.08.2026. None при покритие < CARDS_MIN_COVERAGE или грешка. Кеш на диска по ден (extra_cache/)."""
    if league in _cards:
        return _cards[league]
    model = None
    try:
        import pickle
        import pandas as pd
        import football_lib as fl
        day = datetime.utcnow().strftime("%Y%m%d")
        cp = os.path.join(CACHE_DIR, f"{league}_cards_{day}.pkl")
        if os.path.exists(cp):
            with open(cp, "rb") as f:
                model = pickle.load(f)
        else:
            df = fl.load_league_data(league)
            fin = df.dropna(subset=["home_goals", "away_goals"])
            if "home_yellow" in df.columns and len(fin):
                cov = fin["home_yellow"].notna() & fin["away_yellow"].notna()
                if cov.mean() >= CARDS_MIN_COVERAGE:
                    d = fin[cov].copy()
                    d["home_cards"] = d["home_yellow"] + (d["home_red"].fillna(0) if "home_red" in d else 0)
                    d["away_cards"] = d["away_yellow"] + (d["away_red"].fillna(0) if "away_red" in d else 0)
                    teams, n, ti = fl.get_team_index(df)
                    m = fl.fit_total_model(d, d["date"].max() + pd.Timedelta(days=1), ti, n, "home_cards", "away_cards",
                                           xi=fl.LEAGUE_XI.get(league, fl.XI))
                    model = {"model": m, "team_idx": ti}
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cp, "wb") as f:
                pickle.dump(model, f)
    except Exception:
        model = None
    _cards[league] = model
    return model


def _all_items(league, lam, mu, home, away, home_cy, away_cy, pm, corners, htft):
    """Допълнителните изходи при SHOW_ALL: над/под 3.5, всички 9 полувреме/край, корнери и картони на всички линии."""
    import football_lib as fl
    X, Y = np.meshgrid(np.arange(MAX_G), np.arange(MAX_G), indexing="ij")
    out = []
    o35 = float(pm[X + Y > 3.5].sum())
    out += [("over35", "Над 3.5", 100 * o35), ("under35", "Под 3.5", 100 * (1 - o35))]
    if htft:
        tot = sum(htft.values())
        for k, v in htft.items():
            out.append((f"htftall:{k}", k, 100 * v / tot))
    if corners is not None:
        lam_c, mu_c, alpha = corners
        ph, pa = fl._nb_pmf(lam_c, alpha), fl._nb_pmf(mu_c, alpha)
        pt = np.convolve(ph, pa)[:fl.CORNERS_MAX]
        for line in CORNER_TOTAL_LINES:
            p = float(1 - pt[:int(line) + 1].sum())
            out += [(f"cornall:total_over_{line}", f"Над {line}", 100 * p), (f"cornall:total_under_{line}", f"Под {line}", 100 * (1 - p))]
        for side, pmf, cy in (("home", ph, home_cy), ("away", pa, away_cy)):
            for line in CORNER_TEAM_LINES:
                p = float(1 - pmf[:int(line) + 1].sum())
                out += [(f"cornall:{side}_over_{line}", f"{cy} над {line}", 100 * p), (f"cornall:{side}_under_{line}", f"{cy} под {line}", 100 * (1 - p))]
    cm = cards_model(league)
    if cm is not None and home in cm["team_idx"] and away in cm["team_idx"]:
        lh, la = fl.get_lambdas(cm["model"], cm["team_idx"], home, away)
        for line in CARD_TOTAL_LINES:
            p = float(fl.total_ou_prob(lh, la, line))
            out += [(f"cardall:total_over_{line}", f"Над {line}", 100 * p), (f"cardall:total_under_{line}", f"Под {line}", 100 * (1 - p))]
    return out


def ht_shares(league):
    """(s_д, s_г) - дял на головете на полувремето в лигата за последните SHARE_DAYS дни. Кеш 6 ч."""
    if time.time() - _shares["at"] > 6 * 3600:
        _shares.update(at=time.time(), by_league={})
    if league in _shares["by_league"]:
        return _shares["by_league"][league]
    out = (DEFAULT_SHARE, DEFAULT_SHARE)
    try:
        import pandas as pd
        f = os.path.join(ROOT, f"{league}_fixtures.csv")
        fx = pd.read_csv(f, usecols=["fixture_id", "status", "timestamp", "ht_home", "ht_away", "ft_home", "ft_away", "fetched_at"])
        fx = fx.sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
        fx = fx[fx["status"].isin(["FT", "AET", "PEN"]) & (fx["timestamp"] >= time.time() - SHARE_DAYS * 86400)].dropna()
        if len(fx) >= 50 and fx["ft_home"].sum() > 0 and fx["ft_away"].sum() > 0:
            out = (fx["ht_home"].sum() / fx["ft_home"].sum(), fx["ht_away"].sum() / fx["ft_away"].sum())
    except Exception:
        pass
    _shares["by_league"][league] = out
    return out


def compute(league, lam, mu, rho, home_cy="Домакин", away_cy="Гост", home=None, away=None, corners=None, htft=None):
    """-> [(код, етикет, процент)]; [] при изключен превключвател или грешка. home/away/corners=(lam_c, mu_c, alpha)/htft={изход: p} -
    само за SHOW_ALL (иначе не се ползват)."""
    if not enabled():
        return []
    try:
        import football_lib as fl
        pm = np.outer(poisson.pmf(range(MAX_G), lam), poisson.pmf(range(MAX_G), mu))
        pm = fl.adjust_matrix(pm, lam, mu, rho)
        X, Y = np.meshgrid(np.arange(MAX_G), np.arange(MAX_G), indexing="ij")
        out = []
        o15 = float(pm[X + Y > 1.5].sum())
        out += [("over15", "Над 1.5", 100 * o15), ("under15", "Под 1.5", 100 * (1 - o15))]
        cs_total = 0.0
        for i in range(CS_MAX + 1):
            for j in range(CS_MAX + 1):
                p = float(pm[i, j])
                cs_total += p
                out.append((f"cs:{i}-{j}", f"{i}:{j}", 100 * p))
        out.append(("cs:other", "друг", 100 * (1 - cs_total)))
        sh, sa = ht_shares(league)
        ph = np.outer(poisson.pmf(range(MAX_G), lam * sh), poisson.pmf(range(MAX_G), mu * sa))
        ph = ph / ph.sum()
        out += [("ht:1", "1", 100 * float(np.tril(ph, -1).sum())), ("ht:X", "X", 100 * float(np.trace(ph))),
                ("ht:2", "2", 100 * float(np.triu(ph, 1).sum()))]
        p00 = float(pm[0, 0])
        share = float(lam / (lam + mu))
        out += [("first:home", home_cy, 100 * (1 - p00) * share), ("first:none", "Никой", 100 * p00),
                ("first:away", away_cy, 100 * (1 - p00) * (1 - share))]
        if not all(np.isfinite(p) and 0 <= p <= 100 for _c, _l, p in out):
            return []
        if show_all():
            try:
                more = _all_items(league, lam, mu, home, away, home_cy, away_cy, pm, corners, htft)
                out += [(c, l, float(min(100.0, max(0.0, p)))) for c, l, p in more if np.isfinite(p) and -1e-6 <= p <= 100 + 1e-6]
            except Exception:
                pass                      # пълният изглед без допълнителните - проверените пазари остават
        return out
    except Exception:
        return []


DDL_SNAPSHOT = """CREATE TABLE IF NOT EXISTS extra_markets_snapshot (
    fixture_id INTEGER NOT NULL, league TEXT, match_date TEXT, market_code TEXT NOT NULL, pick_label TEXT, pick_pct REAL,
    computed_at TEXT, model_version TEXT, PRIMARY KEY (fixture_id, market_code))"""


def save_snapshot(fixture_id, league, match_date, items, version):
    """Заменя стойностите на мача в extra_markets_snapshot (+ log_first). Никога не хвърля."""
    if not items:
        return
    try:
        con = sqlite3.connect(DB_PATH, timeout=30)
        try:
            con.execute("PRAGMA busy_timeout=30000")
            con.execute(DDL_SNAPSHOT)
            now = datetime.now().isoformat()
            con.execute("DELETE FROM extra_markets_snapshot WHERE fixture_id=?", (fixture_id,))
            con.executemany("INSERT INTO extra_markets_snapshot (fixture_id, league, match_date, market_code, pick_label, pick_pct, computed_at, "
                            "model_version) VALUES (?,?,?,?,?,?,?,?)",
                            [(fixture_id, league, match_date, c, l, float(p), now, version) for c, l, p in items])
            con.execute("DELETE FROM extra_markets_snapshot WHERE match_date < date('now', '-2 day')")
            con.commit()
        finally:
            con.close()
    except Exception:
        pass
    log_first(fixture_id, league, match_date, items, version)


def rows_for_fixture(fixture_id):
    """Редовете на мача във формата на predictions_snapshot (market_code, pick_pct, ...) или [] (изключено/няма/грешка)."""
    if not enabled():
        return []
    try:
        con = sqlite3.connect("file:" + DB_PATH + "?mode=ro", uri=True, timeout=10)
        try:
            cur = con.execute("SELECT fixture_id, league, match_date, market_code, pick_label, pick_pct, computed_at, model_version "
                              "FROM extra_markets_snapshot WHERE fixture_id=?", (int(fixture_id),))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            con.close()
    except Exception:
        return []


def log_first(fixture_id, league, match_date, items, version):
    """Първата стойност на мач и пазар -> extra_markets_log (само добавяне). Никога не хвърля."""
    if not items:
        return
    try:
        con = sqlite3.connect(DB_PATH, timeout=30)
        try:
            con.execute("PRAGMA busy_timeout=30000")
            con.execute("""CREATE TABLE IF NOT EXISTS extra_markets_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, logged_at TEXT NOT NULL, fixture_id INTEGER NOT NULL, league TEXT,
                match_date TEXT, market_code TEXT NOT NULL, pick_pct REAL, model_version TEXT, UNIQUE(fixture_id, market_code))""")
            now = datetime.utcnow().isoformat(timespec="seconds")
            con.executemany("INSERT OR IGNORE INTO extra_markets_log (logged_at, fixture_id, league, match_date, market_code, pick_pct, model_version) "
                            "VALUES (?,?,?,?,?,?,?)", [(now, fixture_id, league, match_date, c, round(p, 4), version) for c, _l, p in items])
            con.commit()
        finally:
            con.close()
    except Exception:
        pass
