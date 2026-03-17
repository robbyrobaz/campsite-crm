#!/usr/bin/env bash
# Auto-commit tracked project repos
# Runs every hour via cron. Commits all changes (respecting .gitignore).
# Does NOT push — push is handled separately by full-restore backup.
set -euo pipefail

WORKSPACE="/home/rob/.openclaw/workspace"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
COMMITTED=0
SKIPPED=0

GIT_AUTHOR_NAME="Rob Hartwig"
GIT_AUTHOR_EMAIL="rob.hartwig@gmail.com"
export GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

# Projects tracked by master-dashboard (those with local git repos)
PROJECTS=(
  "master-dashboard"
  "blofin-stack"
  "blofin-dashboard"
  "arb-dashboard"
  "kanban-dashboard"
  "numerai-tournament"
  "ai-workshop"
  "campsite-crm"
  "gilbert-pd-radio-trainer"
)

for proj in "${PROJECTS[@]}"; do
  dir="$WORKSPACE/$proj"
  if [[ ! -d "$dir" ]]; then
    echo "SKIP $proj (not found)"
    SKIPPED=$((SKIPPED+1))
    continue
  fi
  if ! git -C "$dir" rev-parse --git-dir &>/dev/null; then
    echo "SKIP $proj (not a git repo)"
    SKIPPED=$((SKIPPED+1))
    continue
  fi

  # Stage everything (respects .gitignore)
  git -C "$dir" add -A

  if git -C "$dir" diff --cached --quiet; then
    echo "CLEAN $proj (nothing to commit)"
    SKIPPED=$((SKIPPED+1))
    continue
  fi

  git -C "$dir" commit -m "auto: snapshot ${STAMP}"
  echo "COMMITTED $proj"
  COMMITTED=$((COMMITTED+1))
done

echo "Done: ${COMMITTED} committed, ${SKIPPED} skipped"
