#!/bin/bash
# ZADACHA_VSICHKO т.5: еднократно в понеделник 12.10.2026 - отчет validation/vsichko_20261012.md (+ _po_liga.csv), commit+push САМО на тях.
# В друг ден не прави нищо (затова е безопасен в crontab). Грешки -> vsichko_report_error.log
cd /home/inkas/sportbg-predictor || exit 1
[ "$(date -u +%F)" = "2026-10-12" ] || exit 0
LOG=vsichko_report_error.log
err() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
files=(validation/vsichko_20261012.md validation/vsichko_20261012_po_liga.csv)
[ -f "${files[0]}" ] && git ls-files --error-unmatch "${files[0]}" >/dev/null 2>&1 && exit 0   # вече направен
out=$(nice -n 15 venv/bin/python3 validation/vsichko_report.py --date 20261012 2>&1) || { err "отчет: $out"; exit 1; }
out=$(git add -- "${files[@]}" 2>&1) || { err "git add: $out"; exit 1; }
out=$(git commit -m "ВСИЧКО: отчет след седмица (12.10.2026)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- "${files[@]}" 2>&1) || { err "git commit: $out"; exit 1; }
out=$(git push origin master 2>&1) || { err "git push: $out"; exit 1; }
