#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_SCRIPT="$SCRIPT_DIR/github-offsite-sync.sh"
ENV_FILE="$SCRIPT_DIR/github-offsite.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Copy github-offsite.env.example first." >&2
  exit 1
fi

chmod 700 "$SYNC_SCRIPT"
chmod 600 "$ENV_FILE"

sudo tee /etc/systemd/system/openclaw-kb-github-sync.service >/dev/null <<EOF
[Unit]
Description=Sync OpenClaw knowledge-base to GitHub
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=rob
WorkingDirectory=/home/rob/.openclaw/workspace/knowledge-base
Environment=ENV_FILE=$ENV_FILE
ExecStart=$SYNC_SCRIPT
EOF

sudo tee /etc/systemd/system/openclaw-kb-github-sync.timer >/dev/null <<'EOF'
[Unit]
Description=Run knowledge-base GitHub sync every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-kb-github-sync.timer
sudo systemctl start openclaw-kb-github-sync.service || true

echo "Installed timer. Check with: systemctl status openclaw-kb-github-sync.timer"
