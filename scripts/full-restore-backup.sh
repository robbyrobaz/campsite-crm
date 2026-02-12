#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="/home/rob/.openclaw/workspace"
STATE_DIR="/home/rob/.openclaw/backups/full-restore"
SNAP_DIR="$STATE_DIR/snapshots"
REPO_DIR="$STATE_DIR/repo"
OWNER="robbyrobaz"
REPO="openclaw-full-restore"
BRANCH="main"

mkdir -p "$SNAP_DIR" "$STATE_DIR"

TOKEN="${GITHUB_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
  TOKEN="$(gh auth token)"
fi

if ! gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  gh repo create "$OWNER/$REPO" --private --description "Full restore snapshots for OpenClaw workspace" --disable-issues --disable-wiki >/dev/null
fi

REMOTE_URL="https://x-access-token:${TOKEN}@github.com/${OWNER}/${REPO}.git"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone "$REMOTE_URL" "$REPO_DIR" >/dev/null 2>&1 || {
    mkdir -p "$REPO_DIR" && cd "$REPO_DIR" && git init >/dev/null && git remote add origin "$REMOTE_URL";
  }
fi

cd "$REPO_DIR"
git remote set-url origin "$REMOTE_URL"
git fetch origin "$BRANCH" >/dev/null 2>&1 || true
git checkout -B "$BRANCH" >/dev/null

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$SNAP_DIR/workspace-${stamp}.tar.gz"
manifest="$SNAP_DIR/workspace-${stamp}.sha256"

tar -czf "$archive" \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  -C "$WORKSPACE" .
sha256sum "$archive" > "$manifest"

mkdir -p snapshots manifests
cp "$archive" snapshots/
cp "$manifest" manifests/

ls -1t snapshots/*.tar.gz | tail -n +8 | xargs -r rm -f
ls -1t manifests/*.sha256 | tail -n +8 | xargs -r rm -f

git add snapshots manifests
if git diff --cached --quiet; then
  echo "No snapshot changes"
  exit 0
fi

git config user.name "Rob Hartwig"
git config user.email "rob.hartwig@gmail.com"
git commit -m "backup: full-restore snapshot ${stamp}" >/dev/null
git push -u origin "$BRANCH" >/dev/null
echo "Created + pushed snapshot: $OWNER/$REPO snapshots/workspace-${stamp}.tar.gz"
