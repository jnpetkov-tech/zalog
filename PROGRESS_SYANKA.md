# PROGRESS_SYANKA — пазарът вън + режим „в сянка" на слоя (решения на Дака 01.10.2026)

Решения: (1) `pazar_vun.patch` — ДА; (2) режим „в сянка" 4 седмици — ДА; (3) `sidelined` признаци — НЕ сега.

## ЧАСТ 1 — пазарът вън от логиката и текста
- 1.1 (08:52 UTC): бекъп `data_backups/20261001_pazar_vun/` (pick_selection.py, templates/prognozi.html); `git apply --check` + `git apply validation/pazar_vun.patch`; `ast.parse` ок.
  Тест от симулацията върху живата `predictions.db` (само четене): **844 същото / 73 друга / 0 без / 34 нови** — точно както в симулацията. `evaluation.published_picks()` върху целия лог: 951 мача за 0.4 с.
  В `templates/prognozi.html` — 0 пъти „пазар"/„коефициент".
- 1.2: `pick_selection.py` се внася от Flask (`match_predictor_app`, `web/*`, `evaluation`) и от самостоятелния `build_trust_derived.py` (06:15). `build_predictions_snapshot` го внася само през
  `match_predictor_app` и ползва `rank_candidates`, който не е променен. `internal_guard` се зарежда лениво в try/except — не може да счупи избор. Следващ пуск на снимката: 09:15 UTC — резултатът е записан по-долу.
