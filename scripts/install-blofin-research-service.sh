#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/rob/.openclaw/workspace/blofin-research"
SERVICE_SRC="$ROOT/systemd/blofin-research.service"
SERVICE_DEST="$HOME/.config/systemd/user/blofin-research.service"

mkdir -p "$ROOT/data" "$HOME/.config/systemd/user"

if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created $ROOT/.env (edit this before live use)"
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
fi

"$ROOT/.venv/bin/pip" install --upgrade pip >/dev/null
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt" >/dev/null

cp "$SERVICE_SRC" "$SERVICE_DEST"
systemctl --user daemon-reload
systemctl --user enable --now blofin-research.service

echo "Installed + started blofin-research.service"
systemctl --user --no-pager --full status blofin-research.service || true
