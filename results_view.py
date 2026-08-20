"""
Нова страница "Резултати и ефективност" — допълва /system_check (не го заменя, не го пипа).
Регистрира се отделно чрез register_results_view(app, ctx), за да няма
кръгов импорт с match_predictor_app.py.
"""
from flask import request, render_template_string
from datetime import datetime, date, timedelta
import prediction_policy as policy
import evaluation

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
        publishable = [p for p in m["predictions"] if policy.is_publishable(m["league"], p["market_code"])]
        safe = [p for p in publishable if policy.is_top_pick_eligible(m["league"], p["market_code"], allow_weak=True)]
        m["top_pred"] = max(safe or publishable or m["predictions"], key=lambda p: p["pick_pct"] or 0)
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
    by_m = {}
    for r in rows:
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
    settled = {}
    pending = {}
    for r in rows:
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
    buckets = {}
    for r in rows:
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

    RESULTS_TEMPLATE = _build_template(BASE_STYLE, SIDEBAR_STYLE, SIDEBAR_HTML)

    @app.route("/results")
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
            matches.sort(key=lambda m: (m["top_pred"]["edge"] is None, -(m["top_pred"]["edge"] or -999)))
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

        return render_template_string(
            RESULTS_TEMPLATE,
            active_page="results", tab=tab, view_source=source, sort=sort,
            args=args, qs=build_qs,
            matches=page_matches, total=total, page=page, total_pages=total_pages,
            league_options=league_options, market_options=market_options,
            overall=overall, eval_summary=eval_summary, roi_market=rmarket,
            roi_league=rleague, weekly=weekly, market_label=market_label,
            LEAGUE_FLAGS=LEAGUE_FLAGS, cyrillic=to_cyrillic,
            BASE_STYLE=BASE_STYLE, SIDEBAR_STYLE=SIDEBAR_STYLE, SIDEBAR_HTML=SIDEBAR_HTML,
        )


def _build_template(BASE_STYLE, SIDEBAR_STYLE, SIDEBAR_HTML):
    extra_style = """
      .rv-tabs { display:flex; gap:4px; border-bottom:1px solid var(--border); margin-bottom:18px; }
      .rv-tab { padding:9px 16px; border:none; background:none; color:var(--sub); font-size:14px; cursor:pointer;
        border-bottom:2px solid transparent; font-family:inherit; text-decoration:none; display:inline-block; }
      .rv-tab.on { color:var(--accent); border-bottom-color:var(--accent); font-weight:600; }
      .rv-srcrow { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:16px; }
      .rv-seg { display:inline-flex; background:var(--panel2); border:1px solid var(--border); border-radius:8px; padding:3px; }
      .rv-seg a { padding:6px 14px; border:none; background:none; color:var(--sub); border-radius:6px;
        font-size:13px; cursor:pointer; font-family:inherit; text-decoration:none; }
      .rv-seg a.on { background:var(--accent); color:#fff; font-weight:600; }
      .rv-filters { display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end; background:var(--panel);
        border:1px solid var(--border); border-radius:10px; padding:12px 14px; margin-bottom:16px; }
      .rv-f { display:flex; flex-direction:column; gap:4px; }
      .rv-f label { font-size:11px; color:var(--sub); text-transform:uppercase; letter-spacing:.04em; }
      .rv-f select, .rv-f input { background:var(--panel2); border:1px solid var(--border); color:var(--text);
        border-radius:7px; padding:7px 9px; font-size:13px; font-family:inherit; min-width:110px; }
      .rv-btn { background:var(--accent); color:#fff; border:none; border-radius:7px; padding:8px 16px;
        font-size:13px; cursor:pointer; font-family:inherit; font-weight:500; }
      .rv-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(148px,1fr)); gap:10px; margin-bottom:18px; }
      .rv-kpi { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }
      .rv-kpi .k { font-size:11px; color:var(--sub); text-transform:uppercase; letter-spacing:.04em; margin-bottom:5px; }
      .rv-kpi .v { font-size:21px; font-weight:600; font-variant-numeric:tabular-nums; }
      .rv-kpi .n { font-size:11px; color:var(--sub); margin-top:2px; }
      .rv-pos { color:var(--green) } .rv-neg { color:var(--live) } .rv-neu { color:var(--sub) } .rv-dim { color:var(--sub) }
      .rv-tblwrap { background:var(--panel); border:1px solid var(--border); border-radius:10px; overflow:auto; margin-bottom:22px; }
      .rv-tblwrap table { border-radius:0; border:none; }
      .rv-tblwrap thead th { background:var(--panel2); color:var(--sub); font-weight:500; font-size:11px;
        text-transform:uppercase; letter-spacing:.04em; white-space:nowrap; }
      .rv-tblwrap thead th a { color:inherit; text-decoration:none; }
      .rv-tblwrap thead th.sorted a { color:var(--accent); }
      .rv-num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
      .rv-teams { font-weight:500; white-space:nowrap; }
      .rv-lg { font-size:11px; color:var(--sub); white-space:nowrap; }
      .rv-score { font-weight:600; font-variant-numeric:tabular-nums; }
      .rv-pill { display:inline-block; padding:1px 7px; border-radius:5px; font-size:11px; font-weight:600; }
      .rv-pill.w { background:var(--green-bg); color:var(--green); }
      .rv-pill.l { background:rgba(239,68,68,0.12); color:var(--live); }
      .rv-pill.p { background:rgba(139,145,157,0.14); color:var(--sub); }
      .rv-edge.pos { color:var(--green); font-weight:600; } .rv-edge.neg { color:var(--live); }
      .rv-sec { font-size:15px; font-weight:600; margin:26px 0 10px; }
      .rv-note { color:var(--sub); font-size:12.5px; margin:-4px 0 14px; max-width:760px; }
      .rv-warn { color:var(--yellow); }
      .rv-calbar { position:relative; height:16px; background:var(--panel2); border-radius:3px; min-width:110px; }
      .rv-calbar .mid { position:absolute; left:50%; top:-2px; bottom:-2px; width:1px; background:var(--border); }
      .rv-calbar .fill { position:absolute; top:3px; height:10px; border-radius:2px; }
      details.rv-mrow > summary { cursor:pointer; list-style:none; }
      details.rv-mrow > summary::-webkit-details-marker { display:none; }
      .rv-expand { padding:8px 14px 12px; background:var(--panel2); }
      .rv-mk { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:5px; }
      .rv-mkrow { display:flex; justify-content:space-between; gap:8px; padding:4px 8px; border-radius:6px;
        background:var(--panel); font-size:12px; }
      .rv-pager { display:flex; gap:8px; align-items:center; font-size:13px; color:var(--sub); margin-bottom:20px; }
      .rv-pager a { color:var(--accent); text-decoration:none; }
      .rv-trend { display:flex; align-items:flex-end; gap:6px; height:90px; padding:0 2px; }
      .rv-tcol { flex:1; display:flex; flex-direction:column; justify-content:flex-end; align-items:center; gap:4px; height:100%; }
      .rv-tbar { width:100%; border-radius:3px 3px 0 0; min-height:2px; }
      .rv-tlab { font-size:10px; color:var(--sub); white-space:nowrap; }
    """

    body = """
<!DOCTYPE html><html lang="bg"><head><meta charset="UTF-8">
<title>Резултати и ефективност</title>
<style>""" + BASE_STYLE + SIDEBAR_STYLE + extra_style + """</style></head><body>""" + SIDEBAR_HTML + """
<div class="container" style="max-width:1180px;">
<h1>Резултати и ефективност</h1>

<div class="rv-tabs">
  <a class="rv-tab {% if tab=='results' %}on{% endif %}" href="/results?{{ qs(args, tab='results') }}">📋 Резултати</a>
  <a class="rv-tab {% if tab=='effectiveness' %}on{% endif %}" href="/results?{{ qs(args, tab='effectiveness') }}">📈 Ефективност</a>
</div>

<div class="rv-srcrow">
  <div class="rv-seg">
    <a class="{% if view_source=='all' %}on{% endif %}" href="/results?{{ qs(args, source='all', page='1') }}">Всички прогнози</a>
    <a class="{% if view_source=='mybets' %}on{% endif %}" href="/results?{{ qs(args, source='mybets', page='1') }}">Само моите залози</a>
  </div>
</div>

{% if view_source == 'mybets' %}
<div class="rv-note rv-warn" style="margin-bottom:16px;">⚠️ При „Моите залози“ не пазим пазарния коефициент от момента на залагане — възвръщаемост/edge тук не могат да се изчислят коректно, показваме само процент познати.</div>
{% endif %}

<form class="rv-filters" method="get" action="/results">
  <input type="hidden" name="tab" value="{{tab}}">
  <input type="hidden" name="source" value="{{view_source}}">
  <div class="rv-f"><label>Период</label>
    <select name="period">
      <option value="" {% if not args.get('period') %}selected{% endif %}>Всичко</option>
      <option value="7" {% if args.get('period')=='7' %}selected{% endif %}>7 дни</option>
      <option value="30" {% if args.get('period')=='30' %}selected{% endif %}>30 дни</option>
    </select>
  </div>
  <div class="rv-f"><label>Лига</label>
    <select name="f_league">
      <option value="">Всички</option>
      {% for code, name in league_options %}
      <option value="{{code}}" {% if args.get('f_league')==code %}selected{% endif %}>{{name}}</option>
      {% endfor %}
    </select>
  </div>
  <div class="rv-f"><label>Пазар</label>
    <select name="f_market">
      <option value="">Всички</option>
      {% for code, name in market_options %}
      <option value="{{code}}" {% if args.get('f_market')==code %}selected{% endif %}>{{name}}</option>
      {% endfor %}
    </select>
  </div>
  <div class="rv-f"><label>Статус</label>
    <select name="f_status">
      <option value="">Всички</option>
      <option value="pending" {% if args.get('f_status')=='pending' %}selected{% endif %}>Чакащи</option>
      <option value="settled" {% if args.get('f_status')=='settled' %}selected{% endif %}>Приключени</option>
    </select>
  </div>
  <div class="rv-f"><label>Мин. увереност %</label><input type="text" name="min_conf" value="{{args.get('min_conf','')}}" style="min-width:80px"></div>
  <div class="rv-f"><label>Отбор</label><input type="text" name="q" value="{{args.get('q','')}}" placeholder="напр. Левски"></div>
  <button class="rv-btn" type="submit">Приложи</button>
</form>

{% if tab == 'results' %}

<div class="rv-kpis">
  <div class="rv-kpi"><div class="k">Приключени</div><div class="v">{{overall.settled}}</div><div class="n">+{{overall.pending}} чакащи</div></div>
  <div class="rv-kpi"><div class="k">Познати (честно)</div><div class="v">{% if eval_summary.actual_pct is not none %}{{"%.1f"|format(eval_summary.actual_pct)}}%{% else %}—{% endif %}</div><div class="n">{% if eval_summary.promised_avg is not none %}обещано {{"%.1f"|format(eval_summary.promised_avg)}}% &middot; n={{eval_summary.n_settled}}{% else %}n=0{% endif %}</div></div>
  <div class="rv-kpi"><div class="k">Възвръщаемост</div>
    <div class="v {% if eval_summary.roi is not none %}{% if eval_summary.roi>=0 %}rv-pos{% else %}rv-neg{% endif %}{% else %}rv-neu{% endif %}">
      {% if eval_summary.roi is not none %}{{"%+.1f"|format(eval_summary.roi)}}%{% else %}—{% endif %}
    </div>
    <div class="n">на база {{eval_summary.roi_n}} публикувани със сигурен коеф.</div>
  </div>
  <div class="rv-kpi"><div class="k">Среден коеф.</div><div class="v">{% if overall.avg_odds %}{{"%.2f"|format(overall.avg_odds)}}{% else %}—{% endif %}</div></div>
</div>

<div class="rv-tblwrap">
<table>
  <thead><tr>
    <th style="width:70px;">Дата</th><th style="width:70px;">Лига</th><th>Мач</th><th style="width:180px;">Прогноза</th>
    <th class="rv-num" style="width:60px;">Увер.</th><th class="rv-num" style="width:55px;">Наш</th><th class="rv-num" style="width:55px;">Пазар</th>
    <th class="rv-num {% if sort=='edge' %}sorted{% endif %}" style="width:65px;"><a href="/results?{{ qs(args, sort='edge') }}">Edge</a></th>
    <th class="rv-num" style="width:60px;">Резултат</th><th style="width:90px;">Изход</th>
  </tr></thead>
  <tbody>
  {% for m in matches %}
    <tr>
      <td colspan="10" style="padding:0;border:none;">
      <details class="rv-mrow">
        <summary>
        <table style="width:100%;border:none;background:none;">
        <tr>
          <td style="width:70px;border:none;" class="rv-dim">{{m.date[5:10] if m.date else '—'}}</td>
          <td class="rv-lg" style="width:70px;border:none;">{{LEAGUE_FLAGS.get(m.league,'⚽')}} {{m.league}}</td>
          <td class="rv-teams" style="border:none;">{{m.home_cy}} – {{m.away_cy}}</td>
          <td style="width:180px;border:none;">{{market_label(m.top_pred.market_code)}}</td>
          <td class="rv-num" style="width:60px;border:none;">{{"%.1f"|format(m.top_pred.pick_pct)}}%</td>
          <td class="rv-num rv-dim" style="width:55px;border:none;">{% if m.top_pred.our_fair_odds %}{{"%.2f"|format(m.top_pred.our_fair_odds)}}{% else %}—{% endif %}</td>
          <td class="rv-num" style="width:55px;border:none;">{% if m.top_pred.market_odds %}{{"%.2f"|format(m.top_pred.market_odds)}}{% else %}—{% endif %}</td>
          <td class="rv-num" style="width:65px;border:none;">
            {% if m.top_pred.edge is not none %}<span class="rv-edge {% if m.top_pred.edge>=0 %}pos{% else %}neg{% endif %}">{{"%+.1f"|format(m.top_pred.edge)}}%</span>{% else %}<span class="rv-dim">—</span>{% endif %}
          </td>
          <td class="rv-num rv-score" style="width:60px;border:none;">{% if m.actual_hg is not none %}{{m.actual_hg}}:{{m.actual_ag}}{% else %}—{% endif %}</td>
          <td style="width:90px;border:none;">
            {% if m.top_pred.status == 'won' %}<span class="rv-pill w">✓ печели</span>
            {% elif m.top_pred.status == 'lost' %}<span class="rv-pill l">✗ губи</span>
            {% elif m.top_pred.status == 'no_data' %}<span class="rv-pill p">няма данни</span>
            {% else %}<span class="rv-pill p">чака</span>{% endif %}
          </td>
        </tr>
        </table>
        </summary>
        <div class="rv-expand">
          {% if m.other_preds %}
          <div class="rv-mk">
            {% for p in m.other_preds %}
            <div class="rv-mkrow">
              <span>{{market_label(p.market_code)}}</span>
              <span class="{% if p.status=='won' %}rv-pos{% elif p.status=='lost' %}rv-neg{% else %}rv-dim{% endif %}">
                {% if p.status=='won' %}✓{% elif p.status=='lost' %}✗{% endif %} {{"%.1f"|format(p.pick_pct)}}%
              </span>
            </div>
            {% endfor %}
          </div>
          {% else %}
          <span class="rv-dim" style="font-size:12px;">Само този пазар е логнат за мача.</span>
          {% endif %}
        </div>
      </details>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="10" style="text-align:center;color:var(--sub);padding:24px;">Няма прогнози за избраните филтри.</td></tr>
  {% endfor %}
  </tbody>
</table>
</div>

<div class="rv-pager">
  <span>Общо {{total}} мача · страница {{page}} от {{total_pages}}</span>
  {% if page > 1 %}<a href="/results?{{ qs(args, page=page-1) }}">← предишна</a>{% endif %}
  {% if page < total_pages %}<a href="/results?{{ qs(args, page=page+1) }}">следваща →</a>{% endif %}
</div>
<p class="rv-note">Клик на ред разгъва всички логнати пазари за мача. Показва се "безопасната" топ прогноза (1X2, над/под 2.5) — не корнери/картони/засади.</p>

{% else %}

<div class="rv-kpis">
  <div class="rv-kpi"><div class="k">Познати (честно)</div><div class="v">{% if eval_summary.actual_pct is not none %}{{"%.1f"|format(eval_summary.actual_pct)}}%{% else %}—{% endif %}</div><div class="n">{% if eval_summary.promised_avg is not none %}обещано {{"%.1f"|format(eval_summary.promised_avg)}}%{% endif %} &middot; {{eval_summary.n_settled}} публикувани</div></div>
  <div class="rv-kpi"><div class="k">Възвръщаемост</div>
    <div class="v {% if eval_summary.roi is not none %}{% if eval_summary.roi>=0 %}rv-pos{% else %}rv-neg{% endif %}{% else %}rv-neu{% endif %}">
      {% if eval_summary.roi is not none %}{{"%+.1f"|format(eval_summary.roi)}}%{% else %}—{% endif %}
    </div>
    <div class="n">на база {{eval_summary.roi_n}} публикувани прогнози с коеф.</div>
  </div>
  <div class="rv-kpi"><div class="k">Чиста печалба</div><div class="v {% if overall.profit>=0 %}rv-pos{% else %}rv-neg{% endif %}">{{"%+.1f"|format(overall.profit)}}</div><div class="n">единици &middot; сурови редове, виж бележка</div></div>
  <div class="rv-kpi"><div class="k">Среден коеф.</div><div class="v">{% if overall.avg_odds %}{{"%.2f"|format(overall.avg_odds)}}{% else %}—{% endif %}</div></div>
</div>

{% if eval_summary.roi_n < 100 %}
<div class="rv-note rv-warn">⚠️ Възвръщаемостта (честна) стъпва само на {{eval_summary.roi_n}} публикувани прогнози с реален пазарен коефициент — малка извадка, чети с повишено внимание. "Чиста печалба" и "Среден коеф." горе все още смятат по суровите редове от predictions_log (не само публикуваните), затова не пасват точно на процента възвръщаемост — предстои изравняване в следваща стъпка. Калибрацията долу стъпва на всичките {{eval_summary.n_settled}} публикувани приключени прогнози.</div>
{% endif %}

<div class="rv-sec">Калибрация — вярна ли е увереността ни?</div>
<p class="rv-note">Ако моделът каже 80%, това трябва да се случва в ~80% от случаите. Систематично отрицателно отклонение значи, че сме прекалено самоуверени.</p>
<div class="rv-tblwrap">
<table>
  <thead><tr><th>Увереност</th><th class="rv-num">Прогнози</th><th class="rv-num">Обещано</th>
    <th class="rv-num">Реално</th><th class="rv-num">Разлика</th><th style="width:170px;">Отклонение</th></tr></thead>
  <tbody>
  {% for c in eval_summary.calibration %}
    <tr>
      <td>{{c.lo}}&ndash;{{100 if c.hi > 100 else c.hi}}%</td><td class="rv-num">{{c.n}}</td>
      <td class="rv-num rv-dim">{{"%.1f"|format(c.promised)}}%</td>
      <td class="rv-num">{{"%.1f"|format(c.actual)}}%</td>
      <td class="rv-num {% if c.diff<0 %}rv-neg{% else %}rv-pos{% endif %}">{{"%+.1f"|format(c.diff)}}pp</td>
      <td>
        <div class="rv-calbar"><div class="mid"></div>
          {% set w = (c.diff|abs) if (c.diff|abs) < 50 else 50 %}
          {% if c.diff < 0 %}
          <div class="fill" style="right:50%;width:{{w}}%;background:var(--live)"></div>
          {% else %}
          <div class="fill" style="left:50%;width:{{w}}%;background:var(--green)"></div>
          {% endif %}
        </div>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="6" style="text-align:center;color:var(--sub);padding:16px;">Недостатъчно данни за калибрация с тези филтри.</td></tr>
  {% endfor %}
  </tbody>
</table>
</div>

<div class="rv-sec">По пазар (само пазарите с реален коефициент)</div>
<p class="rv-note">Подредено по възвръщаемост, не по процент познати — висок win rate при нисък коефициент може пак да губи пари.</p>
<div class="rv-tblwrap">
<table>
  <thead><tr><th>Пазар</th><th class="rv-num">Приключени</th><th class="rv-num">Познати</th>
    <th class="rv-num">Среден кф</th><th class="rv-num">Възвръщаемост</th><th class="rv-num">Печалба</th></tr></thead>
  <tbody>
  {% for r in roi_market %}
    <tr>
      <td>{{r.label}}</td><td class="rv-num">{{r.n}}</td><td class="rv-num">{{"%.1f"|format(r.win_rate)}}%</td>
      <td class="rv-num rv-dim">{{"%.2f"|format(r.avg_odds)}}</td>
      <td class="rv-num {% if r.roi>=0 %}rv-pos{% else %}rv-neg{% endif %}">{{"%+.1f"|format(r.roi)}}%</td>
      <td class="rv-num {% if r.profit>=0 %}rv-pos{% else %}rv-neg{% endif %}">{{"%+.1f"|format(r.profit)}}</td>
    </tr>
  {% else %}
    <tr><td colspan="6" style="text-align:center;color:var(--sub);padding:16px;">Няма приключени прогнози с коефициент за тези пазари в избрания период.</td></tr>
  {% endfor %}
  </tbody>
</table>
</div>

<div class="rv-sec">По лига</div>
<div class="rv-tblwrap">
<table>
  <thead><tr><th>Лига</th><th class="rv-num">Приключени</th><th class="rv-num">Познати</th>
    <th class="rv-num">Възвръщаемост</th><th class="rv-num">Чакащи</th><th>Извадка</th></tr></thead>
  <tbody>
  {% for l in roi_league %}
    <tr>
      <td>{{l.flag}} {{l.name}}</td><td class="rv-num">{{l.n}}</td>
      <td class="rv-num">{% if l.win_rate is not none %}{{"%.1f"|format(l.win_rate)}}%{% else %}—{% endif %}</td>
      <td class="rv-num {% if l.roi is not none %}{% if l.roi>=0 %}rv-pos{% else %}rv-neg{% endif %}{% else %}rv-dim{% endif %}">
        {% if l.roi is not none %}{{"%+.1f"|format(l.roi)}}%{% else %}—{% endif %}
      </td>
      <td class="rv-num rv-dim">{{l.pending}}</td>
      <td>{% if l.n < 30 %}<span class="rv-pill p">малка</span>{% else %}<span class="rv-pill w">достатъчна</span>{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

{% if weekly %}
<div class="rv-sec">Възвръщаемост по седмици <span class="rv-note" style="margin:0;">(само 1X2 и над/под 2.5)</span></div>
<div style="background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin-bottom:20px;">
  <div class="rv-trend">
    {% set maxabs = (weekly|map(attribute='roi')|map('abs')|max) %}
    {% for w in weekly %}
    <div class="rv-tcol">
      <div class="rv-tbar" style="height:{{ ((w.roi|abs) / (maxabs if maxabs>0 else 1) * 100)|round|int }}%;background:{% if w.roi>=0 %}var(--green){% else %}var(--live){% endif %}"></div>
      <div class="rv-tlab">{{"%+.0f"|format(w.roi)}}%</div>
    </div>
    {% endfor %}
  </div>
  <div style="display:flex;gap:6px;margin-top:6px;">
    {% for w in weekly %}<div style="flex:1;text-align:center;font-size:11px;color:var(--sub);">{{w.week}}</div>{% endfor %}
  </div>
</div>
{% endif %}

{% endif %}

</div>
</body></html>
"""
    return body
