#!/bin/sh
# layer_weekly_cron.sh - седмичното преобучение на слоя + пазача (crontab пон 05:20 UTC, под flock /tmp/layer_train.lock).
# ZADACHA_PAZACH_2 (06.10.2026): същото като стария cron ред (layer_train.py && layer_gate.py), плюс известие (notify.py), ако
# преобучението спре с грешка или пазачът спре неочаквано - да не е тихо. Решението на пазача (приета/отхвърлена) и грешка,
# хваната вътре в пазача (код 3), известява самият layer_gate.py. Кодове на layer_gate.py: 0 приета/няма кандидат, 2 отхвърлена,
# 3 грешка (вече известена), друго (напр. 134 - LightGBM уби процеса) -> известие оттук.
cd "$(dirname "$0")" || exit 1
PY=venv/bin/python3
nice -n 19 $PY features/layer_train.py >> layer_train_cron.log 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    $PY notify.py --error "преобучението на слоя (layer_train.py) спря с код $rc - няма нов кандидат, на живо остава текущата версия; виж layer_train_cron.log" >> layer_gate_cron.log 2>&1
    exit $rc
fi
nice -n 19 $PY -W ignore features/layer_gate.py >> layer_gate_cron.log 2>&1
rc=$?
case $rc in
    0|2|3) ;;
    *) $PY notify.py --error "пазачът (layer_gate.py) спря неочаквано с код $rc - current.json не е сменян от него; виж layer_gate_cron.log" >> layer_gate_cron.log 2>&1 ;;
esac
exit $rc
