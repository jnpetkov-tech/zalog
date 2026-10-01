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
