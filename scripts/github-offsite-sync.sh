#!/usr/bin/env bash
set -euo pipefail

# Sync knowledge-base/ to a dedicated private GitHub repo.
# Requires env vars in github-offsite.env (not committed).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/github-offsite.env}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

: "${GITHUB_OWNER:?Set GITHUB_OWNER in github-offsite.env}"
: "${GITHUB_REPO:?Set GITHUB_REPO in github-offsite.env}"
: "${GITHUB_TOKEN:?Set GITHUB_TOKEN in github-offsite.env}"
: "${GIT_AUTHOR_NAME:=Rob Hartwig}"
: "${GIT_AUTHOR_EMAIL:=rob.hartwig@gmail.com}"
: "${GIT_BRANCH:=main}"

REMOTE_URL="https://${GITHUB_TOKEN}@github.com/${GITHUB_OWNER}/${GITHUB_REPO}.git"

cd "$KB_DIR"

if [[ ! -d .git ]]; then
  git init
  git checkout -b "$GIT_BRANCH"
  git config user.name "$GIT_AUTHOR_NAME"
  git config user.email "$GIT_AUTHOR_EMAIL"
fi

git config user.name "$GIT_AUTHOR_NAME"
git config user.email "$GIT_AUTHOR_EMAIL"

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "$REMOTE_URL"
else
  git remote set-url origin "$REMOTE_URL"
fi

git add -A
if git diff --cached --quiet; then
  echo "No changes to sync"
  exit 0
fi

git commit -m "backup: knowledge-base sync $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push -u origin "$GIT_BRANCH"
echo "Synced knowledge-base to ${GITHUB_OWNER}/${GITHUB_REPO}"
