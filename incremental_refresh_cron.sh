#!/bin/bash
# 23.08.2026, rate limit стъпка 3/4: вика живия Flask процес (не отделен
# python скрипт) - за да минава през СЪЩОТО заключване (_try_start_refresh)
# като ръчния бутон "Опресни всички данни" на началната страница.
#
# 23.08.2026 (по-късно същата вечер): повторен опит при провал на curl-а
# (напр. gunicorn се рестартира точно в 04:00 - "connection refused").
# Заключването пази от двойно пускане, значи е безопасно просто да
# пробваме пак - до 3 опита общо, 60 сек пауза между тях (~2 мин прозорец
# вместо нула). Виж CLAUDE_HANDOFF.md, раздел 9, за пълния контекст.
MAX_ATTEMPTS=3
RETRY_DELAY=60
# Сигурност, 25.08.2026: токенът вече идва от .env (абсолютен път - unit-ът
# няма WorkingDirectory).
source /home/inkas/sportbg-predictor/.env
TOKEN="$REFRESH_TOKEN"
URL="http://127.0.0.1:8001/refresh_all"

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    http_code=$(curl -s -H "X-Refresh-Token: $TOKEN" -X POST "$URL" -o /dev/null -w "%{http_code}")
    exit_code=$?
    if [ "$exit_code" -eq 0 ]; then
        echo "$http_code"
        exit 0
    fi
    echo "опит $attempt/$MAX_ATTEMPTS: curl се провали (exit $exit_code)" >&2
    if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
        sleep "$RETRY_DELAY"
    fi
    attempt=$((attempt + 1))
done

echo "провалени всичките $MAX_ATTEMPTS опита" >&2
exit "$exit_code"
