"""Фаза I.3 (остатък) - wiring на evaluation.py в /results.py.
Замества "ПОЗНАТИ"/"ВЪЗВРЪЩАЕМОСТ" (двата таба) и калибрационната таблица
с честни числа, смятани само върху ПУБЛИКУВАНИТЕ прогнози (виж
evaluation.py от Фаза I.2, wired вече на началната страница във I.3).
Тествано локално с пълна интеграция (Flask test client + синтетични данни,
пресъздаващи диагностиката: 41 corners-само мача, 40 bulgaria2 >=99.5%,
23 здрави мача) - виж claude/ACTION_PLAN.md.
"""
import ast

with open("results_view.py") as f:
    content = f.read()


def apply(content, old, new, label):
    count = content.count(old)
    assert count == 1, f"{label}: anchor count {count} (очаквано 1)"
    return content.replace(old, new, 1)


# 1) import evaluation
content = apply(
    content,
    "from flask import request, render_template_string\nfrom datetime import datetime, date, timedelta\nimport prediction_policy as policy\n",
    "from flask import request, render_template_string\nfrom datetime import datetime, date, timedelta\nimport prediction_policy as policy\nimport evaluation\n",
    "1-import",
)

# 2) смятане на eval_summary в route-а (замества старото calibration_table() извикване)
content = apply(
    content,
    '''        overall = overall_stats(filtered)
        calibration = calibration_table(rows if source == "all" else filtered)
        rmarket = roi_by_market(filtered, market_label)''',
    '''        overall = overall_stats(filtered)
        # Фаза I.3 (остатък): честна метрика само върху ПУБЛИКУВАНИТЕ прогнози
        # (виж evaluation.py, Фаза I.2) - замества calibration_table(), която
        # смяташе директно върху суровия predictions_log (артефакт - виж
        # ACTION_PLAN.md Б.3/opus_review раздел 1).
        eval_summary = evaluation.summary(filtered, policy)
        rmarket = roi_by_market(filtered, market_label)''',
    "2-compute",
)

# 3) render_template_string подава eval_summary вместо calibration
content = apply(
    content,
    "            overall=overall, calibration=calibration, roi_market=rmarket,\n",
    "            overall=overall, eval_summary=eval_summary, roi_market=rmarket,\n",
    "3-kwargs",
)

# 4) таб "Резултати" - KPI плочки Познати/Възвръщаемост
content = apply(
    content,
    '''<div class="rv-kpis">
  <div class="rv-kpi"><div class="k">Приключени</div><div class="v">{{overall.settled}}</div><div class="n">+{{overall.pending}} чакащи</div></div>
  <div class="rv-kpi"><div class="k">Познати</div><div class="v">{% if overall.win_rate is not none %}{{"%.1f"|format(overall.win_rate)}}%{% else %}—{% endif %}</div></div>
  <div class="rv-kpi"><div class="k">Възвръщаемост</div>
    <div class="v {% if overall.roi is not none %}{% if overall.roi>=0 %}rv-pos{% else %}rv-neg{% endif %}{% else %}rv-neu{% endif %}">
      {% if overall.roi is not none %}{{"%+.1f"|format(overall.roi)}}%{% else %}—{% endif %}
    </div>
    <div class="n">на база {{overall.roi_n}} със сигурен коеф.</div>
  </div>
  <div class="rv-kpi"><div class="k">Среден коеф.</div><div class="v">{% if overall.avg_odds %}{{"%.2f"|format(overall.avg_odds)}}{% else %}—{% endif %}</div></div>
</div>

<div class="rv-tblwrap">
<table>
  <thead><tr>
    <th style="width:70px;">Дата</th><th style="width:70px;">Лига</th><th>Мач</th><th style="width:180px;">Прогноза</th>''',
    '''<div class="rv-kpis">
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
    <th style="width:70px;">Дата</th><th style="width:70px;">Лига</th><th>Мач</th><th style="width:180px;">Прогноза</th>''',
    "4-results-tab-kpis",
)

# 5) таб "Ефективност" - KPI плочки + предупреждение за малка извадка
content = apply(
    content,
    '''<div class="rv-kpis">
  <div class="rv-kpi"><div class="k">Познати</div><div class="v">{% if overall.win_rate is not none %}{{"%.1f"|format(overall.win_rate)}}%{% else %}—{% endif %}</div><div class="n">{{overall.settled}} приключени</div></div>
  <div class="rv-kpi"><div class="k">Възвръщаемост</div>
    <div class="v {% if overall.roi is not none %}{% if overall.roi>=0 %}rv-pos{% else %}rv-neg{% endif %}{% else %}rv-neu{% endif %}">
      {% if overall.roi is not none %}{{"%+.1f"|format(overall.roi)}}%{% else %}—{% endif %}
    </div>
    <div class="n">на база {{overall.roi_n}} прогнози с коеф.</div>
  </div>
  <div class="rv-kpi"><div class="k">Чиста печалба</div><div class="v {% if overall.profit>=0 %}rv-pos{% else %}rv-neg{% endif %}">{{"%+.1f"|format(overall.profit)}}</div><div class="n">единици</div></div>
  <div class="rv-kpi"><div class="k">Среден коеф.</div><div class="v">{% if overall.avg_odds %}{{"%.2f"|format(overall.avg_odds)}}{% else %}—{% endif %}</div></div>
</div>

{% if overall.roi_n < 100 %}
<div class="rv-note rv-warn">⚠️ Възвръщаемостта стъпва само на {{overall.roi_n}} прогнози с реален пазарен коефициент (само 1X2 и над/под 2.5 засега имат логнат коефициент) — малка извадка, чети с повишено внимание. Калибрацията долу стъпва на всичките {{overall.settled}} приключени и е по-надежден показател засега.</div>
{% endif %}''',
    '''<div class="rv-kpis">
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
{% endif %}''',
    "5-effectiveness-tab-kpis",
)

# 6) калибрационна таблица - eval_summary.calibration (lo/hi/promised вместо label/predicted)
content = apply(
    content,
    '''  {% for c in calibration %}
    <tr>
      <td>{{c.label}}</td><td class="rv-num">{{c.n}}</td>
      <td class="rv-num rv-dim">{{"%.1f"|format(c.predicted)}}%</td>
      <td class="rv-num">{{"%.1f"|format(c.actual)}}%</td>''',
    '''  {% for c in eval_summary.calibration %}
    <tr>
      <td>{{c.lo}}&ndash;{{100 if c.hi > 100 else c.hi}}%</td><td class="rv-num">{{c.n}}</td>
      <td class="rv-num rv-dim">{{"%.1f"|format(c.promised)}}%</td>
      <td class="rv-num">{{"%.1f"|format(c.actual)}}%</td>''',
    "6-calibration",
)

ast.parse(content)

with open("results_view.py", "w") as f:
    f.write(content)

print("OK - /results вече показва честни числа (Фаза I.3, остатък): "
      "Познати/Възвръщаемост (и двата таба) + калибрационна таблица "
      "от evaluation.summary(), не от суровия predictions_log.")
