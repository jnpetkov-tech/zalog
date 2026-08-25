#!/bin/bash
cd /home/inkas/sportbg-predictor
# Поправка 25.08.2026: -u/basic auth тук никога не се е проверявал в
# match_predictor_app.py (require_auth() проверява само сесийна бисквитка
# или X-Refresh-Token за конкретен списък пътища) - двете заявки по-долу
# получаваха 302 вместо реално да проверят резултатите (открито, докладвано,
# сега поправено по образеца на /refresh_all, commit 5bc64a8 - виж
# CLAUDE_HANDOFF.md). Вече праща X-Refresh-Token вместо -u.
source /home/inkas/sportbg-predictor/.env
TS=$(date -Iseconds)
curl -s -H "X-Refresh-Token: $REFRESH_TOKEN" -X POST http://127.0.0.1:8001/system_check_results -o /dev/null -w "%{http_code}"
echo " - system_check_results ($TS)" >> check_results_cron.log
curl -s -H "X-Refresh-Token: $REFRESH_TOKEN" -X POST http://127.0.0.1:8001/check_results -o /dev/null -w "%{http_code}"
echo " - check_results ($TS)" >> check_results_cron.log
