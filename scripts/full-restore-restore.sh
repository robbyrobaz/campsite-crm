#!/usr/bin/env bash
set -euo pipefail

# ── Full OpenClaw Restore ────────────────────────────────────────────
# Restores an OpenClaw installation from a backup snapshot.
#
# Usage:
#   ./full-restore-restore.sh                    # restore latest from GitHub
#   ./full-restore-restore.sh <snapshot.tar.gz>  # restore specific local file
#
# What it restores:
#   ~/.openclaw/workspace/    → your files, memory, skills, projects
#   ~/.openclaw/openclaw.json → gateway config
#   ~/.openclaw/identity/     → device keys
#   ~/.openclaw/agents/       → agent configs
#   ~/.openclaw/cron/         → scheduled jobs
#   ~/.openclaw/credentials/  → stored credentials
#   ~/.openclaw/exec-approvals.json
#
# After restore, restart OpenClaw:
#   openclaw gateway restart
# ──────────────────────────────────────────────────────────────────────

OPENCLAW_DIR="/home/rob/.openclaw"
OWNER="robbyrobaz"
REPO="openclaw-full-restore"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[restore]${NC} $*"; }
warn()  { echo -e "${YELLOW}[restore]${NC} $*"; }
error() { echo -e "${RED}[restore]${NC} $*" >&2; }

# ── Determine snapshot to restore ──

ARCHIVE=""

if [[ "${1:-}" != "" ]]; then
  ARCHIVE="$1"
  if [[ ! -f "$ARCHIVE" ]]; then
    error "File not found: $ARCHIVE"
    exit 1
  fi
  info "Restoring from local file: $ARCHIVE"
else
  info "Fetching latest snapshot from GitHub..."
  TMPDIR="$(mktemp -d)"
  trap 'rm -rf "$TMPDIR"' EXIT

  gh release list -R "$OWNER/$REPO" --limit 1 >/dev/null 2>&1 && {
    warn "No releases found, cloning repo for snapshots..."
  }

  git clone --depth 1 "https://github.com/${OWNER}/${REPO}.git" "$TMPDIR/repo" 2>/dev/null
  ARCHIVE="$(ls -1t "$TMPDIR/repo/snapshots/"*.tar.gz 2>/dev/null | head -1)"

  if [[ -z "$ARCHIVE" ]]; then
    error "No snapshots found in $OWNER/$REPO"
    exit 1
  fi
  info "Latest snapshot: $(basename "$ARCHIVE")"
fi

# ── Verify checksum if manifest exists ──

MANIFEST="${ARCHIVE%.tar.gz}.sha256"
if [[ -f "$MANIFEST" ]]; then
  info "Verifying checksum..."
  if sha256sum -c "$MANIFEST" >/dev/null 2>&1; then
    info "Checksum OK ✓"
  else
    error "Checksum FAILED! Archive may be corrupted."
    read -rp "Continue anyway? (y/N) " ans
    [[ "$ans" =~ ^[Yy] ]] || exit 1
  fi
fi

# ── Back up current state ──

BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$OPENCLAW_DIR/backups/pre-restore-${BACKUP_STAMP}"
info "Backing up current state to $BACKUP_DIR..."
mkdir -p "$BACKUP_DIR"
for item in workspace openclaw.json identity agents cron credentials exec-approvals.json; do
  if [[ -e "$OPENCLAW_DIR/$item" ]]; then
    cp -a "$OPENCLAW_DIR/$item" "$BACKUP_DIR/"
  fi
done
info "Current state backed up ✓"

# ── Restore ──

info "Extracting snapshot..."
tar -xzf "$ARCHIVE" -C "$OPENCLAW_DIR"
info "Restore complete ✓"

echo ""
info "Restored files to $OPENCLAW_DIR"
info "Pre-restore backup saved to: $BACKUP_DIR"
echo ""
warn "Next steps:"
echo "  1. Review restored config: cat $OPENCLAW_DIR/openclaw.json"
echo "  2. Restart OpenClaw:       openclaw gateway restart"
echo "  3. If something is wrong:  cp -a $BACKUP_DIR/* $OPENCLAW_DIR/"
