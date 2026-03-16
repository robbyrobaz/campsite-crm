#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8780}"

echo "[1/4] healthz"
curl -fsS "$BASE_URL/healthz" | grep -q "ok"

echo "[2/4] summary"
curl -fsS "$BASE_URL/api/summary" >/tmp/blofin_summary.json

echo "[3/4] signals"
curl -fsS "$BASE_URL/api/signals?limit=5" >/tmp/blofin_signals.json

echo "[4/4] ticks"
curl -fsS "$BASE_URL/api/ticks/latest?limit=5" >/tmp/blofin_ticks.json

echo "Smoke test passed for $BASE_URL"
