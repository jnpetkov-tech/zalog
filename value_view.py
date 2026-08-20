"""
value_view.py - Фаза F2: страница "/value", отделен модул по същия модел
като results_view.py (register_*_view(app, ctx) - избягва кръгов импорт).

Показва списък от ВЪЗМОЖНОСТИ (мач + пазар), не мачове - един мач може да
се появи 0, 1 или няколко пъти, ако повече от един негов пазар мине
филтъра. Чете директно от predictions_log (вече изчислено от nightly
snapshot / refresh_pending_odds), не смята нищо на живо - евтина заявка,
без API извиквания.

ПРАГОВЕТЕ СА ОТ РЕАЛНИ ДАННИ (Фаза F1, diag_value_edge.py, 2026-08-10):
- pick_pct 25-85%: под 25% edge% е шумен (наблюдавано -72% до +656% в
  същия бин заради малък знаменател), над 85% извадката е твърде рядка
  за да значи нещо.
- edge 3-15%: ГОРНА граница е умишлена, не пропуск. F1 показа, че
  приключилите прогнози с 15%+ edge реално печелят в 24.5% от случаите
  при обещани 39.5% (n=53) - точно обратното на очакваното, ако edge
  просто се сортира низходящо без таван. Най-вероятното обяснение:
  екстремен edge по-често означава че ние сме надценили вероятността,
  не че пазарът е сгрешил. Затова 15%+ НЕ се показва тук - третира се
  като "вероятна грешка в оценката", не като находка.

ЧЕСТНОТО ОГРАНИЧЕНИЕ (виж claude/daily_value_redesign_2026-08-10.md
раздел 3.3): backtest-ите зад PROVEN тавана мерят дали моделът бие
NAIVE BASELINE, не дали бие ЗАТВАРЯЩАТА ПАЗАРНА ЛИНИЯ. Този борд е
ПРОВЕРИМА ХИПОТЕЗА, не доказан инструмент - затова банерът на страницата
казва точно това. Не е нужна отделна snapshot таблица за да се провери
по-късно: всичко, показано тук, вече се пази в predictions_log (market_odds,
our_fair_odds, pick_pct, status) - бъдещ diag_value_edge.py повторен run
директно ще каже дали хипотезата се потвърждава.
"""
from flask import render_template_string
from datetime import datetime

MIN_PCT = 25
MAX_PCT = 85
MIN_EDGE = 3.0
MAX_EDGE = 15.0


def get_value_opportunities(get_conn, is_eligible, hours_ahead=None):
    """Чете от predictions_log, филтрира по прага (виж модулния docstring)
    + предиката is_eligible(league, market_code) - Фаза L.3 (20.08.2026):
    вече se подава prediction_policy.is_proven() тук, не is_publishable().
    /value твърди конкретен edge% - "недостатъчно тествано" (WEAK) пазар с
    твърдение за количествена печалба е двойна несигурност, затова по-
    високата летва (само PROVEN). Само pending (все още неизиграни)
    записи. Връща списък от dict-и, сортирани по edge низходящо."""
    # match_date >= сега, НЕ само status='pending': check-results.timer върви
    # на 3 часа, затова status може все още да казва "pending" няколко часа
    # СЛЕД реалния начален час - бордът не бива да показва вече започнали
    # мачове като "възможност за залог".
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = get_conn()
    conn.row_factory = __import__("sqlite3").Row
    rows = conn.execute("""
        SELECT id, league, fixture_id, match_date, home_team, away_team,
               market_code, pick_label, pick_pct, market_odds, our_fair_odds,
               ROUND((market_odds*1.0/our_fair_odds - 1)*100, 1) AS edge_pct
        FROM predictions_log
        WHERE market_odds IS NOT NULL AND our_fair_odds IS NOT NULL AND our_fair_odds > 0
          AND status = 'pending'
          AND match_date >= ?
          AND pick_pct >= ? AND pick_pct <= ?
          AND (market_odds*1.0/our_fair_odds - 1)*100 >= ?
          AND (market_odds*1.0/our_fair_odds - 1)*100 <= ?
        ORDER BY edge_pct DESC
    """, (now_str, MIN_PCT, MAX_PCT, MIN_EDGE, MAX_EDGE)).fetchall()
    conn.close()
    out = []
    for r in rows:
        if not is_eligible(r["league"], r["market_code"]):
            continue
        out.append(dict(r))
    return out


def register_value_view(app, ctx):
    BASE_STYLE = ctx["BASE_STYLE"]
    SIDEBAR_STYLE = ctx["SIDEBAR_STYLE"]
    SIDEBAR_HTML = ctx["SIDEBAR_HTML"]
    ALL_LEAGUES = ctx["ALL_LEAGUES"]
    LEAGUE_FLAGS = ctx["LEAGUE_FLAGS"]
    market_label = ctx["market_label"]
    to_cyrillic = ctx["to_cyrillic"]
    st = ctx["st"]
    policy = ctx["policy"]

    VALUE_TEMPLATE = _build_template(BASE_STYLE, SIDEBAR_STYLE, SIDEBAR_HTML)

    @app.route("/value")
    def value_view():
        opps = get_value_opportunities(st.get_conn, policy.is_proven)
        for o in opps:
            o["home_cy"] = to_cyrillic(o["home_team"], o["league"])
            o["away_cy"] = to_cyrillic(o["away_team"], o["league"])
            o["league_name"] = ALL_LEAGUES.get(o["league"], {}).get("name", o["league"])
            o["league_flag"] = LEAGUE_FLAGS.get(o["league"], "")
            o["market_name"] = market_label(o["market_code"])
        avg_edge = round(sum(o["edge_pct"] for o in opps) / len(opps), 1) if opps else None
        leagues_count = len(set(o["league"] for o in opps))
        return render_template_string(
            VALUE_TEMPLATE,
            active_page="value", opps=opps, total=len(opps),
            avg_edge=avg_edge, leagues_count=leagues_count,
            min_pct=MIN_PCT, max_pct=MAX_PCT, min_edge=MIN_EDGE, max_edge=MAX_EDGE,
            BASE_STYLE=BASE_STYLE, SIDEBAR_STYLE=SIDEBAR_STYLE, SIDEBAR_HTML=SIDEBAR_HTML,
        )


def _build_template(BASE_STYLE, SIDEBAR_STYLE, SIDEBAR_HTML):
    extra_style = """
      .vv-note { color:var(--sub); font-size:12.5px; margin:0 0 16px; max-width:820px; line-height:1.5; }
      .vv-warn { background:rgba(234,179,8,0.08); border:1px solid rgba(234,179,8,0.25); border-radius:10px;
        padding:12px 14px; color:var(--yellow); font-size:13px; margin-bottom:18px; line-height:1.5; }
      .vv-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(148px,1fr)); gap:10px; margin-bottom:18px; }
      .vv-kpi { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }
      .vv-kpi .k { font-size:11px; color:var(--sub); text-transform:uppercase; letter-spacing:.04em; margin-bottom:5px; }
      .vv-kpi .v { font-size:21px; font-weight:600; font-variant-numeric:tabular-nums; }
      .vv-tblwrap { background:var(--panel); border:1px solid var(--border); border-radius:10px; overflow:auto; margin-bottom:22px; }
      .vv-tblwrap table { border-radius:0; border:none; width:100%; border-collapse:collapse; }
      .vv-tblwrap thead th { background:var(--panel2); color:var(--sub); font-weight:500; font-size:11px;
        text-transform:uppercase; letter-spacing:.04em; white-space:nowrap; padding:9px 12px; text-align:left; }
      .vv-tblwrap td { padding:10px 12px; border-top:1px solid var(--border); font-size:13.5px; }
      .vv-num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
      .vv-teams { font-weight:500; white-space:nowrap; }
      .vv-lg { font-size:11px; color:var(--sub); white-space:nowrap; }
      .vv-edge { color:var(--green); font-weight:600; font-variant-numeric:tabular-nums; }
      .vv-empty { color:var(--sub); font-size:14px; padding:30px; text-align:center; background:var(--panel);
        border:1px solid var(--border); border-radius:10px; }
    """
    body = """
<!DOCTYPE html><html lang="bg"><head><meta charset="UTF-8">
<title>Стойност</title>
<style>""" + BASE_STYLE + SIDEBAR_STYLE + extra_style + """</style></head><body>""" + SIDEBAR_HTML + """
<div class="container" style="max-width:1180px;">
<h1>Стойност</h1>
<div class="vv-warn">
  ⚠️ Експериментален борд, не доказан инструмент. Нашите backtest-и мерят дали моделът бие наивен baseline
  (винаги домакин, винаги над 2.5 и т.н.), не дали бие затварящата пазарна линия на букмейкъра - това е
  много по-висока летва, за която все още нямаме измерване. Прагът тук (вероятност {{min_pct}}-{{max_pct}}%,
  edge {{min_edge}}-{{max_edge}}%) е избран от реално разпределение на данните (не произволно) - над {{max_edge}}%
  edge умишлено НЕ се показва, защото засега по-често означава грешка в нашата оценка, отколкото реална находка.
  Следим резултатите с времето, за да видим дали хипотезата се потвърждава. Показват се само пазари с ниво
  <b>PROVEN</b> (доказано бият baseline при backtest) - недостатъчно тествани (WEAK) пазари не влизат тук, дори
  ако изглеждат с висок edge.
</div>
<div class="vv-kpis">
  <div class="vv-kpi"><div class="k">Възможности</div><div class="v">{{total}}</div></div>
  <div class="vv-kpi"><div class="k">Среден edge</div><div class="v">{% if avg_edge is not none %}{{avg_edge}}%{% else %}-{% endif %}</div></div>
  <div class="vv-kpi"><div class="k">Лиги</div><div class="v">{{leagues_count}}</div></div>
</div>
{% if opps %}
<div class="vv-tblwrap">
<table>
<thead><tr>
  <th>Лига</th><th>Мач</th><th>Начало</th><th>Пазар</th><th>Прогноза</th>
  <th class="vv-num">Увереност</th><th class="vv-num">Коефициент</th><th class="vv-num">Edge</th>
</tr></thead>
<tbody>
{% for o in opps %}
<tr>
  <td class="vv-lg">{{o.league_flag}} {{o.league_name}}</td>
  <td class="vv-teams">{{o.home_cy}} - {{o.away_cy}}</td>
  <td class="vv-lg">{{o.match_date}}</td>
  <td>{{o.market_name}}</td>
  <td>{{o.pick_label}}</td>
  <td class="vv-num">{{"%.1f"|format(o.pick_pct)}}%</td>
  <td class="vv-num">{{o.market_odds}}</td>
  <td class="vv-num vv-edge">+{{o.edge_pct}}%</td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
{% else %}
<div class="vv-empty">Няма възможности в прага в момента - или няма мачове с коефициент в 48-часовия прозорец,
или нищо не минава филтъра точно сега. Провери отново по-късно.</div>
{% endif %}
</div>
</body></html>
"""
    return body
