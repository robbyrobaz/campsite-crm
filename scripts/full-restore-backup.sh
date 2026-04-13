#!/usr/bin/env bash
set -euo pipefail

# ── Full OpenClaw Backup ──────────────────────────────────────────────
# Backs up only what ISN'T already on its own GitHub repo:
#   - brain/, memory/, scripts, docs, configs
#   - openclaw.json, identity/, agents/ (minus session logs), cron/, credentials/
#   - ai-workshop source (minus projects that graduated to own repos)
#
# Repos with their own remotes are EXCLUDED (already backed up):
#   blofin-stack, campsite-crm, NQ-Trading-PIPELINE, numerai-tournament,
#   kanban-dashboard, master-dashboard, arb-dashboard, gilbert-pd-radio-trainer,
#   jarvis-home-energy
#
# Result: ~5MB tarball, no LFS needed, plain git push.
# Single copy: archive lives in repo dir only (no separate snapshots dir).
# ──────────────────────────────────────────────────────────────────────

OPENCLAW_DIR="/home/rob/.openclaw"
STATE_DIR="$OPENCLAW_DIR/backups/full-restore"
REPO_DIR="$STATE_DIR/repo"
OWNER="robbyrobaz"
REPO="openclaw-full-restore"
BRANCH="main"
KEEP_REMOTE=5    # snapshots kept in git repo

mkdir -p "$STATE_DIR"

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
  mkdir -p "$REPO_DIR" && cd "$REPO_DIR" && git init -b main >/dev/null && git remote add origin "$REMOTE_URL"
fi

cd "$REPO_DIR"
git remote set-url origin "$REMOTE_URL"

# Remove LFS if previously configured — no longer needed
git lfs uninstall >/dev/null 2>&1 || true
rm -f .gitattributes

stamp="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p snapshots manifests

# Build the slim archive directly into the repo dir
archive="snapshots/workspace-${stamp}.tar.gz"
manifest="manifests/workspace-${stamp}.sha256"

# tar exit code 1 = "file changed as we read it" — harmless for live backups
tar -czf "$archive" \
  --exclude='backups' \
  --exclude='completions' \
  --exclude='subagents' \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='.venv-*' \
  --exclude='venv' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.tar.gz' \
  --exclude='*.parquet' \
  --exclude='openclaw.json.bak*' \
  --exclude='workspace/.trash' \
  --exclude='workspace/android-sdk' \
  --exclude='workspace/blofin-stack' \
  --exclude='workspace/blofin-moonshot' \
  --exclude='workspace/blofin-dashboard' \
  --exclude='workspace/campsite-crm' \
  --exclude='workspace/NQ-Trading-PIPELINE' \
  --exclude='workspace/numerai-tournament' \
  --exclude='workspace/kanban-dashboard' \
  --exclude='workspace/master-dashboard' \
  --exclude='workspace/arb-dashboard' \
  --exclude='workspace/gilbert-pd-radio-trainer' \
  --exclude='workspace/jarvis-home-energy' \
  --exclude='workspace/home-energy-os' \
  --exclude='workspace/ai-workshop/projects/campsite-crm' \
  --exclude='workspace/ai-workshop/projects/sports-betting/scraper_env' \
  --exclude='workspace/ai-workshop/projects/sports-betting/_archived' \
  --exclude='agents/main/sessions' \
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

# Prune old snapshots (keep $KEEP_REMOTE)
ls -1t snapshots/*.tar.gz 2>/dev/null | tail -n +$((KEEP_REMOTE + 1)) | xargs -r rm -f
ls -1t manifests/*.sha256  2>/dev/null | tail -n +$((KEEP_REMOTE + 1)) | xargs -r rm -f

git add -A
if git diff --cached --quiet; then
  echo "No snapshot changes"
  exit 0
fi

git config user.name "Rob Hartwig"
git config user.email "rob.hartwig@gmail.com"
git commit -m "backup: full-restore snapshot ${stamp}" >/dev/null

# Prune git history older than 30 days to prevent repo bloat
cutoff_date="$(date -u -d '30 days ago' +%Y-%m-%d)"
git rev-list --all --since="$cutoff_date" | git pack-objects --stdout >/dev/null 2>&1 || true

# Kill stale pushes from previous runs before starting
pkill -f "git-remote-https.*openclaw-full-restore" 2>/dev/null || true
# Push with 180s timeout to prevent hanging CPU hogs
timeout 180 git push --force -u origin "$BRANCH" >/dev/null || {
  echo "WARNING: git push timed out after 180s"
  exit 1
}

# Clean up local git repo after push (remove dangling objects, repack)
git gc --auto --quiet >/dev/null 2>&1 || true

echo "Created + pushed snapshot: $OWNER/$REPO snapshots/workspace-${stamp}.tar.gz ($(du -h "$archive" | cut -f1))"
