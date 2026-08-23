import os
import pickle
import threading
import time
import subprocess
import glob
import shutil
import tarfile
import io
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, render_template_string, render_template, redirect, url_for, copy_current_request_context, send_file
import numpy as np
import pandas as pd
import requests
from datetime import date, timedelta, datetime
from scipy.stats import poisson
import football_lib as fl
from production_pipeline import fit_ht_2h_models, predict_ht_ft
from bg_names import to_cyrillic
import bets_tracker as bt
import player_props as pp
import system_tracker as st
import prediction_policy as policy
import pick_selection as ps
import evaluation

app = Flask(__name__)

app.secret_key = "a83f19d7c2b04e6f9a1d5c8b3e7f2a90c4d61be0f51273a9"
app.permanent_session_lifetime = timedelta(days=30)
LOGIN_PASSWORD = "anton20"
REFRESH_TOKEN = "f6d2a9c7e1b84a3f9c05e2d7a1b6f4e8"

@app.route("/login", methods=["GET", "POST"])
def login():
    from flask import session
    if request.method == "POST":
        if request.form.get("password") == LOGIN_PASSWORD:
            session.permanent = True
            session["authed"] = True
            next_url = request.args.get("next") or "/"
            return redirect(next_url)
        return render_template("login.html", error=True)
    return render_template("login.html", error=False)


@app.before_request
def require_auth():
    from flask import session
    if request.endpoint == "login" or request.path.startswith("/static"):
        return
    # 23.08.2026, rate limit стъпка 3/4: /refresh_all влиза в същия списък,
    # за да може новата нощна задача (incremental-refresh.timer, 04:00,
    # виж CLAUDE_HANDOFF.md) да го вика през curl+токен, по образец на
    # refresh-odds.timer - вика ЖИВИЯ Flask процес (не отделен скрипт,
    # който да пресъздава _refresh_state в нов процес), значи минава през
    # СЪЩОТО заключване (_try_start_refresh) като ръчния бутон.
    #
    # Хотфикс в СЪЩОТО изменение: старият код тук правеше БЕЗУСЛОВЕН
    # redirect към /login, ако токенът липсва/не съвпада - това щеше да
    # счупи истинските бутони в интерфейса (/refresh_all се вика директно
    # от index.html/leagues_admin.html с реална сесийна бисквитка, БЕЗ
    # токен). Сега: без токен просто пада през към обичайната сесийна
    # проверка по-долу, вместо да пресича достъпа предварително.
    if request.path in ("/refresh_odds_cache", "/refresh_injuries_cache", "/refresh_all"):
        if request.headers.get("X-Refresh-Token") == REFRESH_TOKEN:
            return
    if not session.get("authed"):
        return redirect(url_for("login", next=request.path))


from api_football import API_KEY, BASE_URL, API_HEADERS, FINISHED_STATUSES, fetch_fixture_predictions, fetch_fixture_odds, fetch_lineups_available, fetch_fixture_injuries, fetch_fixture_lineups_full, fetch_team_recent_form, fetch_league_standings_for_teams, DAYS_AHEAD, fetch_upcoming_fixtures, fetch_fixture_id_for_today

# лиги, за които контузиите ДОКАЗАНО НЕ подобряват модела (тествано и отхвърлено)
NO_INJURY_MODEL_LEAGUES = {"champions_league", "europa_league"}

ALL_LEAGUES = {
    "bulgaria": {"name": "Първа лига България", "id": 172},
    "england": {"name": "Английска Висша лига", "id": 39},
    "germany": {"name": "Бундеслига", "id": 78},
    "spain": {"name": "Ла Лига", "id": 140},
    "france": {"name": "Лига 1 Франция", "id": 61},
    "champions_league": {"name": "Шампионска лига", "id": 2},
    "europa_league": {"name": "Лига Европа", "id": 3},
    "conference_league": {"name": "Лига на конференциите", "id": 848},
    "italy": {"name": "Серия А Италия", "id": 135},
    "portugal": {"name": "Примейра Лига Португалия", "id": 94},
    "france2": {"name": "Франция - Лига 2", "id": 62},
    "spain2": {"name": "Испания - Сегунда Дивисион", "id": 141},
    "italy2": {"name": "Италия - Серия Б", "id": 136},
    "portugal2": {"name": "Португалия - Сегунда Лига", "id": 95},
    "bulgaria2": {"name": "България - Втора лига", "id": 173},
    "england2": {"name": "Англия - Чемпиъншип", "id": 40},
    "germany2": {"name": "Германия - Втора Бундеслига", "id": 79},
}

LEAGUE_FLAGS = {
    "bulgaria": "🇧🇬", "england": "🏴", "germany": "🇩🇪", "spain": "🇪🇸", "france": "🇫🇷",
    "champions_league": "🏆", "europa_league": "🏆", "conference_league": "🏆",
    "italy": "🇮🇹", "portugal": "🇵🇹",
    "france2": "🇫🇷", "spain2": "🇪🇸", "italy2": "🇮🇹", "portugal2": "🇵🇹", "bulgaria2": "🇧🇬",
    "england2": "🏴", "germany2": "🇩🇪",
}
LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "INT", "LIVE"}

MARKET_LABELS = {
    "home_win": "Домакин печели", "draw": "Равен", "away_win": "Гост печели",
    "over25": "Над 2.5 гола", "under25": "Под 2.5 гола",
    "btts_yes": "Двата отбора отбелязват - Да", "btts_no": "Двата отбора отбелязват - Не",
    "home_over15": "Домакин над 1.5 гола", "home_under15": "Домакин под 1.5 гола",
    "away_over15": "Гост над 1.5 гола", "away_under15": "Гост под 1.5 гола",
    "home_clean_sheet": "Домакин чиста мрежа", "away_clean_sheet": "Гост чиста мрежа",
    "dc_1x": "Двоен шанс 1X", "dc_x2": "Двоен шанс X2", "dc_12": "Двоен шанс 12",
    "corners_home_over_4.5": "Домакин над 4.5 корнера", "corners_away_over_4.5": "Гост над 4.5 корнера",
    "corners_total_over_9.5": "Над 9.5 корнера общо", "corners_total_under_9.5": "Под 9.5 корнера общо",
    "cards_total_over_3.5": "Над 3.5 картона общо", "cards_total_under_3.5": "Под 3.5 картона общо",
    "offsides_total_over_3.5": "Над 3.5 засади общо", "offsides_total_under_3.5": "Под 3.5 засади общо",
}
_HTFT_LABELS = {"1": "Домакин", "X": "Равен", "2": "Гост"}


def market_label(code):
    if code in MARKET_LABELS:
        return MARKET_LABELS[code]
    if code.startswith("htft:"):
        ht, ft = code.split(":")[1].split("/")
        return f"Полувреме/Край: {_HTFT_LABELS.get(ht, ht)}/{_HTFT_LABELS.get(ft, ft)}"
    return code


ACTIVE_LEAGUES_FILE = "active_leagues.json"


ACTIVE_LEAGUES_COOKIE = "active_leagues"


def load_active_leagues():
    cookie_val = request.cookies.get(ACTIVE_LEAGUES_COOKIE)
    if cookie_val:
        selected = [k for k in cookie_val.split(",") if k in ALL_LEAGUES]
        if selected:
            return selected
    return list(ALL_LEAGUES.keys())
    with open(ACTIVE_LEAGUES_FILE, "w") as f:
        json.dump(active_list, f)


def get_leagues():
    active = load_active_leagues()
    return {k: v["name"] for k, v in ALL_LEAGUES.items() if k in active}


def get_league_ids():
    active = load_active_leagues()
    return {k: v["id"] for k, v in ALL_LEAGUES.items() if k in active}

FORM_WINDOW_DAYS = 90

_model_cache = {}


MODEL_CACHE_DIR = "model_cache"
os.makedirs(MODEL_CACHE_DIR, exist_ok=True)


def get_models(league):
    if league not in _model_cache:
        csv_path = f"{league}_merged_full.csv"
        cache_path = os.path.join(MODEL_CACHE_DIR, f"{league}.pkl")

        if os.path.exists(cache_path) and os.path.exists(csv_path):
            if os.path.getmtime(cache_path) > os.path.getmtime(csv_path):
                try:
                    with open(cache_path, "rb") as cf:
                        _model_cache[league] = pickle.load(cf)
                    return _model_cache[league]
                except Exception:
                    pass

        df = fl.load_league_data(league)
        teams, n, team_idx = fl.get_team_index(df)
        ref_date = df["date"].max()
        league_xi = fl.LEAGUE_XI.get(league, fl.XI)
        has_injuries = ("home_injuries" in df.columns) and (league not in NO_INJURY_MODEL_LEAGUES)
        if has_injuries:
            ft_model = fl.fit_goals_direct_covariate(df, ref_date, team_idx, n, "home_injuries", "away_injuries", xi=league_xi)
        else:
            ft_model = fl.fit_goals_model(df, ref_date, team_idx, n, xi=league_xi)
        ht_model, h2_model = fit_ht_2h_models(df, team_idx, n)
        recent_cutoff = ref_date - pd.Timedelta(days=FORM_WINDOW_DAYS)
        recent_df = df[df["date"] >= recent_cutoff]
        recent_matches_count = len(recent_df)
        recent_model = fl.fit_goals_model(recent_df, ref_date, team_idx, n, xi=league_xi) if recent_matches_count >= 20 else None
        if "home_yellow" in df.columns:
            df["home_cards_total"] = df["home_yellow"].fillna(0) + df.get("home_red", pd.Series(0, index=df.index)).fillna(0)
            df["away_cards_total"] = df["away_yellow"].fillna(0) + df.get("away_red", pd.Series(0, index=df.index)).fillna(0)
        corners_model = fl.fit_total_model(df, ref_date, team_idx, n, "home_corners", "away_corners", xi=league_xi) if "home_corners" in df.columns else None
        cards_model = fl.fit_total_model(df, ref_date, team_idx, n, "home_cards_total", "away_cards_total", xi=league_xi) if "home_yellow" in df.columns else None
        offsides_model = fl.fit_total_model(df, ref_date, team_idx, n, "home_offsides", "away_offsides", xi=league_xi) if "home_offsides" in df.columns else None
        _model_cache[league] = (teams, team_idx, ft_model, ht_model, h2_model,
                                  corners_model, cards_model, offsides_model,
                                  recent_model, recent_matches_count, has_injuries)

        try:
            with open(cache_path, "wb") as cf:
                pickle.dump(_model_cache[league], cf)
        except Exception as e:
            print(f"  Предупреждение - не успях да запазя диск кеша за {league}: {e}")

    return _model_cache[league]
    return _model_cache[league]


def get_ft_lambdas(ft_model, team_idx, home, away, home_inj=0, away_inj=0):
    if ft_model.get("direct_covariate"):
        return fl.get_lambdas_direct(ft_model, team_idx, home, away, home_inj, away_inj)
    return fl.get_lambdas(ft_model, team_idx, home, away)


def fair_odds(pct):
    if pct <= 0:
        return None
    return round(100 / pct, 2)


BLEND_WEIGHT = 0.5  # Нощна сесия 24.08.2026: старият коментар тук ("бектест на 6 лиги")
# нямаше файл зад себе си (виж CLAUDE_HANDOFF.md) - подменен с реален, committed бектест:
# validation/blend_vs_raw_backtest_20260824.py/csv (475 уредени наблюдения) +
# validation/blend_vs_raw_significance_20260824.py/txt (paired bootstrap значимост).
# Извод: за 1X2+O/У 2.5 (пазарите, за които изобщо има market_odds) смесеното число
# е статистически значимо по-точно от чистия модел (95% CI изключва нулата, и в Brier,
# и в log-loss) - не само точкова оценка. Затова смесеното е авторитетното число
# НАВСЯКЪДЕ по сайта за тези пазари (виж _blend_with_market по-долу), не само на /daily.

MIN_VALUE_BET_PROB = 0.35  # филтър: не показвай value bet под тази наша вероятност
MAX_VALUE_BET_ODDS = 5.0   # филтър: не показвай value bet над този коефициент
KELLY_FRACTION = 0.25      # дробен Kelly (25% от пълния, за защита срещу несигурност на модела)
# Фаза N.1 (11.08.2026): наблюдавано на живо - моделът даде 44.7% на ЦСКА 1948
# срещу пазарни 21.8% (EV +90%), докато вградената прогноза на API-Football
# даваше 10%. Ликвиден европейски пазар не греши така. Над този праг приемаме,
# че греши НАШИЯТ модел, не пазарът, и не препоръчваме залог - вместо това
# показваме предупреждение (виж distrusted_bets в compute_grouped_markets).
MAX_TRUSTWORTHY_EV = 0.40  # 40% - над това не вярваме на модела си


def devig_1x2(h_odds, d_odds, a_odds):
    ih, idr, ia = 1 / h_odds, 1 / d_odds, 1 / a_odds
    total = ih + idr + ia
    return ih / total, idr / total, ia / total


def devig_ou(over_odds, under_odds):
    io, iu = 1 / over_odds, 1 / under_odds
    total = io + iu
    return io / total, iu / total


def _blend_with_market(home_win, draw, away_win, ou_p, market_odds):
    """Смесва чист модел с обезвигован пазар (BLEND_WEIGHT), само за
    home_win/draw/away_win/over25/under25 - точно пазарите, за които
    /daily вече прилага същото смесване (_raw_candidates по-долу) и за
    които бектестът (validation/blend_vs_raw_*_20260824.*) показва
    статистически значимо подобрение. Без пазарен коефициент за дадена
    група - връща стойностите непроменени (чист модел)."""
    if market_odds and market_odds.get("home_win") and market_odds.get("draw") and market_odds.get("away_win"):
        try:
            mh, md, ma = devig_1x2(market_odds["home_win"], market_odds["draw"], market_odds["away_win"])
            home_win = BLEND_WEIGHT * mh + (1 - BLEND_WEIGHT) * home_win
            draw = BLEND_WEIGHT * md + (1 - BLEND_WEIGHT) * draw
            away_win = BLEND_WEIGHT * ma + (1 - BLEND_WEIGHT) * away_win
        except (ZeroDivisionError, TypeError):
            pass
    if market_odds and market_odds.get("over25") and market_odds.get("under25"):
        try:
            mo, mund = devig_ou(market_odds["over25"], market_odds["under25"])
            ou_p = BLEND_WEIGHT * mo + (1 - BLEND_WEIGHT) * ou_p
        except (ZeroDivisionError, TypeError):
            pass
    return home_win, draw, away_win, ou_p


def _raw_candidates(lam, mu, home, away, ht_ft_probs, market_odds=None, rho=0.0):
    """Суровите candidates (label, prob_0_1, code) от Poisson + пазарен
    blend - БЕЗ policy филтриране/дедупликация/класиране. Тази логика вече
    е в pick_selection.py (Фаза I.1), за да не се разминава между
    top_pick_with_code(), top_picks_with_code() и index_home().

    rho: Фаза K.1 (20.08.2026) - Dixon-Coles параметър от ft_model["rho"],
    подаден от викащия. 0.0 (по подразбиране) = без корекция, старо
    поведение точно."""
    max_g = 10
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    if rho:
        pm = fl.dc_adjust_matrix(pm, lam, mu, rho)
    home_win = np.sum(np.tril(pm, -1))
    draw = np.sum(np.diag(pm))
    away_win = np.sum(np.triu(pm, 1))
    _, ou_p = fl.btts_ou_probs(lam, mu, rho=rho)
    extra = fl.extra_markets_probs(lam, mu, rho=rho)
    best_htft = max(ht_ft_probs.items(), key=lambda x: x[1])

    home_win, draw, away_win, ou_p = _blend_with_market(home_win, draw, away_win, ou_p, market_odds)
    used_market = bool(market_odds and (
        (market_odds.get("home_win") and market_odds.get("draw") and market_odds.get("away_win")) or
        (market_odds.get("over25") and market_odds.get("under25"))
    ))

    home_cy, away_cy = to_cyrillic(home), to_cyrillic(away)
    candidates = [
        (f"{home_cy} печели", home_win, "home_win"),
        ("Равен", draw, "draw"),
        (f"{away_cy} печели", away_win, "away_win"),
        ("Над 2.5 гола", ou_p, "over25"),
        ("Под 2.5 гола", 1 - ou_p, "under25"),
        (f"{home_cy} над 1.5 гола", extra["home_over15"], "home_over15"),
        (f"{home_cy} под 1.5 гола", 1 - extra["home_over15"], "home_under15"),
        (f"Резултат почивка/край {best_htft[0]}", best_htft[1], f"htft:{best_htft[0]}"),
    ]
    return candidates, used_market


def top_pick_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=None, rho=0.0):
    candidates, used_market = _raw_candidates(lam, mu, home, away, ht_ft_probs, market_odds, rho=rho)
    label, pct, code = ps.rank_candidates(candidates, league, policy, n=1)[0]
    return label, pct, code, used_market


def top_picks_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=None, n=3, rho=0.0):
    """Топ N picks (Фаза F3) - сега през каноничния
    pick_selection.rank_candidates() (Фаза I.1) вместо собствена копирана
    fallback/дедупликационна логика. НОВО спрямо преди Фаза I.1: вече
    отхвърля и тук >=95% кандидати (pick_selection.MAX_PUBLISHABLE_PCT) -
    съзнателна унификация, виж claude/ACTION_PLAN.md Фаза I.1."""
    candidates, used_market = _raw_candidates(lam, mu, home, away, ht_ft_probs, market_odds, rho=rho)
    ranked = ps.rank_candidates(candidates, league, policy, n=n)
    return ranked, used_market


def _market_info_for_pick(code, market_odds):
    """Обезвигована пазарна вероятност + коефициент за market_code, ако
    market_odds има пълна двойка/тройка за него - иначе None (пазарът не
    покрива този код, напр. home_over15/htft:*, или липсва данни за мача)."""
    if not market_odds:
        return None
    try:
        if code in ("home_win", "draw", "away_win") and market_odds.get("home_win") and market_odds.get("draw") and market_odds.get("away_win"):
            mh, md, ma = devig_1x2(market_odds["home_win"], market_odds["draw"], market_odds["away_win"])
            return {"home_win": (mh, market_odds["home_win"]), "draw": (md, market_odds["draw"]),
                    "away_win": (ma, market_odds["away_win"])}.get(code)
        if code in ("over25", "under25") and market_odds.get("over25") and market_odds.get("under25"):
            mo, mund = devig_ou(market_odds["over25"], market_odds["under25"])
            return {"over25": (mo, market_odds["over25"]), "under25": (mund, market_odds["under25"])}.get(code)
    except (ZeroDivisionError, TypeError):
        return None
    return None


def build_pick_card(picks, market_odds):
    """Задача 5 (нощна сесия 24.08.2026): картата на /daily - най-много два
    реда вместо предишните до три чипа. `picks` е списъкът вече ДОВЕРЕНИ
    (policy-eligible, минали през pick_selection.rank_candidates) кандидати
    за мача - label/pct/code/odds, идентична структура и в живия, и в
    snapshot пътя. `market_odds` са кешираните пазарни коефициенти (или
    None/непълни).

    'Стойностен' = най-висок EV сред кандидатите, за които изобщо има
    пазарна цена (home_win/draw/away_win/over25/under25 - единствените с
    market_odds), със СЪЩИТЕ прагове като value_bets в
    compute_grouped_markets (MIN_VALUE_BET_PROB/MAX_VALUE_BET_ODDS/
    MAX_TRUSTWORTHY_EV) - непроменени тук, само преизползвани.
    'Сигурен' = най-висока вероятност сред ВСИЧКИ доверени кандидати
    (включително пазари без пазарна цена - идентично на старата top pick).
    Ако съвпадат - `same=True`, показва се само един ред. Ако никой доверен
    кандидат няма положителен EV - `value=None`. `has_market_odds=False`
    означава че за мача изобщо няма кеширан пазарен коефициент."""
    if not picks:
        return None

    def make_row(p):
        info = _market_info_for_pick(p["code"], market_odds)
        if not info:
            return {"label": p["label"], "our_pct": p["pct"], "market_pct": None, "odd": None, "ev": None}
        market_p, odd = info
        ev = (p["pct"] / 100 * odd - 1) * 100
        return {"label": p["label"], "our_pct": p["pct"], "market_pct": market_p * 100, "odd": odd, "ev": ev}

    confident = max(picks, key=lambda p: p["pct"])
    has_market_odds = bool(market_odds and (
        (market_odds.get("home_win") and market_odds.get("draw") and market_odds.get("away_win")) or
        (market_odds.get("over25") and market_odds.get("under25"))
    ))

    best_value, best_ev = None, None
    for p in picks:
        info = _market_info_for_pick(p["code"], market_odds)
        if not info:
            continue
        market_p, odd = info
        our_p = p["pct"] / 100
        if our_p <= market_p or our_p < MIN_VALUE_BET_PROB or odd > MAX_VALUE_BET_ODDS:
            continue
        ev = our_p * odd - 1
        if ev > MAX_TRUSTWORTHY_EV:
            continue
        if best_ev is None or ev > best_ev:
            best_value, best_ev = p, ev

    confident_row = make_row(confident)
    if best_value is None:
        return {"confident": confident_row, "value": None, "same": False, "has_market_odds": has_market_odds}
    value_row = make_row(best_value)
    return {"confident": confident_row, "value": value_row,
            "same": best_value["code"] == confident["code"], "has_market_odds": has_market_odds}


def compute_grouped_markets(league, home, away, home_inj=0, away_inj=0, real_odds=None):
    (teams, team_idx, ft_model, ht_model, h2_model,
     corners_model, cards_model, offsides_model,
     recent_model, recent_matches_count, has_injuries) = get_models(league)

    if home not in team_idx or away not in team_idx:
        return None, None

    lam, mu = get_ft_lambdas(ft_model, team_idx, home, away, home_inj, away_inj)
    lam_ht, mu_ht = fl.get_lambdas(ht_model, team_idx, home, away)
    lam_2h, mu_2h = fl.get_lambdas(h2_model, team_idx, home, away)
    # Фаза K.1 (20.08.2026): Dixon-Coles rho, фитнат в fit_goals_model()
    # (ft_model["rho"] е 0.0 за модели трениран със старото use_dc=False,
    # т.е. и за fit_goals_direct_covariate() моделите - виж bel.).
    rho_ft = ft_model.get("rho", 0.0)

    max_g = 10

    def probs_1x2_ou(l, m, rho=0.0):
        pm = np.outer(poisson.pmf(range(max_g), l), poisson.pmf(range(max_g), m))
        if rho:
            pm = fl.dc_adjust_matrix(pm, l, m, rho)
        hw = np.sum(np.tril(pm, -1))
        dr = np.sum(np.diag(pm))
        aw = np.sum(np.triu(pm, 1))
        btts_p, ou_p = fl.btts_ou_probs(l, m, rho=rho)
        return hw, dr, aw, btts_p, ou_p

    home_win, draw, away_win, btts_p, ou_p = probs_1x2_ou(lam, mu, rho=rho_ft)
    # Задача 2 (нощна сесия 24.08.2026): смесеното число (модел+пазар) е
    # статистически значимо по-точно за home_win/draw/away_win/over25/under25
    # (validation/blend_vs_raw_significance_20260824.txt) - огледално на /daily,
    # прилага се тук на главната таблица И на value_bets/EV/Kelly по-долу
    # (и двете четат същите home_win/draw/away_win/ou_p променливи). Без
    # real_odds за дадена група - непроменено, чист модел.
    home_win, draw, away_win, ou_p = _blend_with_market(home_win, draw, away_win, ou_p, real_odds)
    extra = fl.extra_markets_probs(lam, mu, rho=rho_ft)
    ht_ft_probs = predict_ht_ft(lam_ht, mu_ht, lam_2h, mu_2h)

    form_data = None
    if recent_model:
        lam_r, mu_r = fl.get_lambdas(recent_model, team_idx, home, away)
        rho_recent = recent_model.get("rho", 0.0)
        hw_r, dr_r, aw_r, _, ou_r = probs_1x2_ou(lam_r, mu_r, rho=rho_recent)
        form_data = {"home_win": hw_r * 100, "draw": dr_r * 100, "away_win": aw_r * 100,
                      "over25": ou_r * 100, "under25": (1 - ou_r) * 100, "n": recent_matches_count}

    top_label, top_pct, top_code, _ = top_pick_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=None, rho=rho_ft)
    home_cy, away_cy = to_cyrillic(home, league), to_cyrillic(away, league)

    groups = []
    groups.append(("1X2 и двойни шансове", [
        (f"{home_cy} печели", home_win * 100, form_data["home_win"] if form_data else None, "home_win"),
        ("Равен", draw * 100, form_data["draw"] if form_data else None, "draw"),
        (f"{away_cy} печели", away_win * 100, form_data["away_win"] if form_data else None, "away_win"),
        ("Двоен шанс 1X", (home_win + draw) * 100, None, "dc_1x"),
        ("Двоен шанс X2", (draw + away_win) * 100, None, "dc_x2"),
        ("Двоен шанс 12", (home_win + away_win) * 100, None, "dc_12"),
    ], True))

    groups.append(("Общо голове", [
        ("Над 2.5 гола", ou_p * 100, form_data["over25"] if form_data else None, "over25"),
        ("Под 2.5 гола", (1 - ou_p) * 100, form_data["under25"] if form_data else None, "under25"),
        ("BTTS - Да", btts_p * 100, None, "btts_yes"),
        ("BTTS - Не", (1 - btts_p) * 100, None, "btts_no"),
    ], True))

    groups.append(("Голове по отбор", [
        (f"{home_cy} над 1.5 гола", extra["home_over15"] * 100, None, "home_over15"),
        (f"{home_cy} под 1.5 гола", (1 - extra["home_over15"]) * 100, None, "home_under15"),
        (f"{away_cy} над 1.5 гола", extra["away_over15"] * 100, None, "away_over15"),
        (f"{away_cy} под 1.5 гола", (1 - extra["away_over15"]) * 100, None, "away_under15"),
        (f"{home_cy} чиста мрежа", extra["home_clean_sheet"] * 100, None, "home_clean_sheet"),
        (f"{away_cy} чиста мрежа", extra["away_clean_sheet"] * 100, None, "away_clean_sheet"),
    ], False))

    groups.append(("Полувреме / край", [
        (f"Резултат {outcome}", prob * 100, None, f"htft:{outcome}")
        for outcome, prob in sorted(ht_ft_probs.items(), key=lambda x: -x[1])[:4]
    ], False))

    if corners_model:
        lam_c, mu_c = fl.get_lambdas(corners_model, team_idx, home, away)
        over_total = fl.total_ou_prob(lam_c, mu_c, 9.5)
        over_home = 1 - poisson.cdf(4, lam_c)
        over_away = 1 - poisson.cdf(4, mu_c)
        groups.append(("Корнери ⚠️", [
            (f"Общо над 9.5 (~{lam_c+mu_c:.1f})", over_total * 100, None, "corners_total_over_9.5"),
            ("Общо под 9.5", (1 - over_total) * 100, None, "corners_total_under_9.5"),
            (f"{home_cy} над 4.5 корнера (~{lam_c:.1f})", over_home * 100, None, "corners_home_over_4.5"),
            (f"{away_cy} над 4.5 корнера (~{mu_c:.1f})", over_away * 100, None, "corners_away_over_4.5"),
        ], False))

    if cards_model:
        lam_cd, mu_cd = fl.get_lambdas(cards_model, team_idx, home, away)
        over_cd = fl.total_ou_prob(lam_cd, mu_cd, 3.5)
        groups.append(("Картони ⚠️", [
            (f"Общо над 3.5 (~{lam_cd+mu_cd:.1f})", over_cd * 100, None, "cards_total_over_3.5"),
            ("Общо под 3.5", (1 - over_cd) * 100, None, "cards_total_under_3.5"),
        ], False))

    if offsides_model:
        lam_o, mu_o = fl.get_lambdas(offsides_model, team_idx, home, away)
        over_o = fl.total_ou_prob(lam_o, mu_o, 3.5)
        groups.append(("Засади ⚠️", [
            (f"Общо над 3.5 (~{lam_o+mu_o:.1f})", over_o * 100, None, "offsides_total_over_3.5"),
            ("Общо под 3.5", (1 - over_o) * 100, None, "offsides_total_under_3.5"),
        ], False))

    for i, (title, items, has_form) in enumerate(groups):
        groups[i] = (title, sorted(items, key=lambda x: -x[1]), has_form)

    form_note = (f"Форма от {recent_matches_count} мача в последните {FORM_WINDOW_DAYS} дни"
                 if recent_model else f"Недостатъчно скорошни мачове ({recent_matches_count})")
    if has_injuries:
        form_note += f" | Контузии: {home_cy} {home_inj}, {away_cy} {away_inj} (модел отчита контузии)"
    else:
        form_note += " | Няма данни за контузии за тази лига"

    value_bets = []
    distrusted_bets = []
    if real_odds:
        candidates = []
        if real_odds.get("home_win") and real_odds.get("draw") and real_odds.get("away_win"):
            try:
                mh, md, ma = devig_1x2(real_odds["home_win"], real_odds["draw"], real_odds["away_win"])
                candidates.append((f"{home_cy} печели", home_win, mh, real_odds["home_win"], "home_win"))
                candidates.append(("Равен", draw, md, real_odds["draw"], "draw"))
                candidates.append((f"{away_cy} печели", away_win, ma, real_odds["away_win"], "away_win"))
            except (ZeroDivisionError, TypeError):
                pass
        if real_odds.get("over25") and real_odds.get("under25"):
            try:
                mo, mund = devig_ou(real_odds["over25"], real_odds["under25"])
                candidates.append(("Над 2.5 гола", ou_p, mo, real_odds["over25"], "over25"))
                candidates.append(("Под 2.5 гола", 1 - ou_p, mund, real_odds["under25"], "under25"))
            except (ZeroDivisionError, TypeError):
                pass
        for label, our_p, market_p, odd, code in candidates:
            edge = (our_p - market_p) * 100
            if edge <= 0:
                continue
            if our_p < MIN_VALUE_BET_PROB:
                continue
            if odd > MAX_VALUE_BET_ODDS:
                continue
            ev = (our_p * odd) - 1
            # Фаза N.1 (11.08.2026): EV над прага не се доверяваме на модела -
            # вместо препоръка за залог, показваме предупреждение (виж
            # distrusted_bets по-долу и MAX_TRUSTWORTHY_EV константата).
            if ev > MAX_TRUSTWORTHY_EV:
                distrusted_bets.append({"label": label, "our_pct": our_p * 100,
                                         "market_pct": market_p * 100, "ev": ev * 100})
                continue
            kelly_full = (our_p * odd - 1) / (odd - 1) if odd > 1 else 0
            kelly_stake = max(0, kelly_full) * KELLY_FRACTION * 100
            value_bets.append({"label": label, "our_pct": our_p * 100, "market_pct": market_p * 100,
                                 "edge": edge, "odd": odd, "code": code, "ev": ev * 100, "kelly_stake": kelly_stake})
        value_bets.sort(key=lambda x: -x["ev"])

    return groups, (lam, mu, top_label, top_pct, form_note, value_bets, distrusted_bets)


BASE_STYLE = """
  :root {
    --bg:#0f1115; --panel:#171a21; --panel2:#1d212b; --sidebar-bg:#12141a; --border:#2a2f3a;
    --text:#e8eaed; --sub:#8b93a3; --accent:#3b82f6;
    --green:#22c55e; --green-bg:#16311f; --yellow:#eab308; --yellow-bg:#332a10;
    --grey:#5b6473; --live:#ef4444; --red:#ef4444;
  }
  body { font-family: -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 24px; }
  .container { max-width: 680px; margin: 0 auto; }
  h1 { font-size: 20px; font-weight: 500; margin-bottom: 12px; color: var(--text); }
  .nav { margin-bottom: 20px; }
  .nav a { color: var(--accent); text-decoration: none; font-size: 13px; margin-right: 16px; }
  form.filter { background: var(--panel2); border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid var(--border); }
  select, button { width: 100%; padding: 10px; margin-bottom: 10px; font-size: 14px;
                    border-radius: 8px; border: 1px solid var(--border); box-sizing: border-box; }
  select { background: var(--panel2); color: var(--text); }
  button { background: var(--accent); color: white; border: none; cursor: pointer; font-weight: 500; }
  button:hover { background: #2563eb; }
  button.small { width: auto; padding: 6px 14px; font-size: 12px; }
  button.green { background: var(--green); }
  .top-pick { background: var(--green-bg); border: 1px solid rgba(34,197,94,0.35); border-radius: 12px; padding: 16px 20px; margin-bottom: 20px; }
  .top-pick-label { font-size: 12px; color: var(--green); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
  .top-pick-row { display: flex; justify-content: space-between; align-items: center; }
  .top-pick-name { font-size: 16px; font-weight: 500; color: var(--green); }
  .top-pick-pct { font-size: 22px; font-weight: 600; color: var(--green); }
  .lambdas { color: var(--sub); font-size: 13px; margin-bottom: 4px; }
  .form-note { color: var(--sub); font-size: 12px; margin-bottom: 16px; font-style: italic; }
  .group { margin-bottom: 16px; }
  .group-title { font-size: 12px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; padding-left: 4px; }
  table { width: 100%; border-collapse: collapse; background: var(--panel2); border-radius: 10px; overflow: hidden; border: 1px solid var(--border); }
  td, th { padding: 8px 14px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); }
  th { background: var(--panel); font-weight: 500; font-size: 11px; color: var(--sub); text-transform: uppercase; }
  td:not(:first-child), th:not(:first-child) { text-align: right; font-weight: 500; }
  tr:last-child td { border-bottom: none; }
  .form-col { color: var(--accent); }
  .match-card { background: var(--panel2); border: 1px solid var(--border); border-radius: 10px; padding: 9px 14px; margin-bottom: 6px; }
  .date-group-header { font-size:13px; font-weight:600; color:var(--sub); margin:20px 0 10px; padding-left:2px; }
  .match-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; gap: 10px; }
  .match-teams { font-size: 13px; font-weight: 500; line-height: 1.3; }
  .match-date { font-size: 10px; color: var(--sub); white-space: nowrap; }
  .match-pick-row { display: flex; justify-content: space-between; align-items: center; }
  .stats-row { display: flex; gap: 12px; margin-bottom: 20px; }
  .stat-box { flex: 1; background: var(--panel2); border-radius: 10px; padding: 14px; text-align: center; border: 1px solid var(--border); }
  .stat-value { font-size: 22px; font-weight: 600; }
  .stat-label { font-size: 11px; color: var(--sub); text-transform: uppercase; }
  .won { color: var(--green); } .lost { color: var(--red); } .pending { color: var(--sub); }
  .checkbox-row { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
  .inj-note { font-size: 11px; color: var(--sub); margin-top: 4px; }
"""

SIDEBAR_STYLE = """
  .sidebar { position: fixed; top:0; left:0; bottom:0; width:220px; background:var(--sidebar-bg); border-right:1px solid var(--border); padding:24px 0; overflow-y:auto; z-index:200; }
  .sidebar-logo { padding:0 20px 20px; font-size:16px; font-weight:600; color:var(--accent); }
  .sidebar-section { padding:16px 20px 6px; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#525a68; font-weight:700; }
  .sidebar a { display:flex; align-items:center; gap:10px; padding:10px 20px; color:var(--sub); text-decoration:none; font-size:13px; }
  .sidebar a.active { background:rgba(59,130,246,0.15); color:var(--accent); font-weight:500; border-right:3px solid var(--accent); }
  .sidebar a:hover { background:var(--panel2); }
  .sidebar-toggle { display:none; position:fixed; top:16px; left:16px; z-index:300; background:var(--panel2); color:var(--text); border:1px solid var(--border); border-radius:8px; width:40px; height:40px; align-items:center; justify-content:center; font-size:18px; cursor:pointer; }
  body { padding-left:244px; }
  @media (max-width: 860px) {
    .sidebar { transform:translateX(-100%); transition:transform 0.2s ease; box-shadow:4px 0 12px rgba(0,0,0,0.4); }
    .sidebar.open { transform:translateX(0); }
    .sidebar-toggle { display:flex; }
    body { padding-left:24px; padding-top:70px; }
  }
"""

SIDEBAR_HTML = """
<div class="sidebar-toggle" onclick="document.querySelector('.sidebar').classList.toggle('open')">☰</div>
<div class="sidebar">
  <a href="/" class="{% if active_page=='home' %}active{% endif %}">🏠 Начало</a>
  <div class="sidebar-section">Прогнози</div>
  <a href="/daily" class="{% if active_page=='daily' %}active{% endif %}">📅 Предстоящи</a>
  <a href="/value" class="{% if active_page=='value' %}active{% endif %}">💰 Стойност</a>
  <a href="/results" class="{% if active_page=='results' %}active{% endif %}">📋 Резултати и ефективност</a>
  <div class="sidebar-section">Инструменти</div>
  <a href="/manual" class="{% if active_page=='manual' %}active{% endif %}">🔍 Търсене</a>
  <div class="sidebar-section">Настройки</div>
  <a href="/leagues_admin" class="{% if active_page=='leagues_admin' %}active{% endif %}">⚙️ Лиги</a>
  <a href="/diagnostics" class="{% if active_page=='diagnostics' %}active{% endif %}">🔧 Диагностика</a>
</div>
"""


INJURY_LEAGUES = {"england", "germany", "spain", "france"}


def update_injuries_for_league(league_key, max_fixtures=60):
    csv_path = f"{league_key}_merged_full.csv"
    if not os.path.exists(csv_path):
        return 0, 0
    df = pd.read_csv(csv_path)
    if "home_injuries" not in df.columns:
        df["home_injuries"] = None
    if "away_injuries" not in df.columns:
        df["away_injuries"] = None
    missing = df[df["home_injuries"].isna()]
    checked = 0
    updated = 0
    for idx in missing.index:
        if checked >= max_fixtures:
            break
        fixture_id = df.at[idx, "fixture_id"]
        checked += 1
        try:
            r = requests.get(f"{BASE_URL}/injuries", headers=API_HEADERS,
                              params={"fixture": int(fixture_id)}, timeout=10)
            data = r.json()
            if data.get("errors") or not data.get("response"):
                df.at[idx, "home_injuries"] = 0
                df.at[idx, "away_injuries"] = 0
            else:
                home_count = 0
                away_count = 0
                home_team_id = None
                for inj in data["response"]:
                    if home_team_id is None:
                        home_team_id = inj["team"]["id"]
                    if inj["team"]["id"] == home_team_id:
                        home_count += 1
                    else:
                        away_count += 1
                df.at[idx, "home_injuries"] = home_count
                df.at[idx, "away_injuries"] = away_count
                updated += 1
        except Exception:
            pass
        time.sleep(0.3)
    df.to_csv(csv_path, index=False)
    return checked, updated


def run_refresh_all():
    import contextlib
    import io
    import incremental_refresh as ir

    with open("refresh_log.txt", "a", encoding="utf-8") as log_f:
        log_f.write(f"\n\n=== Опресняване стартирано: {__import__('datetime').datetime.now()} ===\n")

        for key, info in ALL_LEAGUES.items():
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    ir.main(key, info["id"])
            except Exception as e:
                buf.write(f"ГРЕШКА при {key}: {e}\n")

            output = buf.getvalue()
            log_f.write(output)
            log_f.flush()

            if "добавени" in output:
                _model_cache.pop(key, None)
                try:
                    get_models(key)
                    log_f.write(f"  {key}: моделът е презареден с новите данни.\n")
                except Exception as e:
                    log_f.write(f"  {key}: грешка при презареждане на модела: {e}\n")
                log_f.flush()

            if key in INJURY_LEAGUES:
                try:
                    checked, updated = update_injuries_for_league(key)
                    if checked:
                        log_f.write(f"  {key}: контузии - проверени {checked}, обновени {updated}.\n")
                except Exception as e:
                    log_f.write(f"  {key}: грешка при обновяване на контузии: {e}\n")
                log_f.flush()

        log_f.write("=== Опресняването приключи ===\n")
        log_f.write("=== Загряване на кеша за /daily (всички лиги) ===\n")
        log_f.flush()
        for key in ALL_LEAGUES.keys():
            try:
                _predict_matches_for_league(key, None, None)
                log_f.write(f"  {key}: загрят.\n")
            except Exception as e:
                log_f.write(f"  {key}: грешка при загряване: {e}\n")
            log_f.flush()
        log_f.write("=== Загряването приключи ===\n")


def _odds_needs_refresh(fixture_id, fixture_date_str, now):
    """Фаза J.1 (11.08.2026): преди тази промяна run_refresh_odds_cache()
    питаше API-то наново за ВСЕКИ мач в прозореца на ВСЕКИ run (на 30 мин),
    без значение колко скоро вече е проверен - fetched_at полето
    съществуваше в odds_cache, но не се четеше никъде. Тук се ползва:
    <24ч до началото -> опресни ако кешът е >25мин стар (почти всеки run);
    24ч-3дни -> >3ч стар; 3-7 дни -> >12ч стар. Пести квота при разширения
    прозорец (виж ACTION_PLAN.md Фаза J.1), без да жертва свежест близо до
    началото на мача, когато линията реално мърда."""
    cached = st.get_cached_odds(fixture_id)
    if not cached or not cached.get("fetched_at"):
        return True
    try:
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        age_minutes = (now - fetched_at).total_seconds() / 60
    except (ValueError, TypeError):
        return True
    try:
        kickoff = datetime.fromisoformat(fixture_date_str)
        hours_to_kickoff = (kickoff - datetime.now(kickoff.tzinfo)).total_seconds() / 3600
    except Exception:
        hours_to_kickoff = 0
    # 22.08.2026: 25/180/720 бяха твърде агресивни - задачата тръгва на
    # всеки 30 мин, а прагът от 25 мин за <24ч означаваше "опресни на
    # практика на всеки единствен цикъл", независимо дали коефициентът реално
    # се е променил. Реален разход от логовете: ~118 fetch_fixture_odds
    # извиквания на цикъл × 48 цикъла/ден ≈ 5700/ден само от тази функция -
    # 76% от дневния лимит от 7500. Разхлабено, за да остане запас за
    # проверка на резултати/контузии/реални посещения на страници (виж
    # CLAUDE_HANDOFF.md, раздел за API квотата, 22.08.2026).
    if hours_to_kickoff < 24:
        max_age = 90
    elif hours_to_kickoff < 72:
        max_age = 360
    else:
        max_age = 1440
    return age_minutes >= max_age


def run_refresh_odds_cache():
    from_date = date.today()
    # Фаза J.1: прозорецът беше today+2, а /daily показва до DAYS_AHEAD=7 -
    # мачове на 3-7 дни напред никога не получаваха коефициент, независимо
    # колко добре работеше самото опресняване (виж ACTION_PLAN.md Фаза J.1).
    to_date = date.today() + timedelta(days=DAYS_AHEAD)
    now = datetime.now()
    updated = 0
    checked = 0
    skipped_fresh = 0
    for key in ALL_LEAGUES.keys():
        try:
            fixtures, _ = fetch_upcoming_fixtures(key, from_date, to_date, use_cache=True)
        except Exception:
            continue
        for f in fixtures:
            fixture_id = f["fixture"]["id"]
            if not _odds_needs_refresh(fixture_id, f["fixture"]["date"], now):
                skipped_fresh += 1
                continue
            checked += 1
            try:
                odds = fetch_fixture_odds(fixture_id)
                if odds and (odds.get("home_win") or odds.get("over25")):
                    st.set_cached_odds(fixture_id, odds)
                    updated += 1
            except Exception:
                pass
    with open("odds_refresh_log.txt", "a", encoding="utf-8") as log_f:
        log_f.write(f"{datetime.now().isoformat()} - проверени {checked}, обновени {updated}, "
                     f"пропуснати(пресни) {skipped_fresh}\n")


def run_refresh_injuries_cache():
    """Фаза N.3 (20.08.2026): преди тази промяна injuries_cache се пълнеше
    само инцидентно, докато някой реално отваря /daily за конкретна лига
    (виж CLAUDE_HANDOFF.md N.3) - мачове, които никой не разгледа навреме,
    оставаха без кеширани контузии дори близо до началото. Тук - целенасочено
    опресняване за прозорец от 48 часа (по-тесен от 7-дневния на
    run_refresh_odds_cache(), защото контузийните новини са релевантни само
    близо до мача), за ВСИЧКИ лиги еднакво - контузиите тук са чисто
    информационни за /match_detail, не вход за модела (виж
    NO_INJURY_MODEL_LEAGUES/has_injuries - отделен, непроменен от това
    гейт). get_cached_injuries() вече връща None при изтекъл кеш (>6ч,
    виж system_tracker.py), затова просто пропускаме fixture-и с все още
    свеж кеш."""
    from_date = date.today()
    # 22.08.2026: прозорецът за самата обработка си остава 48ч (контузийните
    # новини са релевантни само близо до мача) - но ЗАЯВКАТА за списъка с
    # мачове сега пита за същия по-широк прозорец (today..+DAYS_AHEAD) като
    # run_refresh_odds_cache(), за да падне в СЪЩИЯ кеширан резултат
    # (fixture_list_cache е ключиран по точния (лига, from, to) диапазон) -
    # филтрираме до 48ч тук, на Python ниво, вместо да караме API-то да го
    # прави. Двете задачи тръгват последователно от един и същ cron скрипт
    # (refresh_odds_cron.sh), значи попадението в кеша е гарантирано, не
    # състезание между два отделни процеса.
    injuries_window_to = from_date + timedelta(days=2)
    to_date = from_date + timedelta(days=DAYS_AHEAD)
    checked = 0
    updated = 0
    for key in ALL_LEAGUES.keys():
        try:
            fixtures, _ = fetch_upcoming_fixtures(key, from_date, to_date, use_cache=True)
        except Exception:
            continue
        for f in fixtures:
            fixture_id = f["fixture"]["id"]
            try:
                f_date = datetime.fromisoformat(f["fixture"]["date"][:19])
            except (ValueError, TypeError, KeyError):
                continue
            if f_date > datetime.combine(injuries_window_to, datetime.min.time()):
                continue
            if st.get_cached_injuries(fixture_id) is not None:
                continue
            checked += 1
            try:
                home_inj, away_inj, ok = fetch_fixture_injuries(fixture_id)
                st.set_cached_injuries(fixture_id, home_inj, away_inj, ok)
                if ok:
                    updated += 1
            except Exception:
                pass
    with open("injuries_refresh_log.txt", "a", encoding="utf-8") as log_f:
        log_f.write(f"{datetime.now().isoformat()} - проверени(извикани API) {checked}, "
                     f"с намерени данни {updated}\n")


# Партида 8 (23.08.2026, rate limit на минута): преди тази промяна
# /refresh_all и /refresh_odds_cache_manual (бутоните на началната
# страница) стартираха нов threading.Thread при ВСЯКО натискане, без
# никаква проверка дали вече тече друго опресняване - ако неколцина души
# натиснат бутона по няколко пъти, се получаваха паралелни копия на
# run_refresh_all()/run_refresh_odds_cache(), всяко изстрелващо десетки
# некеширани заявки без пауза помежду им - точно това, комбинирано с
# 30-минутните фонови задачи, пробиваше лимита от 300 заявки/минута на
# API-Football (виж диагнозата в CLAUDE_HANDOFF.md).
#
# Заключването е ПО ВИД задача (all/odds/injuries), не общо за всичко:
# odds и injuries тръгват последователно от един и същ cron скрипт
# (refresh_odds_cron.sh) и вече разчитат, че могат да вървят едновременно
# - общ единствен флаг би блокирал injuries всеки път, докато odds още
# тече. Само ВТОРО извикване на СЪЩИЯ вид, докато първото не е приключило,
# се блокира. gunicorn тук е --workers 1 (виж CLAUDE_HANDOFF.md) - процесът
# е един, значи обикновен threading.Lock е достатъчен, не е нужна
# междупроцесна брава.
_REFRESH_KIND_LABELS = {
    "all": "всички лиги (нови мачове + модели)",
    "odds": "пазарни коефициенти",
    "injuries": "контузии",
}
_refresh_state = {
    "all": {"running": False, "started_at": None},
    "odds": {"running": False, "started_at": None},
    "injuries": {"running": False, "started_at": None},
}
_refresh_state_lock = threading.Lock()


def _try_start_refresh(kind, target):
    """Стартира target() във фонов thread, освен ако задача от СЪЩИЯ kind
    вече тече - тогава връща None и не прави нищо. Вика се от маршрутите в
    web/admin.py (двата бутона + двата cron endpoint-а)."""
    with _refresh_state_lock:
        if _refresh_state[kind]["running"]:
            return None
        _refresh_state[kind]["running"] = True
        _refresh_state[kind]["started_at"] = datetime.now().isoformat()

    def _wrapped():
        try:
            target()
        finally:
            with _refresh_state_lock:
                _refresh_state[kind]["running"] = False
                _refresh_state[kind]["started_at"] = None

    thread = threading.Thread(target=_wrapped, daemon=True)
    thread.start()
    return thread


def get_refresh_state():
    """За показване в интерфейса (index.html/leagues_admin.html) - кой вид
    опресняване тече в момента, ако изобщо тече."""
    with _refresh_state_lock:
        running_kinds = [k for k, v in _refresh_state.items() if v["running"]]
    if not running_kinds:
        return {"running": False, "label": None}
    return {"running": True, "label": ", ".join(_REFRESH_KIND_LABELS[k] for k in running_kinds)}


# Партида 3, довършване (21.08.2026, ARCHITECTURE.md): TTL кешът от И.3
# (300 сек, обвиваше сглобения резултат за лига+период - виж git история,
# commit-и de42ed4/4ee07c5, за пълния оригинален коментар) е премахнат.
# Причината, записана изрично в ARCHITECTURE.md: „два кеша, които се борят,
# са по-лоши от нула" - predictions_snapshot (обновявана на 30 мин от
# build-predictions-snapshot.timer, виж Стъпка 3 по-горе в CLAUDE_HANDOFF.md)
# вече играе ролята на кеш пред скъпата Poisson/Dixon-Coles сметка; тя вече
# НЕ се случва вътре в тази заявка (виж _predict_matches_for_league_from_snapshot).
# Втори 5-минутен кеш отгоре само добавяше закъснение (live резултат/
# lineups_confirmed можеха да изостанат до 5 мин) без реална полза.
def _predict_matches_for_league(league, from_date, to_date, use_snapshot=True):
    if use_snapshot:
        return _predict_matches_for_league_from_snapshot(league, from_date, to_date)
    return _predict_matches_for_league_impl(league, from_date, to_date)


# Партида 3, Стъпка 4 (21.08.2026, ARCHITECTURE.md, Граница 2: „смятане
# срещу показване"). Флаг за връщане към стария път без промяна в кода -
# просто смени на False. ?source=live / ?source=snapshot в заявката
# override-ва флага за момента (сравнение без рестарт).
DAILY_USE_SNAPSHOT = True


def _daily_use_snapshot(req):
    override = req.args.get("source")
    if override == "live":
        return False
    if override == "snapshot":
        return True
    return DAILY_USE_SNAPSHOT


def _predict_matches_for_league_from_snapshot(league, from_date, to_date):
    """Партида 3, Стъпка 4: чете pick/pct/code от predictions_snapshot
    (вече смятано на фон от build_predictions_snapshot.py, на всеки 30 мин
    - виж build-predictions-snapshot.timer) вместо да смята Poisson/
    Dixon-Coles/compute_grouped_markets „на момента" за всеки мач - точно
    тази сметка беше установеният проблем зад бавния студен старт на
    /daily (виж И.3 по-горе). Списъкът с мачове (fixture_id, дата, отбори,
    лога, живо статус/резултат) си остава от fetch_upcoming_fixtures() -
    евтина API заявка, никога не е била установеният проблем.

    Ако снимката още няма ред за даден fixture (нов мач, появил се между
    две пускания на фоновата задача - прозорец до 30 мин) - НЕ смятаме на
    момента (би върнало старата бавност точно за случая, който тази
    стъпка маха) - показваме честно „изчаква следващо изчисление".

    inj_note/lineups_confirmed логиката е ИДЕНТИЧНА на старата (евтини,
    кеширани справки - никога не са били установеният проблем).
    used_market се извежда наново от текущия cached_odds (същото условие
    като в _raw_candidates) вместо да се пази в снимката - козметичен
    бедж„🎯 с пазарни коеф." срещу „⏳ чисто моделна", не самата прогноза;
    евентуално разминаване от няколко минути е приемливо и за старата, и
    за новата логика."""
    fixtures, api_error = fetch_upcoming_fixtures(league, from_date, to_date)
    (teams, team_idx, ft_model, ht_model, h2_model, corners_model, cards_model,
     offsides_model, recent_model, recent_matches_count, has_injuries) = get_models(league)

    snapshot_by_fixture = st.get_snapshot_picks_for_fixtures([f["fixture"]["id"] for f in fixtures])

    matches = []
    for f in fixtures:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        match_date = f["fixture"]["date"][:16].replace("T", " ")
        fixture_id = f["fixture"]["id"]
        status_short = f["fixture"]["status"].get("short", "NS")
        elapsed = f["fixture"]["status"].get("elapsed")
        goals_home = f["goals"]["home"]
        goals_away = f["goals"]["away"]
        base = {
            "date": match_date, "home": home, "away": away,
            "home_cy": to_cyrillic(home, league), "away_cy": to_cyrillic(away, league),
            "home_logo": f["teams"]["home"].get("logo"), "away_logo": f["teams"]["away"].get("logo"),
            "fixture_id": fixture_id,
            "league": league, "league_name": ALL_LEAGUES[league]["name"],
            "status_short": status_short, "elapsed": elapsed,
            "goals_home": goals_home, "goals_away": goals_away,
        }

        if home not in team_idx or away not in team_idx:
            matches.append({**base, "pick": "Няма прогноза (нов отбор)", "pct": None, "code": None,
                             "odds": None, "picks": [], "card": None, "inj_note": None, "lineups_confirmed": False,
                             "used_market": None, "odds_updated_at": None, "live_result": None})
            continue

        picks_rows = snapshot_by_fixture.get(fixture_id)
        if not picks_rows:
            matches.append({**base, "pick": "Изчаква следващо изчисление (до 30 мин)", "pct": None,
                             "code": None, "odds": None, "picks": [], "card": None, "inj_note": None,
                             "lineups_confirmed": False, "used_market": None, "odds_updated_at": None,
                             "live_result": None})
            continue

        top = picks_rows[0]
        picks_list = [{"label": r["pick_label"], "pct": r["pick_pct"], "code": r["market_code"],
                        "odds": r["fair_odds"]} for r in picks_rows]

        inj_note = None
        if has_injuries:
            cached_inj = st.get_cached_injuries(fixture_id)
            if cached_inj is not None:
                home_inj, away_inj, ok = cached_inj
            else:
                home_inj, away_inj, ok = fetch_fixture_injuries(fixture_id)
                st.set_cached_injuries(fixture_id, home_inj, away_inj, ok)
            if ok:
                inj_note = f"Контузии: {to_cyrillic(home, league)} {home_inj}, {to_cyrillic(away, league)} {away_inj}"
            else:
                inj_note = "Няма данни за контузии за този мач (все още)"

        live_result = None
        if status_short in LIVE_STATUSES and elapsed is not None:
            lam_ht, mu_ht = fl.get_lambdas(ht_model, team_idx, home, away)
            lam_2h, mu_2h = fl.get_lambdas(h2_model, team_idx, home, away)
            if lam_ht is not None:
                try:
                    live_result = fl.live_match_probs_v2(lam_ht, mu_ht, lam_2h, mu_2h,
                                                           elapsed, goals_home or 0, goals_away or 0)
                except Exception:
                    live_result = None

        cached_odds = st.get_cached_odds(fixture_id)
        used_market = bool(cached_odds and cached_odds.get("home_win") and cached_odds.get("draw")
                            and cached_odds.get("away_win")) or bool(
                            cached_odds and cached_odds.get("over25") and cached_odds.get("under25"))

        try:
            kickoff = datetime.fromisoformat(f["fixture"]["date"])
            minutes_to_kickoff = (kickoff - datetime.now(kickoff.tzinfo)).total_seconds() / 60
        except Exception:
            minutes_to_kickoff = 9999
        lineups_confirmed = False
        if 0 <= minutes_to_kickoff <= 60:
            lineups_confirmed = fetch_lineups_available(fixture_id)

        card = build_pick_card(picks_list, cached_odds)
        matches.append({**base, "pick": top["pick_label"], "pct": top["pick_pct"], "code": top["market_code"],
                         "odds": top["fair_odds"], "picks": picks_list, "card": card, "inj_note": inj_note,
                         "lineups_confirmed": lineups_confirmed, "used_market": used_market,
                         "odds_updated_at": (cached_odds.get("fetched_at") if cached_odds else None),
                         "live_result": live_result})
    return matches, api_error


def _predict_matches_for_league_impl(league, from_date, to_date, use_fixture_cache=False):
    # use_fixture_cache=True само от build_predictions_snapshot.py (фонова
    # задача на 30 мин, споделя fixture_list_cache с run_refresh_odds_cache/
    # run_refresh_injuries_cache - виж 22.08.2026 бележката там). Остава
    # False по подразбиране - тази функция се вика и от /daily?source=live
    # (рядка ръчна диагностика), където живият статус трябва да е пресен.
    fixtures, api_error = fetch_upcoming_fixtures(league, from_date, to_date, use_cache=use_fixture_cache)
    (teams, team_idx, ft_model, ht_model, h2_model, corners_model, cards_model,
     offsides_model, recent_model, recent_matches_count, has_injuries) = get_models(league)
    rho_ft = ft_model.get("rho", 0.0)  # Фаза K.1 (20.08.2026)

    matches = []
    for f in fixtures:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        match_date = f["fixture"]["date"][:16].replace("T", " ")
        fixture_id = f["fixture"]["id"]
        status_short = f["fixture"]["status"].get("short", "NS")
        elapsed = f["fixture"]["status"].get("elapsed")
        goals_home = f["goals"]["home"]
        goals_away = f["goals"]["away"]
        if home not in team_idx or away not in team_idx:
            matches.append({
                "date": match_date, "home": home, "away": away,
                "home_cy": to_cyrillic(home, league), "away_cy": to_cyrillic(away, league),
                "home_logo": f["teams"]["home"].get("logo"), "away_logo": f["teams"]["away"].get("logo"),
                "pick": "Няма прогноза (нов отбор)", "pct": None, "code": None, "odds": None, "picks": [],
                "fixture_id": fixture_id, "inj_note": None,
                "lineups_confirmed": False,
                "league": league, "league_name": ALL_LEAGUES[league]["name"],
                "used_market": None, "odds_updated_at": None,
                "status_short": status_short, "elapsed": elapsed,
                "goals_home": goals_home, "goals_away": goals_away, "live_result": None,
            })
            continue

        home_inj, away_inj = 0, 0
        inj_note = None
        if has_injuries:
            # Хотфикс 12.08.2026: първо кешът (виж st.get_cached_injuries),
            # само при "студен" или изтекъл кеш се тегли на живо от API-то.
            cached_inj = st.get_cached_injuries(fixture_id)
            if cached_inj is not None:
                home_inj, away_inj, ok = cached_inj
            else:
                home_inj, away_inj, ok = fetch_fixture_injuries(fixture_id)
                st.set_cached_injuries(fixture_id, home_inj, away_inj, ok)
            if ok:
                inj_note = f"Контузии: {to_cyrillic(home, league)} {home_inj}, {to_cyrillic(away, league)} {away_inj}"
            else:
                inj_note = "Няма данни за контузии за този мач (все още)"

        lam, mu = get_ft_lambdas(ft_model, team_idx, home, away, home_inj, away_inj)
        lam_ht, mu_ht = fl.get_lambdas(ht_model, team_idx, home, away)
        lam_2h, mu_2h = fl.get_lambdas(h2_model, team_idx, home, away)
        ht_ft_probs = predict_ht_ft(lam_ht, mu_ht, lam_2h, mu_2h)
        live_result = None
        if status_short in LIVE_STATUSES and elapsed is not None and lam_ht is not None:
            try:
                live_result = fl.live_match_probs_v2(lam_ht, mu_ht, lam_2h, mu_2h,
                                                       elapsed, goals_home or 0, goals_away or 0)
            except Exception:
                live_result = None
        cached_odds = st.get_cached_odds(fixture_id)
        # Фаза F3: една заявка към top_picks_with_code() вместо отделни
        # извиквания на top_pick_with_code() + top_picks_with_code() -
        # picks_raw[0] е ГАРАНТИРАНО идентичен на старото top_pick_with_code()
        # (доказано локално с 300 случайни случая преди деплой), затова
        # комбинираната колонка/залог логиката по-долу (която разчита на
        # единичните pick/pct/code) остава непроменена.
        # Задача 5 (нощна сесия 24.08.2026): n вдигнато от 3 на 8 (максималният
        # брой сурови кандидати - виж _raw_candidates) - build_pick_card() по-долу
        # трябва да вижда ВСИЧКИ доверени кандидати, за да намери реално
        # най-стойностния по EV, не само измежду топ 3 по вероятност. picks_raw[0]
        # остава идентичен на преди (сортирано низходящо, независимо от n).
        picks_raw, used_market = top_picks_with_code(lam, mu, home, away, ht_ft_probs, league, market_odds=cached_odds, n=8, rho=rho_ft)
        pick, pct, code = picks_raw[0]
        picks_list = [
            {"label": p_label, "pct": p_pct, "code": p_code, "odds": fair_odds(p_pct)}
            for p_label, p_pct, p_code in picks_raw
        ]
        card = build_pick_card(picks_list, cached_odds)
        # Фаза И.3 (21.08.2026): проверяваме already_logged() ПРЕДИ да смятаме
        # compute_grouped_markets() - преди тук се смяташе за ВСЕКИ мач на
        # ВСЯКО зареждане на /daily, само за да се провери после дали изобщо
        # трябва да се логне. compute_grouped_markets() е скъпа сметка
        # (пълна Poisson/Dixon-Coles сметка за до 8 модела), а already_logged()
        # е една евтина индексирана справка в SQLite (idx_predictions_fixture_market).
        # За мач, логнат при предишно зареждане, старият резултат така или
        # иначе се изхвърляше неизползван - тази промяна само пропуска
        # ненужната сметка, логването е побитово идентично (доказано локално
        # преди деплой).
        if not st.already_logged(fixture_id):
            # Задача 3 (нощна сесия 24.08.2026): real_odds=cached_odds подадено тук,
            # за да се логне СЪЩОТО (смесено, за 1X2/O-U 2.5) pick_pct, което вече
            # показва /daily - иначе predictions_log.pick_pct винаги оставаше чист
            # модел (виж validation/blend_vs_raw_audit_20260824.md, т.2), а /value
            # и началната страница четат точно pick_pct от лога за класирането си.
            groups_for_log, _ = compute_grouped_markets(league, home, away, home_inj, away_inj, real_odds=cached_odds)
            if groups_for_log:
                # Хотфикс 12.08.2026: премахнато живо API извикване тук - точно
                # това причиняваше rate limit/524 при /daily?league=all (до 8
                # успоредни лиги x по едно допълнително API извикване на мач).
                # Ползваме вече изтеглените cached_odds (кеширани по-горе в тази
                # функция); ако липсват - логваме без коефициент. Съществуващата
                # фонова задача refresh_pending_odds.py (get_fixtures_needing_odds_refresh
                # / update_odds_for_fixture) вече е предназначена точно за
                # асинхронно допълване на такива липсващи коефициенти по-късно.
                st.log_all_markets(league, fixture_id, match_date, home, away, groups_for_log, real_odds=cached_odds)

        try:
            kickoff = datetime.fromisoformat(f["fixture"]["date"])
            minutes_to_kickoff = (kickoff - datetime.now(kickoff.tzinfo)).total_seconds() / 60
        except Exception:
            minutes_to_kickoff = 9999

        lineups_confirmed = False
        if 0 <= minutes_to_kickoff <= 60:
            lineups_confirmed = fetch_lineups_available(fixture_id)
        matches.append({
            "date": match_date, "home": home, "away": away,
            "home_cy": to_cyrillic(home, league), "away_cy": to_cyrillic(away, league),
            "home_logo": f["teams"]["home"].get("logo"), "away_logo": f["teams"]["away"].get("logo"),
            "pick": pick, "pct": pct, "code": code, "odds": fair_odds(pct), "picks": picks_list, "card": card,
            "fixture_id": fixture_id, "inj_note": inj_note,
            "lineups_confirmed": lineups_confirmed,
            "league": league, "league_name": ALL_LEAGUES[league]["name"],
            "used_market": used_market, "odds_updated_at": (cached_odds.get("fetched_at") if cached_odds else None),
            "status_short": status_short, "elapsed": elapsed,
            "goals_home": goals_home, "goals_away": goals_away, "live_result": live_result,
        })
    return matches, api_error


_TOP_PICK_SAFE_CODES = {"home_win", "draw", "away_win", "over25", "under25", "home_over15", "home_under15"}


def _is_safe_top_market(code):
    return code in _TOP_PICK_SAFE_CODES or code.startswith("htft:")


def run_diagnostics():
    import sqlite3
    results = {"db": [], "api": [], "models": [], "services": [], "disk": None,
               "recent_errors_count": None, "recent_errors_sample": []}

    for db_name in ["predictions.db", "bets.db"]:
        entry = {"name": db_name}
        if os.path.exists(db_name):
            entry["exists"] = True
            entry["size_mb"] = round(os.path.getsize(db_name) / (1024 * 1024), 2)
            try:
                conn = sqlite3.connect(db_name)
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                entry["integrity"] = integrity
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                row_counts = {}
                for (tname,) in tables:
                    try:
                        row_counts[tname] = conn.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
                    except Exception:
                        pass
                entry["row_counts"] = row_counts
                conn.close()
                entry["ok"] = (integrity == "ok")
            except Exception as e:
                entry["ok"] = False
                entry["error"] = str(e)
        else:
            entry["exists"] = False
            entry["ok"] = False
        results["db"].append(entry)

    api_entry = {"name": "API-Football (/status)"}
    try:
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/status", headers=API_HEADERS, timeout=10)
        elapsed = round((time.time() - t0) * 1000)
        data = r.json()
        api_entry["response_ms"] = elapsed
        req_info = data.get("response", {}).get("requests", {})
        api_entry["used_today"] = req_info.get("current")
        api_entry["limit_day"] = req_info.get("limit_day")
        if req_info.get("limit_day") is not None and req_info.get("current") is not None:
            api_entry["remaining"] = req_info["limit_day"] - req_info["current"]
        api_entry["ok"] = (r.status_code == 200 and not data.get("errors"))
        if data.get("errors"):
            api_entry["errors"] = data["errors"]
    except Exception as e:
        api_entry["ok"] = False
        api_entry["error"] = str(e)
    results["api"].append(api_entry)

    for key in ALL_LEAGUES.keys():
        entry = {"league": key}
        pkl_path = os.path.join("model_cache", f"{key}.pkl")
        csv_path = f"{key}_merged_full.csv"
        entry["csv_exists"] = os.path.exists(csv_path)
        entry["pkl_exists"] = os.path.exists(pkl_path)
        if entry["csv_exists"]:
            entry["csv_modified"] = datetime.fromtimestamp(os.path.getmtime(csv_path)).strftime("%Y-%m-%d %H:%M")
        if entry["pkl_exists"]:
            entry["pkl_modified"] = datetime.fromtimestamp(os.path.getmtime(pkl_path)).strftime("%Y-%m-%d %H:%M")
            entry["cache_fresh"] = (not entry["csv_exists"]) or (os.path.getmtime(pkl_path) >= os.path.getmtime(csv_path))
        else:
            entry["cache_fresh"] = False
        results["models"].append(entry)

    for svc in ["match-predictor-app", "cloudflared", "check-results.timer", "predictions-server"]:
        entry = {"name": svc}
        try:
            out = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=5)
            entry["status"] = out.stdout.strip()
            entry["ok"] = entry["status"] == "active"
        except Exception as e:
            entry["ok"] = False
            entry["error"] = str(e)
        results["services"].append(entry)

    total, used, free = shutil.disk_usage(".")
    results["disk"] = {
        "total_gb": round(total / (1024 ** 3), 1),
        "free_gb": round(free / (1024 ** 3), 1),
        "free_pct": round(free / total * 100, 1),
        "ok": (free / total) > 0.1,
    }

    try:
        out = subprocess.run(["journalctl", "-u", "match-predictor-app", "-n", "500", "--no-pager"],
                              capture_output=True, text=True, timeout=10)
        error_lines = [l for l in out.stdout.splitlines() if "ERROR" in l or "Traceback" in l]
        results["recent_errors_count"] = len(error_lines)
        results["recent_errors_sample"] = error_lines[-5:]
    except Exception as e:
        results["recent_errors_count"] = None
        results["recent_errors_sample"] = [str(e)]

    return results


import sys as _sys
print("Предварително зареждане на модели за всички лиги...", flush=True)
for _lg in ALL_LEAGUES.keys():
    try:
        print(f"  зареждам {_lg}...", flush=True)
        get_models(_lg)
        print(f"  {_lg} готово", flush=True)
    except Exception as _e:
        print(f"  ГРЕШКА при зареждане на {_lg}: {_e}")
print("Всички модели са в кеша.", flush=True)

from web.results import register_results_view
register_results_view(app, {
    "BASE_STYLE": BASE_STYLE, "SIDEBAR_STYLE": SIDEBAR_STYLE, "SIDEBAR_HTML": SIDEBAR_HTML,
    "ALL_LEAGUES": ALL_LEAGUES, "LEAGUE_FLAGS": LEAGUE_FLAGS, "market_label": market_label,
    "to_cyrillic": to_cyrillic, "st": st, "bt": bt,
})
from web.value import register_value_view
register_value_view(app, {
    "BASE_STYLE": BASE_STYLE, "SIDEBAR_STYLE": SIDEBAR_STYLE, "SIDEBAR_HTML": SIDEBAR_HTML,
    "ALL_LEAGUES": ALL_LEAGUES, "LEAGUE_FLAGS": LEAGUE_FLAGS, "market_label": market_label,
    "to_cyrillic": to_cyrillic, "st": st, "policy": policy,
})
from web.admin import register_admin_routes
register_admin_routes(app, {
    "ALL_LEAGUES": ALL_LEAGUES, "LEAGUE_FLAGS": LEAGUE_FLAGS,
    "load_active_leagues": load_active_leagues, "ACTIVE_LEAGUES_COOKIE": ACTIVE_LEAGUES_COOKIE,
    "run_refresh_all": run_refresh_all, "run_refresh_odds_cache": run_refresh_odds_cache,
    "run_refresh_injuries_cache": run_refresh_injuries_cache, "run_diagnostics": run_diagnostics,
    "_try_start_refresh": _try_start_refresh, "get_refresh_state": get_refresh_state,
    "BASE_STYLE": BASE_STYLE, "st": st, "market_label": market_label, "policy": policy,
    "to_cyrillic": to_cyrillic, "API_KEY": API_KEY, "BASE_URL": BASE_URL, "requests": requests,
})
from web.daily import register_daily_routes
register_daily_routes(app, {
    "DAYS_AHEAD": DAYS_AHEAD, "LIVE_STATUSES": LIVE_STATUSES, "FINISHED_STATUSES": FINISHED_STATUSES,
    "ALL_LEAGUES": ALL_LEAGUES, "LEAGUE_FLAGS": LEAGUE_FLAGS,
    "st": st, "evaluation": evaluation, "ps": ps, "policy": policy, "to_cyrillic": to_cyrillic, "fl": fl,
    "get_models": get_models, "get_leagues": get_leagues, "compute_grouped_markets": compute_grouped_markets,
    "_daily_use_snapshot": _daily_use_snapshot, "_predict_matches_for_league": _predict_matches_for_league,
    "fetch_fixture_id_for_today": fetch_fixture_id_for_today, "get_refresh_state": get_refresh_state,
})
from web.match import register_match_routes
register_match_routes(app, {
    "get_models": get_models, "st": st,
    "fetch_fixture_injuries": fetch_fixture_injuries, "fetch_fixture_odds": fetch_fixture_odds,
    "fetch_lineups_available": fetch_lineups_available, "fetch_fixture_predictions": fetch_fixture_predictions,
    "fetch_team_recent_form": fetch_team_recent_form, "fetch_league_standings_for_teams": fetch_league_standings_for_teams,
    "fetch_fixture_lineups_full": fetch_fixture_lineups_full,
    "to_cyrillic": to_cyrillic, "ALL_LEAGUES": ALL_LEAGUES, "compute_grouped_markets": compute_grouped_markets,
    "fair_odds": fair_odds, "pp": pp, "bt": bt, "API_KEY": API_KEY, "BASE_URL": BASE_URL, "requests": requests,
})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)
