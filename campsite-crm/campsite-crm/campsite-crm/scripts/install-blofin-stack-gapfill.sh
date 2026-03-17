#!/usr/bin/env bash
set -euo pipefail
cp /home/rob/.openclaw/workspace/systemd/blofin-stack-gapfill.service "$HOME/.config/systemd/user/"
cp /home/rob/.openclaw/workspace/systemd/blofin-stack-gapfill.timer "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now blofin-stack-gapfill.timer
systemctl --user start blofin-stack-gapfill.service || true
systemctl --user --no-pager status blofin-stack-gapfill.timer || true
