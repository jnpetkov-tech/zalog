#!/bin/bash
# Седмичен cron: commit+push САМО на нов validation/syanka_*.md и validation/pazach_*.md (отчет на пазача, ZADACHA_PAZACH; нищо друго). Грешки -> syanka_commit_error.log
cd /home/inkas/sportbg-predictor || exit 1
LOG=syanka_commit_error.log
err() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
shopt -s nullglob
files=(validation/syanka_*.md validation/pazach_*.md)
[ ${#files[@]} -eq 0 ] && exit 0
# само нови/променени отчети (untracked или различни от HEAD)
changed=$(git status --porcelain -- "${files[@]}" | wc -l)
[ "$changed" -eq 0 ] && exit 0
out=$(git add -- "${files[@]}" 2>&1) || { err "git add: $out"; exit 1; }
# pathspec след -- гарантира, че нищо друго (вече стейджнато) не влиза в commit-а
out=$(git commit -m "СЯНКА/ПАЗАЧ: седмичен отчет ($(date -u +%F))

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" -- "${files[@]}" 2>&1) || { err "git commit: $out"; exit 1; }
out=$(git push origin master 2>&1) || { err "git push: $out"; exit 1; }
