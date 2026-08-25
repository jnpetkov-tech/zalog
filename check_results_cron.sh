#!/bin/bash
cd /home/inkas/sportbg-predictor
# Сигурност, 25.08.2026: паролата вече идва от .env, не е сменена.
# ЗАБЕЛЕЖКА (открита при тази промяна, НЕ поправена - виж CLAUDE_HANDOFF.md):
# -u/basic auth тук не се проверява никъде в match_predictor_app.py
# (before_request проверява само сесийна бисквитка или X-Refresh-Token за
# 3 конкретни /refresh_* пътя) - тези две заявки вероятно получават 302
# (login redirect) вместо реално да проверят резултатите. Отделен проблем
# от тази задача (местене на тайни, не смяна на поведение) - докладвано,
# не пипнато тук.
source /home/inkas/sportbg-predictor/.env
TS=$(date -Iseconds)
curl -s -u "sportbg:$LOGIN_PASSWORD" -X POST http://127.0.0.1:8001/system_check_results -o /dev/null -w "%{http_code}"
echo " - system_check_results ($TS)" >> check_results_cron.log
curl -s -u "sportbg:$LOGIN_PASSWORD" -X POST http://127.0.0.1:8001/check_results -o /dev/null -w "%{http_code}"
echo " - check_results ($TS)" >> check_results_cron.log
