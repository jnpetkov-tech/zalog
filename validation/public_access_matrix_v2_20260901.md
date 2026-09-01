# Смяна на входните точки, проверка преди commit (01.09.2026)

Повторение на `validation/public_access_matrix_20260901.md`, с добавени
`/`, `/1`, `/admin`, след смяната на входните точки (публичното на корена,
логинът на `/1`, админската начална страница на `/admin`).

## Метод

Същият като миналия път: `app.test_client()` БЕЗ сесия, `GET` към всеки
път, `follow_redirects=False`.

## Резултат: точно ТРИ пътя връщат 200 без сесия - `/`, `/prognozi`, `/1`. Всичко останало - 302 към `/1`.

| Път | Статус | Пренасочване към |
|---|---|---|
| **`/`** | **200** | — (публичната страница, /prognozi изгледът) |
| `/daily` | 302 | `/1?next=/daily` |
| `/live` | 302 | `/1?next=/live` |
| `/value` | 302 | `/1?next=/value` |
| `/results` | 302 | `/1?next=/results` |
| `/my_bets` | 302 | `/1?next=/my_bets` |
| `/manual` | 302 | `/1?next=/manual` |
| `/match_detail` | 302 | `/1?next=/match_detail` |
| `/save_match_note` | 302 | `/1?next=/save_match_note` |
| `/place_bet_market` | 302 | `/1?next=/place_bet_market` |
| `/place_bet_single` | 302 | `/1?next=/place_bet_single` |
| `/place_combo` | 302 | `/1?next=/place_combo` |
| `/system` | 302 | `/1?next=/system` |
| `/system_check` | 302 | `/1?next=/system_check` |
| `/system_check_results` | 302 | `/1?next=/system_check_results` |
| `/check_results` | 302 | `/1?next=/check_results` |
| `/leagues_admin` | 302 | `/1?next=/leagues_admin` |
| `/refresh_all` | 302 | `/1?next=/refresh_all` |
| `/refresh_odds_cache` | 302 | `/1?next=/refresh_odds_cache` |
| `/refresh_injuries_cache` | 302 | `/1?next=/refresh_injuries_cache` |
| `/refresh_odds_cache_manual` | 302 | `/1?next=/refresh_odds_cache_manual` |
| `/refresh_status` | 302 | `/1?next=/refresh_status` |
| `/match_result` | 302 | `/1?next=/match_result` |
| `/diagnostics` | 302 | `/1?next=/diagnostics` |
| `/diagnostics/backup` | 302 | `/1?next=/diagnostics/backup` |
| `/how_it_works` | 302 | `/1?next=/how_it_works` |
| **`/prognozi`** | **200** | — (псевдоним на `/`, СЪЩАТА view функция) |
| **`/1`** | **200** | — (логин формата - очаквано, тя самата е публична по дизайн) |
| **`/admin`** | 302 | `/1?next=/admin` (старата админска начална страница - вече изисква парола, точно както заданието изисква) |

Точно съответства на очакването от заданието: `/`/`/prognozi`/`/1` → 200,
`/admin` → 302 към `/1`, всичко останало от старата матрица → 302 към `/1`
(не към старото `/login`).

## Допълнителни проверки

**`/` и `/prognozi` връщат буквално идентичен HTML** (проверено с директно
сравнение на телата на двата отговора - `==` дава `True`) - потвърждава
"една view функция, два маршрута", не дублиран код.

**Реален вход и redirect по подразбиране:** `POST /1` с валидна парола →
`Location: /admin` (не `/`) - точно т.4 от заданието. Последвана сесийна
`GET /admin` → 200.

**`/robots.txt`** (публичен, но НЕ добавен в `PUBLIC_PATHS` - отделно
изключение в `require_auth()`, по образец на `/static`):

```
User-agent: *
Allow: /$
Disallow: /
```

Позволява индексиране само на `/` (не и на `/prognozi` - псевдоним,
дублирано съдържание). Достъпен без сесия, `Content-Type: text/plain`.

**`/static`** продължава да отдава коректно - тествано с несъществуващ файл
(`/static/nonexistent.css`) → `404` (файлът не съществува), НЕ `302` (не
пита за парола) - механизмът за пропускане на статични файлове е непокътнат.

**Token-байпасът за cron скриптовете** - непокътнат, идентична проверка
като миналия път:

| Път (с валиден `X-Refresh-Token`) | Статус |
|---|---|
| `/refresh_odds_cache` | 200 |
| `/refresh_all` | 200 |

(Тези две реално задействат `run_refresh_odds_cache()`/`run_refresh_all()`
- очаквано ненулев брой реални API заявки по време на теста заради това,
не заради нещо друго - самата проверка на достъпа/белия списък прави 0
заявки.)

## Заключение

Точно три пътя от белия списък връщат 200 без сесия, точно както заданието
изисква; никое друго неочаквано 200. Готово за commit.
