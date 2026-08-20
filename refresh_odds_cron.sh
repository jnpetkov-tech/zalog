#!/bin/bash
curl -s -H "X-Refresh-Token: f6d2a9c7e1b84a3f9c05e2d7a1b6f4e8" -X POST http://127.0.0.1:8001/refresh_odds_cache -o /dev/null -w "%{http_code}\n"
# Фаза N.3 (20.08.2026): същият timer (на всеки 30 мин) вече опреснява и
# injuries_cache за близките 48 часа - не изисква нов systemd timer.
curl -s -H "X-Refresh-Token: f6d2a9c7e1b84a3f9c05e2d7a1b6f4e8" -X POST http://127.0.0.1:8001/refresh_injuries_cache -o /dev/null -w "%{http_code}\n"
