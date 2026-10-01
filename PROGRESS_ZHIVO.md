# PROGRESS_ZHIVO — обученият слой влиза в живата прогноза (решение на Дака 01.10.2026)

## КАК СЕ ВРЪЩА НАЗАД (една команда)

```
sed -i 's/^LAYER_LIVE=1/LAYER_LIVE=0/' /home/inkas/sportbg-predictor/.env && sudo systemctl restart match-predictor-app
```

- Снимката (`build_predictions_snapshot.py`, самостоятелна) чете `.env` на всеки пуск → върнатата настройка влиза при следващия цикъл (:15/:45), най-много 30 мин.
  За веднага: `cd /home/inkas/sportbg-predictor && venv/bin/python3 build_predictions_snapshot.py`.
- Flask чете `.env` само при старт → затова е нужен рестартът в същата команда.
- При `LAYER_LIVE=0` изходът е **байт по байт** старият (доказано по-долу, т.1).
- Пълно връщане на кода (ако трябва и кодът да се махне): `git revert <commit-ът на ZHIVO>`; бекъпи на оригиналите: `data_backups/20261001_zhivo/`.

Основа: `validation/sloy_vlizane_20261001.md`. Правила: `football_lib.py` и `prediction_policy.py` НЕ са пипани.

(Разделите по-долу се допълват в хода на работата.)
