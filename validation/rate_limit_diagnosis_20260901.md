# Партида 4: диагноза на rate limiter-а (01.09.2026) — САМО диагноза, кодът НЕ е пипнат

Метод: четене на живите systemd unit/timer файлове (`/etc/systemd/system/*`),
трите `*_cron.sh` скрипта, `journalctl` за конкретни времеви прозорци, `grep`
за "Too many requests"/"429" в `refresh_log.txt`/`odds_refresh_log.txt`/
`injuries_refresh_log.txt`, и `grep -rn "requests\.get\|requests\.post"` за
живия код (изключвайки `archive/` — 157 мъртви скрипта, никога изпълнявани
на живо).

## (а) Вярно ли е "уеб процесът + 4 скрипта = 5 отделни лимитера, 2×280=560"?

**Частично вярно, но структурата е различна от предположението.** Реален
`_rate_limiter` (in-memory `deque`, нулира се при всяко стартиране на
процеса) съществува само в процеси, които **директно импортират
`api_football.py`**:

| Процес | Собствен лимитер? | Кога тръгва |
|---|---|---|
| `match-predictor-app.service` (gunicorn, `--workers 1 --threads 4`, постоянно активен) | ДА — Limiter A, споделен от всичките 4 threads | винаги |
| `build-predictions-snapshot.service` (`python3 build_predictions_snapshot.py`, `Type=oneshot`) | ДА — Limiter B | `*:15/30:00` (на :15 и :45) |
| `nightly-snapshot.service` (`python3 nightly_snapshot.py`, `Type=oneshot`) | ДА — Limiter C | `06:00:00`, веднъж дневно |
| `refresh-pending-odds.service` (`python3 refresh_pending_odds.py`, `Type=oneshot`, самостоятелен `time.sleep(0.3)` между заявки — не знае за другите лимитери) | ДА — Limiter D | `02,08,14,20:00:00` |
| `build-trust-derived.service` | НЕ — не импортира `api_football`/`match_predictor_app` изобщо | 06:15 дневно |
| `db-backup.service` | НЕ — само файлови операции | 05:00 дневно |

**Ключова поправка на предположението:** `refresh_odds_cron.sh`,
`incremental_refresh_cron.sh` и `check_results_cron.sh` **НЕ са отделни
Python процеси с
собствен лимитер** — и трите са чисти `curl` обвивки, викащи ЖИВИЯ
`match-predictor-app` процес по HTTP (`127.0.0.1:8001`) с
`X-Refresh-Token`. Самите `.sh` файлове го документират изрично:
`incremental_refresh_cron.sh` — "вика живия Flask процес (не отделен python
скрипт) - за да минава през СЪЩОТО заключване (`_try_start_refresh`) като
ръчния бутон". Работата им (`run_refresh_odds_cache`/`run_refresh_all`/
`system_tracker.check_results`) се случва ВЪТРЕ в Limiter A — не добавя
пети/шести лимитер.

**Реален брой конкурентни лимитера: до 4 (A/B/C/D), не 5.** Двойка A+B е
най-честата (на всеки 30 мин, но B е нарочно разминат 15 мин от
`refresh-odds.timer`, което само пуска работа ВЪТРЕ в A — виж
CLAUDE_HANDOFF.md, раздел 9, т.4). A+C (06:00, веднъж дневно) и A+D (02/08/
14/20:00, 4x дневно) не са координирани с нищо. При най-лошия случай
(две 280-лимитирани поредици, покриващи се напълно) — до ~560 заявки/мин
към акаунта е теоретично възможно, но виж (в) по-долу защо това вероятно НЕ
е доминиращият механизъм на практика.

## (б) Съвпада ли часът на реалните грешки с фонова задача?

4 реални `"Too many requests. You have exceeded the limit of requests per
minute of your subscription."` грешки в `refresh_log.txt` (пише се от
`run_refresh_all()`, вътре в Limiter A):

| Дата/час на грешката | Най-близка фонова задача | Забележка |
|---|---|---|
| 2026-08-17 06:14:17 | `nightly-snapshot.timer` (06:00:00) | +14 мин — правдоподобно все още активен (Limiter C), но не потвърдено с journalctl (логовете от 17.08 не бяха достъпни за проверка) |
| 2026-08-22 07:59:21 (два пъти подред) | `refresh-odds.timer` + `refresh-pending-odds.timer` (и двата `08:00:00`) | -39 сек до и двата — правдоподобно, ПРЕДИ 23.08 поправките (locking + timer stagger) |
| 2026-08-25 11:52:51 | Първо подозрение: `build-predictions-snapshot.timer` (11:45) — ОПРОВЕРГАНО с `journalctl`: този run приключи в 11:46:32, 6+ мин преди грешката. **Реалната находка:** `journalctl -u match-predictor-app` показва рестарт на gunicorn worker точно в 11:52:14 (37 сек преди грешката) — модел на деня (Раздел 25, `82a589d`, "model_cache изчистени и регенерирани преди рестарта"). Най-вероятно: функционален тест на `/refresh_all` веднага след деплой (протоколът изисква точно това — "рестарт + функционален тест") попадна в burst от несинхронизирани заявки веднага след restart, когато Limiter A е ПРАЗЕН (нулиран от рестарта) |

**Важно за 25.08 случая:** това е ПЪРВАТА потвърдена грешка СЛЕД
rate-limit поправките от 23.08 (Раздели 8-9) — доказва, че самите поправки
(in-process locking + shared limiter + timer stagger) не са достатъчни.
Причината не е "два процеса се сблъскаха" (проверено, не е) — виж (в).

## (в) Кои извиквания правят собствен `requests.get`/`requests.post` и заобикалят `_api_get`?

`grep -rn "requests\.get\|requests\.post\|requests_module\.get"` (изключвайки
`archive/`) намери **6 живи call site-а**, всичките БЕЗ throttling, всичките
вътре в цикли по много елементи наведнъж:

| Файл:ред | Функция | Обхват на един burst | Кой го вика |
|---|---|---|---|
| `incremental_refresh.py:64` | `main()` — `/fixtures` | 1 на лига (×17) | `run_refresh_all()` |
| `incremental_refresh.py:17` | `fetch_fixture_stats()` — `/fixtures/statistics` | 1 на всеки НОВ завършен мач, БЕЗ пауза | `main()`, вика се от `run_refresh_all()` |
| `match_predictor_app.py:710` | `update_injuries_for_league()` — `/injuries` | до 60 на лига × 4 `INJURY_LEAGUES` = **до 240**, БЕЗ пауза | `run_refresh_all()` |
| `system_tracker.py:558` | `check_results()` — `/fixtures` | 1 на всеки уникален pending `fixture_id` — **в момента 191** (проверено живо), БЕЗ пауза | `/system_check_results` (на 3 часа + ръчен бутон) |
| `bets_tracker.py:121` | `check_results()` — `/fixtures` | 1 на всеки pending залог (в момента 7), БЕЗ пауза | `/check_results` |
| `bets_tracker.py:230` | `fetch_fixture_stats()` — `/fixtures/statistics` | при corners/cards/offsides пазар | `bets_tracker.check_results()`/`system_tracker.check_results()` |
| `match_predictor_app.py:1332` | `run_diagnostics()` — `/status` | 1, единично | `/diagnostics` (рядко, нисък риск) |

**Извод, различен от първоначалната хипотеза:** доминиращият риск не е
"N процеса × 280" — той е тези шест call site-а, които изобщо НЕ минават
през `_rate_limiter`. Само `run_refresh_all()` (без нужда от ВТОРИ
конкурентен процес) може да произведе burst от условно **250-400+
непроверени заявки** в рамките на секунди: до 17 (incremental fixtures) +
плюс (по едно на всеки нов завършен мач, непредвидимо, зависи от колко мачове
са се изиграли от последното опресняване) + до 240 (injuries backfill) —
всичко ПРЕДИ третата фаза на `run_refresh_all()` (загряване на кеша), която
единствена минава през `_api_get`. `system_tracker.check_results()` (на
всеки 3 часа) добавя самостоятелно до 191 непроверени заявки в момента,
независимо от `run_refresh_all()`.

Това обяснява 25.08 инцидента по-добре от "два процеса конкурентни" —
не намерих доказателство за втори конкурентен процес в прозореца (виж
(б)), но `run_refresh_all()` (стартирана вероятно ръчно/от функционалния
тест точно след деплоя) съдържа сама по себе си достатъчно unthrottled
обем, за да удари 300/мин.

## Обобщение (само диагноза — НЕ приложена поправка в тази партида)

1. Реалният брой конкурентни in-process лимитера е 4 (A/B/C/D), не 5 — трите
   `.sh` cron скрипта НЕ добавят собствен лимитер, работата им се случва
   вътре в Limiter A.
2. Историческите грешки от ПРЕДИ 23.08 (17.08, 22.08) съвпадат правдоподобно
   с двойно/тройно timer-припокриване — очаквано, вече адресирано частично
   от timer stagger-а.
3. Грешката от 25.08 (СЛЕД поправките) НЕ съвпада с втори конкурентен
   процес — съвпада с рестарт на gunicorn (нулира Limiter A) точно преди
   ръчен `/refresh_all` тест, чиято собствена работа масово заобикаля
   `_api_get` изобщо (т.в).
4. Ако се търси поправка (отделна, бъдеща партида, изрично НЕ тук):
   по-спешно е да минат `incremental_refresh.py`/`update_injuries_for_
   league()`/`system_tracker.check_results()`/`bets_tracker.py` (двете му
   функции) през `_api_get`, отколкото да се прави `_rate_limiter`-ът
   истински между-процесен (файл-базиран/друго) — второто не пази от нищо,
   ако шестте call site-а продължават да го заобикалят изцяло.
