# PROGRESS_TEGLENE3 — дубликати (А) и инвентар на API-то (Б), 01.10.2026

## ЧАСТ А — ГОТОВА (04:55 UTC)
- А1-А2: 8 289 точни копия (champions_league 5 292, portugal 2 997) изтрити; 123 „ключови" повторения оставени (API: id 0, общи id-та,
  двойни записи) — основание във `validation/dubliakti_20261001.md`.
- А3: причина — старото теглене (преди 24.09) дописваше без проверка при застъпващи се пускове. `fetch_player_stats.py` вече проверява
  fixture_id в CSV преди запис (влиза от следващия cron пуск, без рестарт).
- А4: flock, бекъп `data_backups/20261001_dubliakti/`, временен файл + проверка + os.replace. `player_props` — същите числа, рестарт не е нужен.
- А5: `validation/dubliakti_20261001.md` + `.csv`.

## ЧАСТ Б — в ход
- Б1а ГОТОВО: `validation/api_pokritie_20261001.csv` (17 лиги x сезони 2022-2026 = 85 реда, 17 заявки). Всички 17 имат events/lineups/standings/players/
  top_*/predictions за 2022-2026; `statistics_fixtures` липсва за bulgaria2; `statistics_players` липсва за bulgaria2 (и частично bulgaria/portugal2);
  `injuries` само в част от лигите/сезоните; `odds` само за текущия сезон 2026.
- Б1б ГОТОВО: 271 заявки към всеки endpoint (`validation/api_probe_20261001.csv`, полета в `api_probe_fields_20261001.json`).
  Ключови: история — events/lineups от 2010, statistics от 2014, players от 2016, injuries от 2020; **odds за минали мачове: 0 за всички сезони**.
  **Откритие:** `/fixtures?ids=a-b-…` (до 20 мача) връща събития + състави + статистика + играчи в 1 заявка → по-мач набори са 20× по-евтини.
- Б2 локален инвентар ГОТОВ: `validation/api_nashe_20261001.csv`. Б3/Б5 — `validation/api_inventar_20261001.md` (с колона „към датата").
- Б4 (05:05 UTC): `fetch_api_sets.py` (15 набора, самостоятелен, в crontab :27/:57 с flock, без рестарт), tmux `sets` тегли сега. Готово: fixtures,
  injuries, standings, teams. Опашка след това: tops, players_season, team_stats, coachs, transfers, squads, fixtures_full, sidelined, predictions, profiles, trophies
  (~90 хил. заявки; част минава в утрешния ден — cron продължава сам след 00:00 UTC).

### Б4 — състояние 06:00 UTC
- Готови: fixtures 29 467 мача (85 заявки; 91.6% имат съдия), injuries 92 628 записа (49), standings, teams, tops, players_season 93 282 реда, team_stats 2 962,
  coachs, transfers 350 019 реда, squads, **fixtures_full: 25 038 мача (1 291 заявки през `ids=`)** → състави 1 034 061 реда (25 036 мача),
  пълна статистика 23 455 мача, събития 2022–23: 12 174 мача, играчи 2022–23: 9 452 мача.
- Върви: sidelined (17 244 играча). Опашка: predictions 12 864, profiles 17 244, trophies 17 244 (cron :27/:57 продължава сам след изчерпване на квотата).
- 0 пъти 429/пауза/грешка; журнал на приложението чист; /prognozi 33 мс. Проверка: `validation/api_teglene_20261001.csv`.
- Дубликати: контузии 4 384 точни копия — идват от самото API (двоен запис в отговора), оставени в суровия CSV (при съединяване — drop_duplicates);
  състави 316 „по ключ" = стари мачове с играчи без id (bulgaria 2018), не са двоен запис.

### Б — равносметка (07:35 UTC)
- Инвентар и таблица (с колона „към датата"): `validation/api_inventar_20261001.md`; проба на всички endpoint-и: `api_probe_20261001.csv`; покритие по лига-сезон: `api_pokritie_20261001.csv`;
  локален инвентар: `api_nashe_20261001.csv`; резултат от тегленето: раздел 6 + `api_teglene_20261001.csv`.
- Теглено (всички набори с оценка ≤ 25 000 заявки, по приоритет): fixtures, injuries, standings, teams, tops, players_season, team_stats, coachs, transfers, squads, fixtures_full
  (състави/статистика/събития/играчи през `ids=`), sidelined — **готови**; predictions в ход; profiles и trophies на опашка (нисък приоритет, довършват се сами по cron).
- Б5 (дизайн за история на коефициентите, не е правено): раздел 5 на `api_inventar_20261001.md`.
- Нищо не е вързано в модела. 0 пъти 429; сайтът не е засегнат.
