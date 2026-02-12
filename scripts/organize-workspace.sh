#!/usr/bin/env bash
set -euo pipefail

cd /home/rob/.openclaw/workspace

mkdir -p external-repos brain

# Keep personal knowledge base under brain/
for d in inbox projects decisions learnings weekly templates; do
  if [[ -d "$d" ]]; then
    mv "$d" brain/
  fi
done

# Move non-core scratch clones under external-repos/
for d in ML_Predict_Assets BTC openclaw tradingview-triggers-1 cloud-code-function-tradingview-triggers-bOvuLu; do
  if [[ -d "$d" ]]; then
    mv "$d" external-repos/ 2>/dev/null || true
  fi
done

echo "Workspace organized: brain/ for notes, external-repos/ for clones."
