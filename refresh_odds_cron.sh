#!/bin/bash
# Сигурност, 25.08.2026: токенът вече идва от .env (абсолютен път - това
# скриптче се стартира и от systemd oneshot unit без WorkingDirectory).
source /home/inkas/sportbg-predictor/.env
curl -s -H "X-Refresh-Token: $REFRESH_TOKEN" -X POST http://127.0.0.1:8001/refresh_odds_cache -o /dev/null -w "%{http_code}\n"
# Фаза N.3 (20.08.2026): същият timer (на всеки 30 мин) вече опреснява и
# injuries_cache за близките 48 часа - не изисква нов systemd timer.
curl -s -H "X-Refresh-Token: $REFRESH_TOKEN" -X POST http://127.0.0.1:8001/refresh_injuries_cache -o /dev/null -w "%{http_code}\n"
