#!/usr/bin/env bash
set -euo pipefail

WORKDIR="/home/rob/.openclaw/workspace"
cd "$WORKDIR"

# Ensure remote exists (read-only if already configured)
if ! git remote get-url second-brain >/dev/null 2>&1; then
  git remote add second-brain https://github.com/robbyrobaz/openclaw-2nd-brain.git
fi

# Keep these in backup scope from config list
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

# Push to same branch tracked from second-brain/main
git push second-brain HEAD:main

echo "Auto code backup sync complete"
