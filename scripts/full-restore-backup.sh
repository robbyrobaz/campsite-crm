#!/usr/bin/env bash
set -euo pipefail

# ── Full OpenClaw Backup ──────────────────────────────────────────────
# Backs up EVERYTHING needed to restore OpenClaw from scratch:
#   - workspace (your files, memory, skills, projects)
#   - openclaw.json (gateway config)
#   - identity/ (device keys)
#   - agents/ (agent configs)
#   - cron/ (scheduled jobs)
#   - credentials/ (stored credentials)
#   - exec-approvals.json
#
# Excludes: .git, .venv, node_modules, __pycache__, completions, subagents
# Snapshots are pushed to GitHub and pruned locally (keep last 12).
# ──────────────────────────────────────────────────────────────────────

OPENCLAW_DIR="/home/rob/.openclaw"
STATE_DIR="$OPENCLAW_DIR/backups/full-restore"
SNAP_DIR="$STATE_DIR/snapshots"
REPO_DIR="$STATE_DIR/repo"
OWNER="robbyrobaz"
REPO="openclaw-full-restore"
BRANCH="main"
KEEP_LOCAL=12    # local snapshots to retain
KEEP_REMOTE=7    # snapshots kept in git repo

mkdir -p "$SNAP_DIR" "$STATE_DIR"

TOKEN="${GITHUB_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
  TOKEN="$(gh auth token)"
fi

if ! gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  gh repo create "$OWNER/$REPO" --private \
    --description "Full restore snapshots for OpenClaw" \
    --disable-issues --disable-wiki >/dev/null
fi

REMOTE_URL="https://x-access-token:${TOKEN}@github.com/${OWNER}/${REPO}.git"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone "$REMOTE_URL" "$REPO_DIR" >/dev/null 2>&1 || {
    mkdir -p "$REPO_DIR" && cd "$REPO_DIR" && git init >/dev/null && git remote add origin "$REMOTE_URL"
  }
fi

cd "$REPO_DIR"
git remote set-url origin "$REMOTE_URL"
git fetch origin "$BRANCH" >/dev/null 2>&1 || true
git checkout -B "$BRANCH" >/dev/null

# Ensure Git LFS is set up for large snapshots
git lfs install >/dev/null 2>&1 || true
if [[ ! -f .gitattributes ]] || ! grep -q 'snapshots/\*.tar.gz' .gitattributes 2>/dev/null; then
  git lfs track "snapshots/*.tar.gz" >/dev/null 2>&1
  git add .gitattributes
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$SNAP_DIR/workspace-${stamp}.tar.gz"
manifest="$SNAP_DIR/workspace-${stamp}.sha256"

# Build the archive from the OpenClaw root, including config + workspace
# tar exit code 1 = "file changed as we read it" — harmless for live backups
tar -czf "$archive" \
  --exclude='backups' \
  --exclude='completions' \
  --exclude='subagents' \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.tar.gz' \
  --exclude='openclaw.json.bak*' \
  --exclude='workspace/blofin-stack/data/*.db' \
  --exclude='workspace/blofin-stack/data/*.db-wal' \
  --exclude='workspace/blofin-stack/data/*.db-shm' \
  --exclude='workspace/blofin-stack/data/*.jsonl' \
  --exclude='workspace/blofin-stack/data/logs' \
  --exclude='workspace/numerai-tournament/v5.1' \
  --exclude='workspace/numerai-tournament/pickles' \
  --exclude='workspace/android-sdk' \
  --exclude='workspace/.trash' \
  --exclude='*.parquet' \
  -C "$OPENCLAW_DIR" \
  workspace \
  openclaw.json \
  identity \
  agents \
  cron \
  credentials \
  exec-approvals.json \
  || { rc=$?; if [[ $rc -ne 1 ]]; then exit $rc; fi; }

sha256sum "$archive" > "$manifest"

# Copy into git repo
mkdir -p snapshots manifests
cp "$archive" snapshots/
cp "$manifest" manifests/

# Prune old snapshots in git repo (keep $KEEP_REMOTE)
ls -1t snapshots/*.tar.gz 2>/dev/null | tail -n +$((KEEP_REMOTE + 1)) | xargs -r rm -f
ls -1t manifests/*.sha256  2>/dev/null | tail -n +$((KEEP_REMOTE + 1)) | xargs -r rm -f

# Prune old local snapshots (keep $KEEP_LOCAL)
ls -1t "$SNAP_DIR"/workspace-*.tar.gz 2>/dev/null | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm -f
ls -1t "$SNAP_DIR"/workspace-*.sha256  2>/dev/null | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm -f

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
