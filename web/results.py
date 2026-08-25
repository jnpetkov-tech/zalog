"""
Нова страница "Резултати и ефективност" — допълва /system_check (не го заменя, не го пипа).
Регистрира се отделно чрез register_results_view(app, ctx), за да няма
кръгов импорт с match_predictor_app.py.
"""
from flask import Blueprint, request, render_template
from datetime import datetime, date, timedelta
import prediction_policy as policy
import pick_selection as ps
import evaluation
import brier_vs_market as bm

ROI_MARKETS = {"home_win", "draw", "away_win", "over25", "under25"}
CALIBRATION_BINS = [(50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
PAGE_SIZE = 30


# ---------- pure helper functions (no Flask/db dependency, easy to unit-test) ----------

def _profit(status, market_odds):
    if status == "won":
        return market_odds - 1.0
    if status == "lost":
        return -1.0
    return None


def _edge_pct(our_odds, market_odds):
    if not our_odds or not market_odds or our_odds <= 0:
        return None
    return (market_odds / our_odds - 1) * 100.0


def _to_float(v):
    try:
        if v is None:
            return None
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def load_rows(st, bt, source):
    raw = bt.list_bets() if source == "mybets" else st.list_predictions()
    rows = []
    for r in raw:
        r = dict(r)
        r["market_odds"] = _to_float(r.get("market_odds"))
        r["our_fair_odds"] = _to_float(r.get("our_fair_odds"))
        r["edge"] = _edge_pct(r.get("our_fair_odds"), r.get("market_odds"))
        rows.append(r)
    return rows


def apply_filters(rows, args, to_cyrillic):
    period = args.get("period", "")
    f_league = args.get("f_league", "")
    f_market = args.get("f_market", "")
    f_status = args.get("f_status", "")
    min_conf = args.get("min_conf", "")
    q = args.get("q", "").strip().lower()

    out = rows
    if period in ("7", "30"):
        cutoff = date.today() - timedelta(days=int(period))

        def _in_period(r):
            try:
                d = datetime.strptime((r["match_date"] or "")[:10], "%Y-%m-%d").date()
                return d >= cutoff
            except (ValueError, TypeError):
                return True
        out = [r for r in out if _in_period(r)]
    if f_league:
        out = [r for r in out if r["league"] == f_league]
    if f_market:
        out = [r for r in out if r["market_code"] == f_market]
    if f_status == "pending":
        out = [r for r in out if r["status"] in ("pending", "no_data")]
    elif f_status == "settled":
        out = [r for r in out if r["status"] in ("won", "lost")]
    if min_conf:
        try:
            mc = float(min_conf)
            out = [r for r in out if (r["pick_pct"] or 0) >= mc]
        except ValueError:
            pass
    if q:
        def _match_team(r):
            home = to_cyrillic(r["home_team"], r["league"])
            away = to_cyrillic(r["away_team"], r["league"])
            return (q in home.lower() or q in away.lower()
                    or q in (r["home_team"] or "").lower() or q in (r["away_team"] or "").lower())
        out = [r for r in out if _match_team(r)]
    return out


def group_by_match(rows, to_cyrillic):
    groups = {}
    for r in rows:
        key = r["fixture_id"]
        groups.setdefault(key, {
            "fixture_id": key, "date": r["match_date"], "league": r["league"],
            "home": r["home_team"], "away": r["away_team"], "predictions": [],
        })
        groups[key]["predictions"].append(r)
    out = list(groups.values())
    for m in out:
        m["home_cy"] = to_cyrillic(m["home"], m["league"])
        m["away_cy"] = to_cyrillic(m["away"], m["league"])
        m["pending_count"] = sum(1 for p in m["predictions"] if p["status"] in ("pending", "no_data"))
        # Стъпка 1 (PREUSTROYSTVO.md, 25.08.2026): единствената функция за
        # "коя е прогнозата за мача" - виж pick_selection.top_pick_for_match()
        # докстринга защо старият ръчен max() тук отпадна (можеше да падне
        # до REJECTED пазар, въпреки текста на страницата - Находка 3).
        m["top_pred"] = ps.top_pick_for_match(m["predictions"], m["league"], policy)
        publishable = [p for p in m["predictions"] if policy.is_publishable(m["league"], p["market_code"])]
        m["other_preds"] = [p for p in publishable if p is not m["top_pred"]]
        m["actual_hg"] = next((p["actual_home_goals"] for p in m["predictions"] if p["actual_home_goals"] is not None), None)
        m["actual_ag"] = next((p["actual_away_goals"] for p in m["predictions"] if p["actual_away_goals"] is not None), None)
    return out


def overall_stats(rows):
    settled = [r for r in rows if r["status"] in ("won", "lost")]
    pending_n = sum(1 for r in rows if r["status"] in ("pending", "no_data"))
    won = sum(1 for r in settled if r["status"] == "won")
    win_rate = (won / len(settled) * 100.0) if settled else None
    roi_items = [r for r in settled if r["market_odds"]]
    roi = None
    profit = 0.0
    avg_odds = None
    if roi_items:
        profit = sum(_profit(r["status"], r["market_odds"]) for r in roi_items)
        roi = profit / len(roi_items) * 100.0
        avg_odds = sum(r["market_odds"] for r in roi_items) / len(roi_items)
    return {
        "settled": len(settled), "pending": pending_n, "win_rate": win_rate,
        "roi": roi, "roi_n": len(roi_items), "profit": profit, "avg_odds": avg_odds,
    }


def calibration_table(rows):
    out = []
    for lo, hi in CALIBRATION_BINS:
        items = [r for r in rows if r["status"] in ("won", "lost") and lo <= (r["pick_pct"] or 0) < hi]
        n = len(items)
        if n == 0:
            continue
        predicted = sum(r["pick_pct"] for r in items) / n
        won = sum(1 for r in items if r["status"] == "won")
        actual = won / n * 100.0
        out.append({
            "label": f"{lo}–{min(hi, 100)}%", "n": n,
            "predicted": predicted, "actual": actual, "diff": actual - predicted,
        })
    return out


def roi_by_market(rows, market_label):
    # Фаза O.1 (21.08.2026): само публикуваните прогнози (evaluation.published_picks(),
    # огледално на I.3 остатъка) - иначе мач с 2+ логнати пазара се брои двойно тук.
    picks = evaluation.published_picks(rows, policy)
    by_m = {}
    for r in picks:
        if r["market_code"] not in ROI_MARKETS or r["status"] not in ("won", "lost"):
            continue
        if not r["market_odds"]:
            continue
        by_m.setdefault(r["market_code"], []).append(r)
    out = []
    for code, items in by_m.items():
        n = len(items)
        won = sum(1 for r in items if r["status"] == "won")
        profit = sum(_profit(r["status"], r["market_odds"]) for r in items)
        avg_odds = sum(r["market_odds"] for r in items) / n
        out.append({
            "market_code": code, "label": market_label(code), "n": n,
            "win_rate": won / n * 100.0, "avg_odds": avg_odds,
            "roi": profit / n * 100.0, "profit": profit,
        })
    out.sort(key=lambda x: -x["roi"])
    return out


def roi_by_league(rows, ALL_LEAGUES, LEAGUE_FLAGS):
    # Фаза O.1 (21.08.2026): само публикуваните прогнози - виж бележката в roi_by_market().
    picks = evaluation.published_picks(rows, policy)
    settled = {}
    pending = {}
    for r in picks:
        lg = r["league"]
        if r["status"] in ("pending", "no_data"):
            pending[lg] = pending.get(lg, 0) + 1
        elif r["status"] in ("won", "lost"):
            settled.setdefault(lg, []).append(r)
    out = []
    for lg in set(settled) | set(pending):
        items = settled.get(lg, [])
        n = len(items)
        won = sum(1 for r in items if r["status"] == "won")
        win_rate = (won / n * 100.0) if n else None
        roi_items = [r for r in items if r["market_odds"]]
        roi = None
        if roi_items:
            profit = sum(_profit(r["status"], r["market_odds"]) for r in roi_items)
            roi = profit / len(roi_items) * 100.0
        out.append({
            "league": lg, "name": ALL_LEAGUES.get(lg, {}).get("name", lg),
            "flag": LEAGUE_FLAGS.get(lg, "⚽"), "n": n, "win_rate": win_rate,
            "roi": roi, "roi_n": len(roi_items), "pending": pending.get(lg, 0),
        })
    out.sort(key=lambda x: (x["win_rate"] is None, -(x["win_rate"] or -999)))
    return out


def weekly_roi(rows):
    # Фаза O.1 (21.08.2026): само публикуваните прогнози - виж бележката в roi_by_market().
    picks = evaluation.published_picks(rows, policy)
    buckets = {}
    for r in picks:
        if r["status"] not in ("won", "lost") or not r["market_odds"]:
            continue
        try:
            d = datetime.strptime((r["match_date"] or "")[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        wk_start = d - timedelta(days=d.weekday())
        buckets.setdefault(wk_start, []).append(r)
    out = []
    for wk, items in sorted(buckets.items()):
        profit = sum(_profit(r["status"], r["market_odds"]) for r in items)
        roi = profit / len(items) * 100.0
        out.append({"week": wk.strftime("%d.%m"), "roi": roi, "n": len(items)})
    return out[-8:]


def brier_vs_market_table(rows, ALL_LEAGUES, LEAGUE_FLAGS, market_label):
    """Точка 1 (разговор с Дака, 24.08.2026): "Бием ли пазара". Обвивка над
    brier_vs_market.py (чист модул, без БД - виж докстринга там за пълната
    методология: raw/blend/market Brier, basis raw/blended, split-half,
    брой тествани комбинации срещу очаквани фалшиви положителни). Тук само
    добавяме имена за показване - самото изчисление е идентично на
    validation/vs_market_brier.py, за да не се разминат числата между
    записания бектест и живата страница."""
    detail = bm.build_detail_rows(rows)
    combos = bm.summarize_by_league_market(detail)
    for c in combos:
        c["league_name"] = ALL_LEAGUES.get(c["league"], {}).get("name", c["league"])
        c["league_flag"] = LEAGUE_FLAGS.get(c["league"], "⚽")
        c["market_name"] = market_label(c["market_code"])
    combos.sort(key=lambda c: (c["league_name"], c["market_name"]))
    mc = bm.multiple_comparisons_summary(combos)
    return combos, mc


def _edge_sort_key(m):
    tp = m["top_pred"]
    if tp is None:
        return (True, True, 999.0)
    edge = tp.get("edge")
    return (False, edge is None, -(edge if edge is not None else -999.0))


def build_qs(args, **overrides):
    merged = {k: v for k, v in args.items() if v}
    merged.update({k: v for k, v in overrides.items() if v not in (None, "")})
    # drop keys explicitly cleared with empty override
    for k, v in overrides.items():
        if v in (None, ""):
            merged.pop(k, None)
    return "&".join(f"{k}={v}" for k, v in merged.items())


# ---------- registration ----------

def register_results_view(app, ctx):
    BASE_STYLE = ctx["BASE_STYLE"]
    SIDEBAR_STYLE = ctx["SIDEBAR_STYLE"]
    SIDEBAR_HTML = ctx["SIDEBAR_HTML"]
    ALL_LEAGUES = ctx["ALL_LEAGUES"]
    LEAGUE_FLAGS = ctx["LEAGUE_FLAGS"]
    market_label = ctx["market_label"]
    to_cyrillic = ctx["to_cyrillic"]
    st = ctx["st"]
    bt = ctx["bt"]

    results_bp = Blueprint("results", __name__)

    @results_bp.route("/results")
    def results_view():
        args = request.args
        source = args.get("source", "all")
        tab = args.get("tab", "results")
        sort = args.get("sort", "date")

        rows = load_rows(st, bt, source)
        filtered = apply_filters(rows, args, to_cyrillic)

        league_options = sorted(
            {(r["league"], ALL_LEAGUES.get(r["league"], {}).get("name", r["league"])) for r in rows},
            key=lambda x: x[1])
        market_options = sorted(
            {(r["market_code"], market_label(r["market_code"])) for r in rows},
            key=lambda x: x[1])

        matches = group_by_match(filtered, to_cyrillic)
        if sort == "edge":
            matches.sort(key=_edge_sort_key)
        elif sort == "date_asc":
            matches.sort(key=lambda m: m["date"] or "")
        else:
            matches.sort(key=lambda m: m["date"] or "", reverse=True)

        total = len(matches)
        try:
            page = max(1, int(args.get("page", "1")))
        except ValueError:
            page = 1
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, total_pages)
        start = (page - 1) * PAGE_SIZE
        page_matches = matches[start:start + PAGE_SIZE]

        overall = overall_stats(filtered)
        # Фаза I.3 (остатък): честна метрика само върху ПУБЛИКУВАНИТЕ прогнози
        # (виж evaluation.py, Фаза I.2) - замества calibration_table(), която
        # смяташе директно върху суровия predictions_log (артефакт - виж
        # ACTION_PLAN.md Б.3/opus_review раздел 1).
        eval_summary = evaluation.summary(filtered, policy)
        rmarket = roi_by_market(filtered, market_label)
        rleague = roi_by_league(filtered, ALL_LEAGUES, LEAGUE_FLAGS)
        weekly = weekly_roi(filtered)
        weekly_brier = evaluation.weekly_brier(filtered, policy)

        # Точка 1 (24.08.2026): винаги от predictions_log (не bt.list_bets()) -
        # "бием ли пазара" е въпрос за самия модел, не за личните залози на
        # Дака, затова НЕ следва избора "Само моите залози" по-горе. Другите
        # филтри (период/лига/пазар/статус/търсене) важат както навсякъде
        # другаде на страницата.
        brier_source_rows = apply_filters(st.list_predictions(), args, to_cyrillic) if source == "mybets" else filtered
        brier_combos, brier_mc = brier_vs_market_table(brier_source_rows, ALL_LEAGUES, LEAGUE_FLAGS, market_label)

        return render_template(
            "results.html",
            active_page="results", tab=tab, view_source=source, sort=sort,
            args=args, qs=build_qs,
            matches=page_matches, total=total, page=page, total_pages=total_pages,
            league_options=league_options, market_options=market_options,
            overall=overall, eval_summary=eval_summary, roi_market=rmarket,
            roi_league=rleague, weekly=weekly, weekly_brier=weekly_brier, market_label=market_label,
            brier_combos=brier_combos, brier_mc=brier_mc, brier_min_n=bm.MIN_N,
            LEAGUE_FLAGS=LEAGUE_FLAGS, cyrillic=to_cyrillic,
        )

    app.register_blueprint(results_bp)
