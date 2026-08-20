#!/bin/bash
cd /home/inkas/sportbg-predictor
TS=$(date -Iseconds)
curl -s -u sportbg:anton20 -X POST http://127.0.0.1:8001/system_check_results -o /dev/null -w "%{http_code}"
echo " - system_check_results ($TS)" >> check_results_cron.log
curl -s -u sportbg:anton20 -X POST http://127.0.0.1:8001/check_results -o /dev/null -w "%{http_code}"
echo " - check_results ($TS)" >> check_results_cron.log
