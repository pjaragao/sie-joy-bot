#!/usr/bin/env bash
# (Re)cria os cron jobs do sie-joy-bot dentro do container.
# Uso: ops/crons.sh --apply
set -euo pipefail
H="docker exec -u hermes sie-joy-bot /opt/hermes/.venv/bin/hermes cron"
JOBS=(
  "resumo-do-dia|30 18 * * *|daily_checkin.py"
  "organizar-arquivos|*/30 8-22 * * *|organizar_arquivos.py"
)
for j in "${JOBS[@]}"; do
  IFS='|' read -r name sched script <<<"$j"
  cmd="$H create \"$sched\" --name $name --script $script --no-agent --deliver local --failure-deliver local"
  if [ "${1:-}" = "--apply" ]; then
    eval "$cmd"
  else
    echo "$cmd"
  fi
done
