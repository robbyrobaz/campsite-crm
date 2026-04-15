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

mkdir -p "$HOME/.config/systemd/user/openclaw-full-restore-backup.service.d"
cat > "$HOME/.config/systemd/user/openclaw-full-restore-backup.service.d/timeout.conf" <<'EOF'
[Service]
TimeoutStartSec=900
EOF

cat > "$HOME/.config/systemd/user/openclaw-full-restore-backup.timer" <<'EOF'
[Unit]
Description=Run OpenClaw full-restore snapshot backup daily

[Timer]
OnBootSec=3min
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now openclaw-full-restore-backup.timer
systemctl --user start openclaw-full-restore-backup.service || true
systemctl --user --no-pager status openclaw-full-restore-backup.timer || true
