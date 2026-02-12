#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/rob/.openclaw/workspace/blofin-stack"
SYSTEMD_SRC="/home/rob/.openclaw/workspace/systemd"
SYSTEMD_DEST="$HOME/.config/systemd/user"

mkdir -p "$ROOT/data" "$SYSTEMD_DEST"

if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created $ROOT/.env (review and tune settings)"
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
fi

"$ROOT/.venv/bin/pip" install --upgrade pip >/dev/null
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt" >/dev/null

cp "$SYSTEMD_SRC/blofin-stack-ingestor.service" "$SYSTEMD_DEST/"
cp "$SYSTEMD_SRC/blofin-stack-api.service" "$SYSTEMD_DEST/"
cp "$SYSTEMD_SRC/blofin-stack-paper.service" "$SYSTEMD_DEST/"
cp "$SYSTEMD_SRC/kanban-worker.service" "$SYSTEMD_DEST/"
cp "$SYSTEMD_SRC/kanban-dashboard.service" "$SYSTEMD_DEST/"
cp "$SYSTEMD_SRC/auto-code-backup-sync.service" "$SYSTEMD_DEST/"
cp "$SYSTEMD_SRC/auto-code-backup-sync.timer" "$SYSTEMD_DEST/"
cp "$SYSTEMD_SRC/dashboard-health-check.service" "$SYSTEMD_DEST/"
cp "$SYSTEMD_SRC/dashboard-health-check.timer" "$SYSTEMD_DEST/"

systemctl --user daemon-reload
systemctl --user enable --now blofin-stack-ingestor.service blofin-stack-api.service blofin-stack-paper.service kanban-worker.service kanban-dashboard.service auto-code-backup-sync.timer dashboard-health-check.timer

echo "Installed and started blofin-stack services"
systemctl --user --no-pager --full status blofin-stack-ingestor.service || true
systemctl --user --no-pager --full status blofin-stack-api.service || true
systemctl --user --no-pager --full status kanban-worker.service || true

echo "Dashboard URL: http://127.0.0.1:8780/"
