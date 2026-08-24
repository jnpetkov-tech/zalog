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
from flask import Blueprint, render_template
from datetime import datetime
import brier_vs_market as bm

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
               market_code, pick_label, pick_pct, market_odds, our_fair_odds, logged_at,
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
        row = dict(r)
        # Точка 2 (разговор с Дака, 24.08.2026): pick_pct тук е "raw" (чист
        # модел) за редове, логнати ПРЕДИ commit 3d52ef5, и "blended"
        # (смесено с пазара) за редове, логнати след това - append-only лог,
        # не се преизчислява ретроактивно. Смесването свива EV към нулата,
        # затова СТАРИТЕ (raw) редове систематично имат по-високо EV -
        # сортирано по edge_pct DESC, върхът на страницата е временно
        # доминиран от по-старото, по-неточно измерване, докато старите
        # чакащи редове не се уредят. Маркираме basis тук изрично, за да се
        # вижда на страницата, не да се крие зад едно сортирано число.
        row["basis"] = "blended" if (row["market_code"] in bm.ALL_CODES
                                      and (row.get("logged_at") or "") >= bm.BLEND_CUTOFF) else "raw"
        out.append(row)
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

    value_bp = Blueprint("value", __name__)

    @value_bp.route("/value")
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
        return render_template(
            "value.html",
            active_page="value", opps=opps, total=len(opps),
            avg_edge=avg_edge, leagues_count=leagues_count,
            min_pct=MIN_PCT, max_pct=MAX_PCT, min_edge=MIN_EDGE, max_edge=MAX_EDGE,
        )

    app.register_blueprint(value_bp)
