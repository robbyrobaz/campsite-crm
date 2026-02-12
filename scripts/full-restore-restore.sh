#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-/tmp/openclaw-restore-test}"
STATE_DIR="/home/rob/.openclaw/backups/full-restore"
REPO_DIR="$STATE_DIR/repo"
OWNER="robbyrobaz"
REPO="openclaw-full-restore"
BRANCH="main"
TOKEN="${GITHUB_TOKEN:-$(gh auth token)}"
REMOTE_URL="https://x-access-token:${TOKEN}@github.com/${OWNER}/${REPO}.git"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone "$REMOTE_URL" "$REPO_DIR" >/dev/null
fi

cd "$REPO_DIR"
git remote set-url origin "$REMOTE_URL"
git fetch origin "$BRANCH" >/dev/null
git checkout "$BRANCH" >/dev/null

latest="$(ls -1t snapshots/*.tar.gz | head -n1)"
sha_file="manifests/$(basename "${latest/.tar.gz/.sha256}")"

sha256sum -c "$sha_file"
mkdir -p "$TARGET"
tar -xzf "$latest" -C "$TARGET"
echo "Restored $(basename "$latest") to $TARGET"
