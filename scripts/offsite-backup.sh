#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEFAULT_ENV_FILE="$SCRIPT_DIR/offsite-backup.env"

usage() {
  cat <<'EOF'
Usage:
  offsite-backup.sh backup [--env <path>] [--dry-run]
  offsite-backup.sh verify [--env <path>] [--dry-run]
  offsite-backup.sh check-config [--env <path>]

Environment file variables (see offsite-backup.env.example):
  KB_SOURCE_DIR           Local source dir (default: <repo>/knowledge-base)
  OFFSITE_SSH_USER        Remote SSH user (required)
  OFFSITE_SSH_HOST        Remote SSH host (required)
  OFFSITE_SSH_PORT        Remote SSH port (default: 22)
  OFFSITE_SSH_KEY         SSH private key path (optional)
  OFFSITE_KNOWN_HOSTS     known_hosts path (optional)
  OFFSITE_DEST_BASE       Remote destination base path (required)
  OFFSITE_BACKUP_LABEL    Remote subdir label (default: hostname)
EOF
}

command_name="${1:-}"
if [[ -z "$command_name" ]]; then
  usage
  exit 1
fi
shift || true

env_file="$DEFAULT_ENV_FILE"
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      env_file="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -f "$env_file" ]]; then
  # shellcheck disable=SC1090
  source "$env_file"
fi

KB_SOURCE_DIR="${KB_SOURCE_DIR:-$REPO_ROOT/knowledge-base}"
OFFSITE_SSH_PORT="${OFFSITE_SSH_PORT:-22}"
OFFSITE_BACKUP_LABEL="${OFFSITE_BACKUP_LABEL:-$(hostname -s)}"

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required setting: $name" >&2
    exit 2
  fi
}

validate_common() {
  if [[ ! -d "$KB_SOURCE_DIR" ]]; then
    echo "KB_SOURCE_DIR does not exist: $KB_SOURCE_DIR" >&2
    exit 2
  fi

  if [[ ! -f "$KB_SOURCE_DIR/README.md" ]]; then
    echo "Safety check failed: expected $KB_SOURCE_DIR/README.md" >&2
    exit 2
  fi

  require_env OFFSITE_SSH_USER
  require_env OFFSITE_SSH_HOST
  require_env OFFSITE_DEST_BASE

  if [[ "$OFFSITE_DEST_BASE" == "/" || "$OFFSITE_DEST_BASE" == "." ]]; then
    echo "Refusing unsafe OFFSITE_DEST_BASE=$OFFSITE_DEST_BASE" >&2
    exit 2
  fi
}

build_ssh_cmd() {
  ssh_cmd=(ssh -p "$OFFSITE_SSH_PORT")

  if [[ -n "${OFFSITE_SSH_KEY:-}" ]]; then
    ssh_cmd+=( -i "$OFFSITE_SSH_KEY" )
  fi

  if [[ -n "${OFFSITE_KNOWN_HOSTS:-}" ]]; then
    ssh_cmd+=( -o UserKnownHostsFile="$OFFSITE_KNOWN_HOSTS" -o StrictHostKeyChecking=yes )
  else
    ssh_cmd+=( -o StrictHostKeyChecking=accept-new )
  fi
}

remote_target() {
  printf '%s@%s:%s/%s/' "$OFFSITE_SSH_USER" "$OFFSITE_SSH_HOST" "$OFFSITE_DEST_BASE" "$OFFSITE_BACKUP_LABEL"
}

run_backup() {
  validate_common
  build_ssh_cmd

  local remote_shell=("${ssh_cmd[@]}")
  local remote_path="$OFFSITE_DEST_BASE/$OFFSITE_BACKUP_LABEL"

  echo "[backup] Source : $KB_SOURCE_DIR/"
  echo "[backup] Remote : $(remote_target)"

  "${remote_shell[@]}" "$OFFSITE_SSH_USER@$OFFSITE_SSH_HOST" "mkdir -p '$remote_path'"

  rsync_opts=(
    --archive
    --compress
    --delete
    --delete-excluded
    --human-readable
    --itemize-changes
    --partial
    --stats
  )

  if [[ $dry_run -eq 1 ]]; then
    rsync_opts+=(--dry-run)
    echo "[backup] Dry-run enabled"
  fi

  rsync "${rsync_opts[@]}" \
    -e "${ssh_cmd[*]}" \
    "$KB_SOURCE_DIR/" \
    "$(remote_target)"

  echo "[backup] Done"
}

run_verify() {
  validate_common
  build_ssh_cmd

  echo "[verify] Checking drift with checksum comparison"
  echo "[verify] Local  : $KB_SOURCE_DIR/"
  echo "[verify] Remote : $(remote_target)"

  rsync_opts=(
    --archive
    --checksum
    --delete
    --itemize-changes
    --human-readable
  )

  if [[ $dry_run -eq 1 ]]; then
    echo "[verify] Dry-run flag set (verify is already non-destructive)"
  fi

  set +e
  verify_output="$(rsync "${rsync_opts[@]}" --dry-run -e "${ssh_cmd[*]}" "$KB_SOURCE_DIR/" "$(remote_target)" 2>&1)"
  rc=$?
  set -e

  if [[ $rc -ne 0 ]]; then
    echo "$verify_output" >&2
    echo "[verify] rsync verification failed" >&2
    exit $rc
  fi

  # Itemized changes start with one of these markers when drift exists.
  if echo "$verify_output" | grep -Eq '^(>f|cd|\*deleting|\.d)'; then
    echo "$verify_output"
    echo "[verify] Drift detected between local and offsite copy" >&2
    exit 3
  fi

  echo "$verify_output"
  echo "[verify] OK: offsite copy matches local checksums"
}

check_config() {
  validate_common
  build_ssh_cmd
  echo "[check-config] OK"
  echo "  env file      : $env_file"
  echo "  source        : $KB_SOURCE_DIR"
  echo "  remote target : $(remote_target)"
}

case "$command_name" in
  backup)
    run_backup
    ;;
  verify)
    run_verify
    ;;
  check-config)
    check_config
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: $command_name" >&2
    usage
    exit 1
    ;;
esac
