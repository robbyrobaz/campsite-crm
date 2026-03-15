#!/usr/bin/env bash
set -euo pipefail

# Kill any stale git-remote-https from previous runs
pkill -f "git-remote-https.*openclaw-2nd-brain" 2>/dev/null || true
pkill -f "git-remote-https.*blofin-trading-pipeline" 2>/dev/null || true

WORKDIR="/home/rob/.openclaw/workspace"
cd "$WORKDIR"

# Ensure remote exists
if ! git remote get-url second-brain >/dev/null 2>&1; then
  git remote add second-brain https://github.com/robbyrobaz/openclaw-2nd-brain.git
fi

LIST_FILE="/home/rob/.openclaw/workspace/config/backup-paths.txt"
while IFS= read -r p; do
  [[ -z "${p// }" ]] && continue
  [[ "$p" =~ ^# ]] && continue
  if [[ -e "$p" ]]; then
    git add "$p"
  fi
done < "$LIST_FILE"

if git diff --cached --quiet; then
  echo "No code/doc changes to backup"
  exit 0
fi

git config user.name "Rob Hartwig"
git config user.email "rob.hartwig@gmail.com"

stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git commit -m "backup: auto code sync ${stamp}"

# Push with 120s timeout — if it hangs, kill it instead of burning CPU for hours
timeout 120 git push second-brain HEAD:main || {
  echo "WARNING: git push timed out after 120s"
  exit 1
}

echo "Auto code backup sync complete"
