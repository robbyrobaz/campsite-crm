#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$HOME/.config/systemd/user" /home/rob/.openclaw/workspace/systemd
cp /home/rob/.openclaw/workspace/systemd/blofin-dashboard.service "$HOME/.config/systemd/user/"
cp /home/rob/.openclaw/workspace/systemd/ops-kanban-dashboard.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now blofin-dashboard.service ops-kanban-dashboard.service
systemctl --user --no-pager status blofin-dashboard.service ops-kanban-dashboard.service || true
