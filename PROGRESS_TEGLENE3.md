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
- Б1б (проба на всички endpoint-и, ~400 заявки) — върви: `archive/inventar_20261001/b1b_probe.py`.
- Б2 локален инвентар ГОТОВ: `validation/api_nashe_20261001.csv`.
