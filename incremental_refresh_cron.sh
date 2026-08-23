#!/bin/bash
# 23.08.2026, rate limit стъпка 3/4: вика живия Flask процес (не отделен
# python скрипт) - за да минава през СЪЩОТО заключване (_try_start_refresh)
# като ръчния бутон "Опресни всички данни" на началната страница.
curl -s -H "X-Refresh-Token: f6d2a9c7e1b84a3f9c05e2d7a1b6f4e8" -X POST http://127.0.0.1:8001/refresh_all -o /dev/null -w "%{http_code}\n"
