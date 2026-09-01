# Партида 3, т.3.5: тест за сигурност преди commit (01.09.2026)

## Метод

`app.test_client()` (същия Flask instance, текущия код) БЕЗ логин - никаква
сесийна бисквитка изобщо, точно "curl без сесия"/"чист браузър без
бисквитка" от заданието. `GET` към всеки път от списъка в т.3.2 плюс
`/prognozi`, `follow_redirects=False` - записан е реалният статус код и
(при 302) целта на пренасочването.

## Резултат: точно ЕДИН път връща 200 - `/prognozi`. Всички останали - 302 към `/login`.

| Път | Статус | Пренасочване към |
|---|---|---|
| `/` | 302 | `/login?next=/` |
| `/daily` | 302 | `/login?next=/daily` |
| `/live` | 302 | `/login?next=/live` |
| `/value` | 302 | `/login?next=/value` |
| `/results` | 302 | `/login?next=/results` |
| `/my_bets` | 302 | `/login?next=/my_bets` |
| `/manual` | 302 | `/login?next=/manual` |
| `/match_detail` | 302 | `/login?next=/match_detail` |
| `/save_match_note` | 302 | `/login?next=/save_match_note` |
| `/place_bet_market` | 302 | `/login?next=/place_bet_market` |
| `/place_bet_single` | 302 | `/login?next=/place_bet_single` |
| `/place_combo` | 302 | `/login?next=/place_combo` |
| `/system` | 302 | `/login?next=/system` |
| `/system_check` | 302 | `/login?next=/system_check` |
| `/system_check_results` | 302 | `/login?next=/system_check_results` |
| `/check_results` | 302 | `/login?next=/check_results` |
| `/leagues_admin` | 302 | `/login?next=/leagues_admin` |
| `/refresh_all` | 302 | `/login?next=/refresh_all` |
| `/refresh_odds_cache` | 302 | `/login?next=/refresh_odds_cache` |
| `/refresh_injuries_cache` | 302 | `/login?next=/refresh_injuries_cache` |
| `/refresh_odds_cache_manual` | 302 | `/login?next=/refresh_odds_cache_manual` |
| `/refresh_status` | 302 | `/login?next=/refresh_status` |
| `/match_result` | 302 | `/login?next=/match_result` |
| `/diagnostics` | 302 | `/login?next=/diagnostics` |
| `/diagnostics/backup` | 302 | `/login?next=/diagnostics/backup` |
| `/how_it_works` | 302 | `/login?next=/how_it_works` |
| **`/prognozi`** | **200** | — |

API заявки по време на целия тест: **0** (потвърдено през
`api_football.get_call_count()`) - самата проверка не консумира квота.

## Проверка: token-байпасът за cron скриптовете остава непокътнат

`PUBLIC_PATHS`-проверката е добавена в `require_auth()` ПРЕДИ token-логиката
(и двете са ранни `return`-и в самото начало на функцията, не се
изключват взаимно) - потвърдено, че петте `/refresh_*`/`/system_check_
results`/`/check_results` пътя продължават да приемат валиден
`X-Refresh-Token` header без сесия:

| Път (с валиден `X-Refresh-Token`) | Статус |
|---|---|
| `/refresh_odds_cache` | 200 |
| `/refresh_all` | 200 |
| `/system_check_results` | 302 към `/system_check` (нормалното поведение на самия route - POST-обработка, после пренасочване към GET изгледа, НЕ auth отказ - виж `web/admin.py:system_check_results_route()`) |

## Проверка: /prognozi не изтича админски данни (т.3.4)

Рендиран HTML на `/prognozi` (upcoming/finished/skipped табове, ден 0 и ден
4) претърсен за: `Kelly`, `.py`, `model_version`, `EV%`, `traceback`,
`predictions.db`, абсолютни пътища (`/home/inkas`), `REFRESH_TOKEN`,
`API_FOOTBALL_KEY` - нула съвпадения. Отделно: бележките на Дака
(`match_notes.note`) никога не се подават към шаблона в `web/prognozi.py`
(само `skip` булевото поле, за таб "Пропуснати" - показва "Изключен от
прогнозите", без текста на бележката) - потвърдено с код преглед, в базата
в момента на теста нямаше активни бележки с текст за директна проверка на
изхода, но пътят на данните е проверен: `note` полето никъде не се подава
на `render_template()` в `web/prognozi.py`.

## Заключение

Точно едно съвпадение с публичния бял списък (`/prognozi`), никакво
неочаквано 200 другаде - няма нужда от спиране/доклад по т.3.5 ("ако нещо
друго върне 200 - спри и докладвай"). Готово за commit.
