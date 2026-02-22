#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
FRONTEND_BUILD_INDEX="$FRONTEND_DIR/build/index.html"

if [[ ! -f "$FRONTEND_BUILD_INDEX" ]]; then
  echo "[campsite-crm] frontend build missing; building now..."
  (cd "$FRONTEND_DIR" && npm run build)
fi

cd "$BACKEND_DIR"
exec env PORT=3000 SERVE_FRONTEND_BUILD=1 NODE_ENV=production node server.js
