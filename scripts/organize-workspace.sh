#!/usr/bin/env bash
set -euo pipefail
cd /home/rob/.openclaw/workspace
mkdir -p external-repos
for d in ML_Predict_Assets BTC openclaw tradingview-triggers-1 cloud-code-function-tradingview-triggers-bOvuLu blofin-research; do
  if [[ -d "$d" ]]; then
    mv "$d" external-repos/ 2>/dev/null || true
  fi
done
echo "Workspace organized. External repos in external-repos/."
