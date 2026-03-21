#!/bin/bash
set -euo pipefail

# OpenClaw Backup Verification Script
# Checks backup recency, integrity, and disk usage

BACKUP_ROOT="/mnt/data/backups"
MANIFEST="${BACKUP_ROOT}/manifest.json"
DISK_BUDGET_GB=500

# Output JSON result
declare -a DETAILS=()
STATUS="OK"

add_detail() {
    local level="$1"
    local message="$2"
    DETAILS+=("{\"level\": \"$level\", \"message\": \"$message\"}")
    
    # Escalate status if needed
    if [[ "$level" == "FAIL" && "$STATUS" != "FAIL" ]]; then
        STATUS="FAIL"
    elif [[ "$level" == "WARN" && "$STATUS" == "OK" ]]; then
        STATUS="WARN"
    fi
}

# Check if backup system is initialized
if [[ ! -d "$BACKUP_ROOT" ]]; then
    add_detail "FAIL" "Backup root does not exist: $BACKUP_ROOT"
    echo "{\"status\": \"$STATUS\", \"details\": [$(IFS=,; echo "${DETAILS[*]}")]}"
    exit 2
fi

if [[ ! -f "$MANIFEST" ]]; then
    add_detail "FAIL" "Manifest file missing: $MANIFEST"
    echo "{\"status\": \"$STATUS\", \"details\": [$(IFS=,; echo "${DETAILS[*]}")]}"
    exit 2
fi

# Parse manifest
LAST_RUN=$(jq -r '.last_run // empty' "$MANIFEST" 2>/dev/null || echo "")
LAST_HOURLY=$(jq -r '.last_hourly // empty' "$MANIFEST" 2>/dev/null || echo "")
LAST_DAILY=$(jq -r '.last_daily // empty' "$MANIFEST" 2>/dev/null || echo "")
LAST_WEEKLY=$(jq -r '.last_weekly // empty' "$MANIFEST" 2>/dev/null || echo "")

if [[ -z "$LAST_RUN" ]]; then
    add_detail "FAIL" "Manifest missing last_run timestamp"
fi

# Helper: check recency (timestamp, max_hours, label)
check_recency() {
    local timestamp="$1"
    local max_hours="$2"
    local label="$3"
    
    if [[ -z "$timestamp" ]]; then
        add_detail "WARN" "$label: never run"
        return
    fi
    
    local ts_epoch=$(date -d "$timestamp" +%s 2>/dev/null || echo "0")
    local now_epoch=$(date +%s)
    local hours_ago=$(( (now_epoch - ts_epoch) / 3600 ))
    
    if [[ $hours_ago -gt $max_hours ]]; then
        add_detail "FAIL" "$label: too old (${hours_ago}h ago, max ${max_hours}h)"
    else
        add_detail "OK" "$label: recent (${hours_ago}h ago)"
    fi
}

# Check backup recency
check_recency "$LAST_HOURLY" 2 "Hourly backup"
check_recency "$LAST_DAILY" 26 "Daily backup"
check_recency "$LAST_WEEKLY" 192 "Weekly backup"  # 8 days

# Check disk usage
BACKUP_SIZE_BYTES=$(du -sb "$BACKUP_ROOT" 2>/dev/null | cut -f1 || echo "0")
BACKUP_SIZE_GB=$((BACKUP_SIZE_BYTES / 1024 / 1024 / 1024))

if [[ $BACKUP_SIZE_GB -gt $DISK_BUDGET_GB ]]; then
    add_detail "WARN" "Backup disk usage: ${BACKUP_SIZE_GB}GB / ${DISK_BUDGET_GB}GB (over budget)"
elif [[ $BACKUP_SIZE_GB -gt $((DISK_BUDGET_GB * 90 / 100)) ]]; then
    add_detail "WARN" "Backup disk usage: ${BACKUP_SIZE_GB}GB / ${DISK_BUDGET_GB}GB (approaching limit)"
else
    add_detail "OK" "Backup disk usage: ${BACKUP_SIZE_GB}GB / ${DISK_BUDGET_GB}GB"
fi

# Database integrity checks
check_db_integrity() {
    local backup_dir="$1"
    local db_type="$2"  # "sqlite" or "duckdb"
    
    if [[ ! -d "$backup_dir" ]]; then
        add_detail "WARN" "Backup directory not found: $backup_dir"
        return
    fi
    
    # Find most recent backup
    local latest_backup=$(find "$backup_dir" -type f -name "*.gz" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    
    if [[ -z "$latest_backup" ]]; then
        add_detail "WARN" "No backups found in $backup_dir"
        return
    fi
    
    # Only check SQLite integrity (DuckDB doesn't have CLI integrity check)
    if [[ "$db_type" == "sqlite" ]]; then
        # Check the most recent SQLite backup (skip duckdb files)
        latest_backup=$(find "$backup_dir" -type f -name "*.db.gz" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
        if [[ -z "$latest_backup" ]]; then
            add_detail "WARN" "No SQLite backups found in $backup_dir"
            return
        fi
        
        local temp_db=$(mktemp /tmp/backup_verify_XXXXXX.db)
        
        # Uncompress to temp
        if ! gunzip -c "$latest_backup" > "$temp_db" 2>/dev/null; then
            add_detail "FAIL" "Failed to decompress: $(basename "$latest_backup")"
            rm -f "$temp_db"
            return
        fi
        
        # Run integrity check
        local integrity_result=$(sqlite3 "$temp_db" "PRAGMA integrity_check;" 2>&1 || echo "ERROR")
        
        if [[ "$integrity_result" == "ok" ]]; then
            add_detail "OK" "SQLite integrity OK: $(basename "$latest_backup")"
        else
            add_detail "FAIL" "Integrity check failed: $(basename "$latest_backup")"
        fi
        
        rm -f "$temp_db"
    else
        add_detail "OK" "DuckDB backups present in $backup_dir (no CLI integrity check available)"
    fi
}

# Check GFS tiers exist
for tier in hourly daily weekly monthly; do
    local_dir="${BACKUP_ROOT}/databases/${tier}"
    count=$(find "$local_dir" -type f 2>/dev/null | wc -l)
    if [[ "$tier" == "hourly" && $count -eq 0 ]]; then
        add_detail "FAIL" "GFS: no hourly DB backups"
    elif [[ "$tier" != "hourly" && $count -eq 0 ]]; then
        add_detail "OK" "GFS: no ${tier} snapshots yet (will populate over time)"
    else
        add_detail "OK" "GFS: ${count} files in databases/${tier}"
    fi
done

# Check database integrity (most recent hourly)
check_db_integrity "${BACKUP_ROOT}/databases/hourly" "sqlite"
check_db_integrity "${BACKUP_ROOT}/databases/hourly" "duckdb"

# Check if config backup exists
CONFIG_DIR="${BACKUP_ROOT}/config/daily"
if [[ -d "$CONFIG_DIR" ]]; then
    LATEST_CONFIG=$(find "$CONFIG_DIR" -type f -name "*.tar.gz" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    if [[ -n "$LATEST_CONFIG" ]]; then
        # Verify tar integrity
        if tar tzf "$LATEST_CONFIG" >/dev/null 2>&1; then
            add_detail "OK" "Config archive valid: $(basename "$LATEST_CONFIG")"
        else
            add_detail "FAIL" "Config archive corrupt: $(basename "$LATEST_CONFIG")"
        fi
    else
        add_detail "WARN" "No config backups found"
    fi
else
    add_detail "WARN" "Config backup directory missing"
fi

# Output JSON result
echo "{"
echo "  \"status\": \"$STATUS\","
echo "  \"timestamp\": \"$(date -Iseconds)\","
echo "  \"backup_size_gb\": $BACKUP_SIZE_GB,"
echo "  \"details\": ["
for i in "${!DETAILS[@]}"; do
    echo -n "    ${DETAILS[$i]}"
    if [[ $i -lt $((${#DETAILS[@]} - 1)) ]]; then
        echo ","
    else
        echo ""
    fi
done
echo "  ]"
echo "}"

# Exit codes: 0=OK, 1=WARN, 2=FAIL
case "$STATUS" in
    OK) exit 0 ;;
    WARN) exit 1 ;;
    FAIL) exit 2 ;;
esac
