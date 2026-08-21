#!/bin/bash
cd /home/inkas/sportbg-predictor
for lg in portugal champions_league europa_league conference_league; do
    echo "--- $lg ---"
    python3 fetch_player_stats.py $lg 2024
done
