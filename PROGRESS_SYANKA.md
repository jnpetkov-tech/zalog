# PROGRESS_SYANKA — пазарът вън + режим „в сянка" на слоя (решения на Дака 01.10.2026)

Решения: (1) `pazar_vun.patch` — ДА; (2) режим „в сянка" 4 седмици — ДА; (3) `sidelined` признаци — НЕ сега.

## ЧАСТ 1 — пазарът вън от логиката и текста
- 1.1 (08:52 UTC): бекъп `data_backups/20261001_pazar_vun/` (pick_selection.py, templates/prognozi.html); `git apply --check` + `git apply validation/pazar_vun.patch`; `ast.parse` ок.
  Тест от симулацията върху живата `predictions.db` (само четене): **844 същото / 73 друга / 0 без / 34 нови** — точно както в симулацията. `evaluation.published_picks()` върху целия лог: 951 мача за 0.4 с.
  В `templates/prognozi.html` — 0 пъти „пазар"/„коефициент".
- 1.2: `pick_selection.py` се внася от Flask (`match_predictor_app`, `web/*`, `evaluation`) и от самостоятелния `build_trust_derived.py` (06:15). `build_predictions_snapshot` го внася само през
  `match_predictor_app` и ползва `rank_candidates`, който не е променен. `internal_guard` се зарежда лениво в try/except — не може да счупи избор. Следващ пуск на снимката: 09:15 UTC — резултатът е записан по-долу.
- 1.2 РЕЗУЛТАТ: снимката от 09:15 UTC (`build-predictions-snapshot.service`, версия `a7aea1a`) мина без грешка (12 мача, 284 реда, 17 лиги, 6.3 с).
- 1.3: комитнато (`7d29039`), съобщено „готово за рестарт“ — **чака рестарт от Дака** (`sudo systemctl restart match-predictor-app`). Бекъп на оригиналите: `data_backups/20261001_pazar_vun/`.
- 1.4 (след рестарта): `match-predictor-app` рестартиран 01.10.2026 10:18:15 UTC, active; `journalctl` от рестарта — 0 реда error/traceback.
  На живо: `/` 200, `/prognozi` 200, `/prognozi/match/1569953` 200; в HTML на `/prognozi` — 0 пъти „пазар"/„коефициент". `pazar_vun.patch` (`7d29039`) е в живия Flask; `build_trust_derived` го е поемал и преди това.

## ЧАСТ 2 — режим „в сянка" (нищо публично) — работи от 09:04 UTC на 01.10.2026
- 2.1 Таблица `layer_shadow` в `predictions.db` (само добавя; създава се от `layer_shadow.py`): fixture_id, league, match_date (UTC), kickoff_ts, computed_at, mode (pre/final), feature_set (AB/ABC),
  lam/mu/rho на ядрото, lam/mu след слоя, вероятностите по 11-те пазара на мерилото за двете (JSON, суров модел), версия на слоя, git на кода.
- 2.2 `layer_shadow.py` (crontab на всеки 15 мин, `flock`, `nice`, без рестарт): при празен график излиза веднага. **pre** — веднъж на ден след 07:00 UTC за мачове в следващите 72 ч, набор AB;
  **final** — за мачове след 15–100 мин, щом излязат съставите (1 заявка `/fixtures/lineups` + 1 `/injuries?fixture=`, повтаря се на 15 мин), набор ABC. Ядрото = `match_predictor_app.get_models/get_ft_lambdas`
  (същата функция като сайта; внася се лениво — по образец на `build_predictions_snapshot.py`), признаците = `features/build_features.build` (същият код като таблицата).
  Преобучение: `features/layer_train.py` (понеделник 05:20 UTC): ново ядро + нова таблица + два модела (AB, ABC) от ВСИЧКИ минали мачове, версия `дата_githash` в `layer_model/` (старите остават).
  Първа версия: `20261001_7d29039`. Първи записи: 5 pre прогнози (международна пауза — малко мачове).
- 2.3 Данни: дневно опресняване на `{лига}_fixtures.csv` за 2026 (17 заявки, в pre); нови изиграни мачове — съставите/статистиката/събитията идват от вече работещите `fetch_api_sets.py` (ids= батчове) и
  `fetch_fixture_events.py`. **Бюджет — ОЦЕНКА (реалното се мери със `features/layer_shadow_budget.py` след няколко дни):** сянка ≈ 17 + (≤ 2 заявки на мач × ~100 мача) ≈ 220–320/ден, нужните данни ≈ 300/ден,
  живият сайт ≈ 2 000/ден → ≈ 2 700/ден, добре под ~6 000. Внимание: докато тече опашката `predictions/profiles/trophies` на `fetch_api_sets.py` (до ~02.10), оставащата квота пада до резерва — след това тегленията спират.
- 2.4 `features/layer_shadow_report.py` (понеделник 08:30 UTC): отчет `validation/syanka_<дата>.md` САМО при поне 150 уредени мача с „pre“; ядро срещу ядро+слой (Brier, log-loss, калибрация, по лиги, 95% интервали),
  pre и final отделно, england отделна секция, пазарът само справка. Отчетите се комитват от сесия на Claude (cron не комитва).
