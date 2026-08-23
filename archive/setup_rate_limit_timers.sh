#!/bin/bash
# Еднократен скрипт - слага новия нощен таймер (04:00, incremental_refresh)
# и разминава двата съществуващи 30-минутни таймера с 15 минути.
# Пусни го така: bash setup_rate_limit_timers.sh
# Ще поиска sudo парола (може и два пъти).
set -e

echo "=== 1) Нов юнит: incremental-refresh.service ==="
sudo tee /etc/systemd/system/incremental-refresh.service > /dev/null <<'EOF'
[Unit]
Description=Нощно опресняване на данните (нови мачове + преобучаване на моделите) в 04:00, преди бекъпа/снимката/trust_derived
After=network.target match-predictor-app.service

[Service]
Type=oneshot
User=inkas
WorkingDirectory=/home/inkas/sportbg-predictor
ExecStart=/home/inkas/sportbg-predictor/incremental_refresh_cron.sh
StandardOutput=journal
StandardError=journal
EOF

echo "=== 2) Нов юнит: incremental-refresh.timer (04:00 всяка нощ) ==="
sudo tee /etc/systemd/system/incremental-refresh.timer > /dev/null <<'EOF'
[Unit]
Description=Timer - нощно опресняване на данните в 04:00 (преди 05:00 бекъп, 06:00 снимка, 06:15 trust_derived)

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "=== 3) Пренаписване на refresh-odds.timer - фиксирани :00 и :30 ==="
sudo tee /etc/systemd/system/refresh-odds.timer > /dev/null <<'EOF'
[Unit]
Description=Timer - опресняване на кофициенти на всеки 30 минути

[Timer]
OnCalendar=*-*-* *:0/30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "=== 4) Пренаписване на build-predictions-snapshot.timer - фиксирани :15 и :45 (15 мин разлика) ==="
sudo tee /etc/systemd/system/build-predictions-snapshot.timer > /dev/null <<'EOF'
[Unit]
Description=Timer - предизчисляване на прогнозите на всеки 30 минути

[Timer]
OnCalendar=*-*-* *:15/30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "=== 5) Презареждане на systemd и активиране ==="
sudo systemctl daemon-reload
sudo systemctl enable --now incremental-refresh.timer
sudo systemctl restart refresh-odds.timer
sudo systemctl restart build-predictions-snapshot.timer

echo "=== Готово. Проверка: ==="
systemctl list-timers incremental-refresh.timer refresh-odds.timer build-predictions-snapshot.timer --all
