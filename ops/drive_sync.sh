#!/usr/bin/env bash
# Envia data/arquivos para o Drive da empresa (pasta WhatsApp). Só copia: nunca apaga no Drive. Inclui o _Restrito (Drive acessível só aos sócios).
set -euo pipefail
exec ~/.local/bin/rclone copy /home/paulojr/sie-joy-bot/data/arquivos drive-empresa:WhatsApp \
  --exclude "_inbox/**" --exclude "_*.lock" --exclude "_estado.json" \
  --exclude "_organizar.lock" --exclude "_notas.lock" --log-level NOTICE "$@"
