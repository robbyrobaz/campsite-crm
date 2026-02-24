#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_PATH="$UNIT_DIR/campsite-crm.service"

mkdir -p "$UNIT_DIR"

cat > "$UNIT_PATH" <<UNIT
[Unit]
Description=Campsite CRM Always-On Service
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
ExecStart=$ROOT_DIR/scripts/start-live.sh
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now campsite-crm.service

echo "Installed and started: $UNIT_PATH"
systemctl --user status campsite-crm.service --no-pager -n 20
