#!/usr/bin/env bash
# Uso: ops/drive_client.sh <client_id> <client_secret>
# Troca o client OAuth do remote drive-empresa pelo seu próprio e reautoriza (abre o link de consentimento).
set -euo pipefail
[ $# -eq 2 ] || { echo "uso: $0 <client_id> <client_secret>"; exit 2; }
R=~/.local/bin/rclone
$R config update drive-empresa client_id "$1" client_secret "$2" --non-interactive >/dev/null
echo "Abra o link abaixo (com o túnel SSH ativo) e autorize com a conta da empresa:"
exec $R config reconnect drive-empresa: --auto-confirm
