#!/usr/bin/env bash
set -euo pipefail

mkdir -p "$HOME/.config/systemd/user"

cat > "$HOME/.config/systemd/user/openclaw-full-restore-backup.service" <<'EOF'
[Unit]
Description=Create and push OpenClaw full-restore snapshot
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/home/rob/.openclaw/workspace/scripts/full-restore-backup.sh
EOF

cat > "$HOME/.config/systemd/user/openclaw-full-restore-backup.timer" <<'EOF'
[Unit]
Description=Run OpenClaw full-restore snapshot backup every 2 hours

[Timer]
OnBootSec=3min
OnUnitActiveSec=2h
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now openclaw-full-restore-backup.timer
systemctl --user start openclaw-full-restore-backup.service || true
systemctl --user --no-pager status openclaw-full-restore-backup.timer || true
