# -*- coding: utf-8 -*-
import ast

with open("match_predictor_app.py", encoding="utf-8") as f:
    content = f.read()

old_const = '''MIN_VALUE_BET_PROB = 0.35  # филтър: не показвай value bet под тази наша вероятност
MAX_VALUE_BET_ODDS = 5.0   # филтър: не показвай value bet над този коефициент
KELLY_FRACTION = 0.25      # дробен Kelly (25% от пълния, за защита срещу несигурност на модела)'''

new_const = '''MIN_VALUE_BET_PROB = 0.35  # филтър: не показвай value bet под тази наша вероятност
MAX_VALUE_BET_ODDS = 5.0   # филтър: не показвай value bet над този коефициент
KELLY_FRACTION = 0.25      # дробен Kelly (25% от пълния, за защита срещу несигурност на модела)
# Фаза N.1 (11.08.2026): наблюдавано на живо - моделът даде 44.7% на ЦСКА 1948
# срещу пазарни 21.8% (EV +90%), докато вградената прогноза на API-Football
# даваше 10%. Ликвиден европейски пазар не греши така. Над този праг приемаме,
# че греши НАШИЯТ модел, не пазарът, и не препоръчваме залог - вместо това
# показваме предупреждение (виж distrusted_bets в compute_grouped_markets).
MAX_TRUSTWORTHY_EV = 0.40  # 40% - над това не вярваме на модела си'''

n1 = content.count(old_const)
assert n1 == 1, f"anchor 1 (константи) count: {n1}"
content = content.replace(old_const, new_const, 1)

old_loop = '''
    value_bets = []
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
            kelly_full = (our_p * odd - 1) / (odd - 1) if odd > 1 else 0
            kelly_stake = max(0, kelly_full) * KELLY_FRACTION * 100
            value_bets.append({"label": label, "our_pct": our_p * 100, "market_pct": market_p * 100,
                                 "edge": edge, "odd": odd, "code": code, "ev": ev * 100, "kelly_stake": kelly_stake})
        value_bets.sort(key=lambda x: -x["ev"])

    return groups, (lam, mu, top_label, top_pct, form_note, value_bets)'''

new_loop = '''
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

    return groups, (lam, mu, top_label, top_pct, form_note, value_bets, distrusted_bets)'''

n2 = content.count(old_loop)
assert n2 == 1, f"anchor 2 (value_bets loop) count: {n2}"
content = content.replace(old_loop, new_loop, 1)

old_tpl = '''{% else %}
<div class="top-pick"><div class="top-pick-label">Топ прогноза</div>
<div class="top-pick-row"><span class="top-pick-name">{{extra_info[2]}}</span><span class="top-pick-pct">{{"%.1f"|format(extra_info[3])}}%</span></div></div>
{% endif %}

{% if real_odds %}
<div class="group"><div class="group-title">Реални коефициенти от букмейкъри (осреднени)</div><table>'''

new_tpl = '''{% else %}
<div class="top-pick"><div class="top-pick-label">Топ прогноза</div>
<div class="top-pick-row"><span class="top-pick-name">{{extra_info[2]}}</span><span class="top-pick-pct">{{"%.1f"|format(extra_info[3])}}%</span></div></div>
{% endif %}

{% if extra_info[6] %}
<div class="group" style="border-left:3px solid #D9A64B;">
<div class="group-title">⚠️ Пренебрегнати оценки (твърде високо разминаване с пазара)</div>
{% for db in extra_info[6][:5] %}
<div style="font-size:13px;color:#8A6D1F;padding:6px 0;">
<b>{{db.label}}</b>: моделът дава {{"%.1f"|format(db.our_pct)}}% при пазарни {{"%.1f"|format(db.market_pct)}}% (очаквана печалба +{{"%.1f"|format(db.ev)}}%). Разлика от този порядък обикновено значи грешка в модела, а не пропусната от пазара стойност. Не се препоръчва залог.
</div>
{% endfor %}
</div>
{% endif %}

{% if real_odds %}
<div class="group"><div class="group-title">Реални коефициенти от букмейкъри (осреднени)</div><table>'''

n3 = content.count(old_tpl)
assert n3 == 1, f"anchor 3 (темплейт) count: {n3}"
content = content.replace(old_tpl, new_tpl, 1)

ast.parse(content)

with open("match_predictor_app.py", "w", encoding="utf-8") as f:
    f.write(content)

print("OK - и трите патча приложени успешно, ast.parse мина")
