#!/bin/bash
set -euo pipefail

# OpenClaw Comprehensive Backup System
# Usage: backup-all.sh [--hourly|--daily|--weekly|--full|--verify]

BACKUP_ROOT="/mnt/data/backups"
LOG_FILE="${BACKUP_ROOT}/backup.log"
MANIFEST="${BACKUP_ROOT}/manifest.json"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Ensure backup root and log exist
mkdir -p "${BACKUP_ROOT}"
touch "${LOG_FILE}"

# Logging function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

log "=== Backup started: $TIMESTAMP ==="

# Parse arguments
MODE="hourly"
VERIFY_ONLY=false
if [[ $# -gt 0 ]]; then
    case "$1" in
        --hourly) MODE="hourly" ;;
        --daily) MODE="daily" ;;
        --weekly) MODE="weekly" ;;
        --full) MODE="full" ;;
        --verify) VERIFY_ONLY=true ;;
        *) log "ERROR: Unknown flag $1"; exit 1 ;;
    esac
fi

log "Mode: ${MODE}"

# Track backup stats
declare -a CREATED_FILES=()
TOTAL_SIZE=0
ERRORS=0

# Check if we need tier2 (models/data) based on last run
should_run_tier2() {
    if [[ ! -f "${MANIFEST}" ]]; then
        return 0  # First run
    fi
    
    local last_weekly=$(jq -r '.last_weekly // empty' "${MANIFEST}" 2>/dev/null || echo "")
    if [[ -z "$last_weekly" ]]; then
        return 0
    fi
    
    local last_epoch=$(date -d "$last_weekly" +%s 2>/dev/null || echo "0")
    local now_epoch=$(date +%s)
    local days_diff=$(( (now_epoch - last_epoch) / 86400 ))
    
    [[ $days_diff -ge 7 ]]
}

# Retention cleanup function
# ========== GFS RETENTION (Grandfather-Father-Son) ==========
# Son    = recent hourly backups (keep last 6 = ~6 hours of coverage)
# Father = 1 daily snapshot kept per day (keep last 7 days)
# Grand  = 1 weekly snapshot (keep last 4 weeks)
# Great  = 1 monthly snapshot (keep last 3 months)
#
# Promotion: before deleting an old Son, check if it's the last one for its
# day/week/month — if so, move it to the Father/Grand/Great tier.

gfs_rotate() {
    local base_dir="$1"       # e.g. /mnt/data/backups/databases
    local hourly_dir="${base_dir}/hourly"
    local daily_dir="${base_dir}/daily"
    local weekly_dir="${base_dir}/weekly"
    local monthly_dir="${base_dir}/monthly"

    mkdir -p "$hourly_dir" "$daily_dir" "$weekly_dir" "$monthly_dir"

    [[ ! -d "$hourly_dir" ]] && return

    local KEEP_HOURLY=6    # ~6 hours of Son backups
    local KEEP_DAILY=7     # 7 Father snapshots (1 per day)
    local KEEP_WEEKLY=4    # 4 Grandfather snapshots (1 per week)
    local KEEP_MONTHLY=3   # 3 Great-grandfather snapshots (1 per month)

    # --- Group hourly files by timestamp prefix (YYYYMMDD_HHMMSS) ---
    # Each hourly run creates multiple files sharing the same timestamp.
    # We work in "sets" grouped by timestamp.

    # Get unique timestamps from filenames, sorted newest first
    local -a timestamps=()
    while IFS= read -r ts; do
        [[ -n "$ts" ]] && timestamps+=("$ts")
    done < <(ls "$hourly_dir" 2>/dev/null | grep -oP '\d{8}_\d{6}' | sort -ru)

    local total_sets=${#timestamps[@]}
    if [[ $total_sets -le $KEEP_HOURLY ]]; then
        log "  GFS: $total_sets hourly sets, keeping all (≤$KEEP_HOURLY)"
    else
        log "  GFS: $total_sets hourly sets, trimming to $KEEP_HOURLY"

        # Timestamps to remove (oldest beyond KEEP_HOURLY)
        local -a old_timestamps=("${timestamps[@]:$KEEP_HOURLY}")

        for old_ts in "${old_timestamps[@]}"; do
            local day_str="${old_ts:0:8}"   # YYYYMMDD
            local year_month="${old_ts:0:6}" # YYYYMM

            # Check: is there already a daily for this day?
            local has_daily=$(find "$daily_dir" -name "*_${day_str}*" -type f 2>/dev/null | head -1)

            if [[ -z "$has_daily" ]]; then
                # Promote one file per DB to daily (this is the Father)
                log "  GFS: promoting $old_ts → daily (day $day_str)"
                for f in "$hourly_dir"/*"${old_ts}"*; do
                    [[ -f "$f" ]] && cp "$f" "$daily_dir/"
                done
            fi

            # Delete the hourly set
            for f in "$hourly_dir"/*"${old_ts}"*; do
                [[ -f "$f" ]] && rm -f "$f"
            done
        done
    fi

    # --- Trim daily: keep KEEP_DAILY, promote oldest to weekly ---
    local -a daily_days=()
    while IFS= read -r d; do
        [[ -n "$d" ]] && daily_days+=("$d")
    done < <(ls "$daily_dir" 2>/dev/null | grep -oP '\d{8}' | sort -ru | uniq)

    if [[ ${#daily_days[@]} -gt $KEEP_DAILY ]]; then
        local -a old_days=("${daily_days[@]:$KEEP_DAILY}")
        for old_day in "${old_days[@]}"; do
            # Get ISO week for this day
            local iso_week=$(date -d "${old_day:0:4}-${old_day:4:2}-${old_day:6:2}" +%G-W%V 2>/dev/null || echo "")
            local has_weekly=$(find "$weekly_dir" -name "*_${old_day}*" -type f 2>/dev/null | head -1)

            if [[ -z "$has_weekly" && -n "$iso_week" ]]; then
                # Check if we already have a snapshot for this ISO week
                local week_start=$(date -d "${old_day:0:4}-${old_day:4:2}-${old_day:6:2}" +%G%V 2>/dev/null || echo "0")
                local existing_week_snap=$(ls "$weekly_dir" 2>/dev/null | grep -oP '\d{8}' | while read wd; do
                    local wk=$(date -d "${wd:0:4}-${wd:4:2}-${wd:6:2}" +%G%V 2>/dev/null || echo "x")
                    [[ "$wk" == "$week_start" ]] && echo "yes"
                done | head -1)

                if [[ -z "$existing_week_snap" ]]; then
                    log "  GFS: promoting daily $old_day → weekly"
                    for f in "$daily_dir"/*"${old_day}"*; do
                        [[ -f "$f" ]] && cp "$f" "$weekly_dir/"
                    done
                fi
            fi

            # Delete old daily files for this day
            for f in "$daily_dir"/*"${old_day}"*; do
                [[ -f "$f" ]] && rm -f "$f"
            done
        done
    fi

    # --- Trim weekly: keep KEEP_WEEKLY, promote oldest to monthly ---
    local -a weekly_days=()
    while IFS= read -r d; do
        [[ -n "$d" ]] && weekly_days+=("$d")
    done < <(ls "$weekly_dir" 2>/dev/null | grep -oP '\d{8}' | sort -ru | uniq)

    if [[ ${#weekly_days[@]} -gt $KEEP_WEEKLY ]]; then
        local -a old_weeks=("${weekly_days[@]:$KEEP_WEEKLY}")
        for old_w in "${old_weeks[@]}"; do
            local year_month="${old_w:0:6}"
            local has_monthly=$(find "$monthly_dir" -name "*${year_month}*" -type f 2>/dev/null | head -1)

            if [[ -z "$has_monthly" ]]; then
                log "  GFS: promoting weekly $old_w → monthly"
                for f in "$weekly_dir"/*"${old_w}"*; do
                    [[ -f "$f" ]] && cp "$f" "$monthly_dir/"
                done
            fi

            for f in "$weekly_dir"/*"${old_w}"*; do
                [[ -f "$f" ]] && rm -f "$f"
            done
        done
    fi

    # --- Trim monthly: keep KEEP_MONTHLY ---
    local -a monthly_months=()
    while IFS= read -r d; do
        [[ -n "$d" ]] && monthly_months+=("$d")
    done < <(ls "$monthly_dir" 2>/dev/null | grep -oP '\d{6}' | sort -ru | uniq)

    if [[ ${#monthly_months[@]} -gt $KEEP_MONTHLY ]]; then
        local -a old_months=("${monthly_months[@]:$KEEP_MONTHLY}")
        for old_m in "${old_months[@]}"; do
            log "  GFS: deleting monthly $old_m (beyond $KEEP_MONTHLY month retention)"
            for f in "$monthly_dir"/*"${old_m}"*; do
                [[ -f "$f" ]] && rm -f "$f"
            done
        done
    fi

    # Report
    local h_count=$(ls "$hourly_dir" 2>/dev/null | grep -oP '\d{8}_\d{6}' | sort -u | wc -l)
    local d_count=$(ls "$daily_dir" 2>/dev/null | wc -l)
    local w_count=$(ls "$weekly_dir" 2>/dev/null | wc -l)
    local m_count=$(ls "$monthly_dir" 2>/dev/null | wc -l)
    log "  GFS status: ${h_count} hourly sets, ${d_count} daily, ${w_count} weekly, ${m_count} monthly"
}

# Legacy wrapper for non-DB dirs (configs, models, data — simple count-based)
cleanup_old_backups() {
    local dir="$1"
    local keep_count="$2"
    
    if [[ ! -d "$dir" ]]; then
        return
    fi
    
    local file_count=$(find "$dir" -type f | wc -l)
    if [[ $file_count -gt $keep_count ]]; then
        log "  Cleaning up old backups in $dir (keep $keep_count)"
        find "$dir" -type f -printf '%T@ %p\n' | sort -rn | tail -n +$((keep_count + 1)) | cut -d' ' -f2- | while read -r old_file; do
            log "  Removing old backup: $(basename "$old_file")"
            rm -f "$old_file"
        done
    fi
}

# Check if sqlite3 is available
if ! command -v sqlite3 &>/dev/null; then
    log "ERROR: sqlite3 CLI not found. Installing..."
    sudo apt-get update && sudo apt-get install -y sqlite3 || {
        log "ERROR: Failed to install sqlite3"
        exit 1
    }
fi

# ========== TIER 1: DATABASE BACKUPS ==========
backup_databases() {
    log "--- Database Backups (Tier 1) ---"
    local db_dir="${BACKUP_ROOT}/databases/hourly"
    mkdir -p "$db_dir"
    
    # GFS rotation FIRST — prune old backups before writing new ones
    # This ensures rotation runs even if blofin_monitor backup takes forever
    gfs_rotate "${BACKUP_ROOT}/databases"
    
    # SQLite databases (use sqlite3 .backup - WAL safe)
    # NOTE: blofin_monitor.db moved to end with lock check (takes 80-100+ min)
    local -a SQLITE_DBS=(
        "/home/rob/.openclaw/workspace/blofin-moonshot-v2/data/moonshot_v2.db"
        "/home/rob/.openclaw/workspace/blofin-moonshot/data/moonshot.db"
        "/home/rob/.openclaw/workspace/kanban-dashboard/kanban.sqlite"
        "/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/data/nq_pipeline.db"
        "/home/rob/.openclaw/workspace/jarvis-home-energy/energy_data.db"
        "/home/rob/.openclaw/workspace/ninja_trader_strategies/data/nq_pipeline.db"
        "/home/rob/.openclaw/workspace/blofin-stack/data/paper_trading.db"
        "/mnt/data/market_macro.db"
        "/mnt/data/backtest_results.db"
        "/home/rob/.openclaw/workspace/ai-workshop/projects/sports-betting/data/betting.db"
        "/home/rob/.openclaw/memory/main.sqlite"
        "/home/rob/.openclaw/memory/nq.sqlite"
        "/home/rob/.openclaw/memory/crypto.sqlite"
    )
    
    for db in "${SQLITE_DBS[@]}"; do
        if [[ ! -f "$db" ]]; then
            log "  SKIP: $db (not found)"
            continue
        fi
        
        local db_name=$(basename "$db")
        local backup_path="${db_dir}/${db_name%.db}_${TIMESTAMP}.db"
        
        log "  Backing up SQLite: $db_name"
        if sqlite3 "$db" ".backup '$backup_path'" 2>>"${LOG_FILE}"; then
            log "    Created: $backup_path"
            gzip -f "$backup_path"
            local gz_file="${backup_path}.gz"
            CREATED_FILES+=("$gz_file")
            TOTAL_SIZE=$((TOTAL_SIZE + $(stat -f%z "$gz_file" 2>/dev/null || stat -c%s "$gz_file")))
        else
            log "    ERROR: Failed to backup $db_name"
            ERRORS=$((ERRORS + 1))
        fi
    done
    
    # DuckDB databases (use cp with fuser check)
    local -a DUCKDB_DBS=(
        "/home/rob/infrastructure/ibkr/data/nq_feed.duckdb"
        "/home/rob/.openclaw/workspace/hyperliquid-sp500-pipeline/data/sp500_pipeline.duckdb"
        "/home/rob/.openclaw/workspace/hyperliquid-sp500-pipeline/data/sp500_pipeline_training.duckdb"
        "/home/rob/infrastructure/ibkr/data/ibkr_options.duckdb"
        "/home/rob/infrastructure/ibkr/data/options.duckdb"
    )
    
    for db in "${DUCKDB_DBS[@]}"; do
        if [[ ! -f "$db" ]]; then
            log "  SKIP: $db (not found)"
            continue
        fi
        
        local db_name=$(basename "$db")
        local backup_path="${db_dir}/${db_name%.duckdb}_${TIMESTAMP}.duckdb"
        
        # Check if file is open
        if command -v fuser &>/dev/null && fuser "$db" 2>/dev/null; then
            log "  WARN: $db_name is in use, waiting 5s..."
            sleep 5
        fi
        
        log "  Backing up DuckDB: $db_name"
        if cp "$db" "$backup_path" 2>>"${LOG_FILE}"; then
            log "    Created: $backup_path"
            gzip -f "$backup_path"
            local gz_file="${backup_path}.gz"
            CREATED_FILES+=("$gz_file")
            TOTAL_SIZE=$((TOTAL_SIZE + $(stat -f%z "$gz_file" 2>/dev/null || stat -c%s "$gz_file")))
        else
            log "    ERROR: Failed to backup $db_name"
            ERRORS=$((ERRORS + 1))
        fi
    done
    
    # Backup blofin_monitor.db LAST with lock check (takes 80-100+ min)
    local blofin_db="/mnt/data/blofin_monitor.db"
    local blofin_lock="${BACKUP_ROOT}/.blofin_backup.lock"
    if [[ -f "$blofin_db" ]]; then
        # Skip if another blofin_monitor backup is already running
        if [[ -f "$blofin_lock" ]] && kill -0 "$(cat "$blofin_lock" 2>/dev/null)" 2>/dev/null; then
            log "  SKIP: blofin_monitor.db (another backup in progress, PID $(cat "$blofin_lock"))"
        else
            echo $$ > "$blofin_lock"
            local backup_path="${db_dir}/blofin_monitor_${TIMESTAMP}.db"
            log "  Backing up SQLite: blofin_monitor.db (large — may take 60-100+ min)"
            if sqlite3 "$blofin_db" ".backup '$backup_path'" 2>>"${LOG_FILE}"; then
                log "    Created: $backup_path"
                CREATED_FILES+=("$backup_path")
                TOTAL_SIZE=$((TOTAL_SIZE + $(stat -c%s "$backup_path" 2>/dev/null || echo 0)))
            else
                log "    ERROR: Failed to backup blofin_monitor.db"
                ERRORS=$((ERRORS + 1))
            fi
            rm -f "$blofin_lock"
        fi
    fi
}

# ========== TIER 1: CONFIG BACKUPS ==========
backup_configs() {
    log "--- Config Backups (Tier 1) ---"
    local config_dir="${BACKUP_ROOT}/config/daily"
    mkdir -p "$config_dir"
    
    local archive_path="${config_dir}/openclaw_config_${TIMESTAMP}.tar.gz"
    
    log "  Creating config archive..."
    
    # Stage everything into a temp dir, then tar it in one shot
    local staging=$(mktemp -d)
    trap "rm -rf $staging" RETURN
    
    local HOME_DIR="$HOME"
    local OC="$HOME_DIR/.openclaw"
    local WS="$OC/workspace"
    
    # OpenClaw core configs
    mkdir -p "$staging/openclaw"
    [[ -f "$OC/openclaw.json" ]] && cp "$OC/openclaw.json" "$staging/openclaw/"
    [[ -d "$OC/identity" ]] && cp -r "$OC/identity" "$staging/openclaw/"
    [[ -d "$OC/credentials" ]] && cp -r "$OC/credentials" "$staging/openclaw/"
    
    # Cron configs (exclude runs/)
    if [[ -d "$OC/cron" ]]; then
        mkdir -p "$staging/openclaw/cron"
        find "$OC/cron" -maxdepth 1 -not -name "runs" -not -path "$OC/cron" -exec cp -r {} "$staging/openclaw/cron/" \;
    fi
    
    # Agent configs (all 4 agents)
    for agent_dir in "$OC"/agents/*/agent; do
        if [[ -d "$agent_dir" ]]; then
            local agent_name=$(basename "$(dirname "$agent_dir")")
            mkdir -p "$staging/agents/$agent_name"
            cp -r "$agent_dir" "$staging/agents/$agent_name/"
        fi
    done
    
    # Workspace brain, memory, scripts, runbooks
    mkdir -p "$staging/workspace"
    for dir in brain memory scripts runbooks; do
        [[ -d "$WS/$dir" ]] && cp -r "$WS/$dir" "$staging/workspace/"
    done
    
    # Workspace markdown files
    for md_file in "$WS"/*.md; do
        [[ -f "$md_file" ]] && cp "$md_file" "$staging/workspace/"
    done
    
    # Systemd user units
    mkdir -p "$staging/systemd"
    for unit_file in "$HOME_DIR/.config/systemd/user"/*.service "$HOME_DIR/.config/systemd/user"/*.timer; do
        [[ -f "$unit_file" ]] && cp "$unit_file" "$staging/systemd/"
    done
    
    # Session logs (conversation history)
    for agent in main nq crypto church; do
        local sess_dir="$OC/agents/$agent/sessions"
        if [[ -d "$sess_dir" ]]; then
            mkdir -p "$staging/sessions/$agent"
            cp "$sess_dir"/*.jsonl "$staging/sessions/$agent/" 2>/dev/null || true
            cp "$sess_dir"/sessions.json "$staging/sessions/$agent/" 2>/dev/null || true
        fi
    done
    
    # All .env files (excluding .venv/)
    mkdir -p "$staging/env-files"
    while IFS= read -r -d '' env_file; do
        local rel_dir=$(dirname "$env_file" | sed "s|$WS/||")
        mkdir -p "$staging/env-files/$rel_dir"
        cp "$env_file" "$staging/env-files/$rel_dir/"
    done < <(find "$WS" -name ".env" -not -path "*/.venv/*" -not -path "*/node_modules/*" -print0 2>/dev/null)
    
    # Create archive from staging dir
    if tar czf "$archive_path" -C "$staging" . 2>>"${LOG_FILE}"; then
        log "    Created: $archive_path ($(du -h "$archive_path" | cut -f1))"
        CREATED_FILES+=("$archive_path")
        TOTAL_SIZE=$((TOTAL_SIZE + $(stat -c%s "$archive_path" 2>/dev/null || echo 0)))
    else
        log "    ERROR: Failed to create config archive"
        ERRORS=$((ERRORS + 1))
    fi
    
    rm -rf "$staging"
    
    # Cleanup old daily configs (keep last 30)
    cleanup_old_backups "$config_dir" 30
}

# ========== TIER 2: ML MODELS ==========
backup_models() {
    log "--- ML Model Backups (Tier 2) ---"
    local models_dir="${BACKUP_ROOT}/models/weekly"
    mkdir -p "$models_dir"
    
    local -a MODEL_DIRS=(
        "/home/rob/.openclaw/workspace/blofin-moonshot-v2/models"
        "/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/ml/models"
        "/home/rob/.openclaw/workspace/hyperliquid-sp500-pipeline/ml/models"
        "/home/rob/.openclaw/workspace/numerai-tournament/models_elite"
        "/home/rob/.openclaw/workspace/numerai-tournament/models_robbyrob3"
    )
    
    for model_dir in "${MODEL_DIRS[@]}"; do
        if [[ ! -d "$model_dir" ]]; then
            log "  SKIP: $model_dir (not found)"
            continue
        fi
        
        local dir_name=$(basename "$model_dir")
        local parent_name=$(basename "$(dirname "$model_dir")")
        local archive_name="${parent_name}_${dir_name}_${TIMESTAMP}.tar.gz"
        local archive_path="${models_dir}/${archive_name}"
        
        log "  Backing up models: $parent_name/$dir_name"
        if tar czf "$archive_path" -C "$(dirname "$model_dir")" "$dir_name" 2>>"${LOG_FILE}"; then
            log "    Created: $archive_path"
            CREATED_FILES+=("$archive_path")
            TOTAL_SIZE=$((TOTAL_SIZE + $(stat -f%z "$archive_path" 2>/dev/null || stat -c%s "$archive_path")))
        else
            log "    ERROR: Failed to backup $dir_name"
            ERRORS=$((ERRORS + 1))
        fi
    done
    
    # Cleanup old weekly models (keep last 8)
    cleanup_old_backups "$models_dir" 8
}

# ========== TIER 2: DATA BACKUPS ==========
backup_data() {
    log "--- Data Backups (Tier 2) ---"
    local data_dir="${BACKUP_ROOT}/data/weekly"
    mkdir -p "$data_dir"
    
    local source_dir="/mnt/data/blofin_tickers"
    if [[ ! -d "$source_dir" ]]; then
        log "  SKIP: $source_dir (not found)"
        return
    fi
    
    local archive_path="${data_dir}/blofin_tickers_${TIMESTAMP}.tar.gz"
    
    log "  Backing up blofin_tickers parquet files..."
    if tar czf "$archive_path" -C /mnt/data blofin_tickers 2>>"${LOG_FILE}"; then
        log "    Created: $archive_path"
        CREATED_FILES+=("$archive_path")
        TOTAL_SIZE=$((TOTAL_SIZE + $(stat -f%z "$archive_path" 2>/dev/null || stat -c%s "$archive_path")))
    else
        log "    ERROR: Failed to backup blofin_tickers"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Backup blofin OHLCV candle data (new ingestor, Mar 22 2026)
    local ohlcv_dir="/mnt/data/blofin_ohlcv"
    if [[ -d "$ohlcv_dir" ]]; then
        local ohlcv_archive="${data_dir}/blofin_ohlcv_${TIMESTAMP}.tar.gz"
        log "  Backing up blofin_ohlcv parquet files..."
        if tar czf "$ohlcv_archive" -C /mnt/data blofin_ohlcv 2>>"${LOG_FILE}"; then
            log "    Created: $ohlcv_archive"
            CREATED_FILES+=("$ohlcv_archive")
            TOTAL_SIZE=$((TOTAL_SIZE + $(stat -c%s "$ohlcv_archive" 2>/dev/null || echo 0)))
        else
            log "    ERROR: Failed to backup blofin_ohlcv"
            ERRORS=$((ERRORS + 1))
        fi
    fi
    
    # Cleanup old weekly data (keep last 4)
    cleanup_old_backups "$data_dir" 4
}

# ========== MAIN EXECUTION ==========
if [[ "$VERIFY_ONLY" == true ]]; then
    log "Verify-only mode - running backup-verify.sh"
    exec /home/rob/.openclaw/workspace/scripts/backup-verify.sh
fi

# Run appropriate backup tiers
backup_databases

if [[ "$MODE" == "daily" || "$MODE" == "weekly" || "$MODE" == "full" ]]; then
    backup_configs
fi

if [[ "$MODE" == "weekly" || "$MODE" == "full" ]] || should_run_tier2; then
    backup_models
    backup_data
fi

# ========== MANIFEST UPDATE ==========
log "--- Updating Manifest ---"

# Get current manifest data
if [[ -f "${MANIFEST}" ]]; then
    PREV_MANIFEST=$(cat "${MANIFEST}")
else
    PREV_MANIFEST="{}"
fi

# Build new manifest
PREV_DAILY=$(echo "$PREV_MANIFEST" | jq -r '.last_daily // "null"' 2>/dev/null)
PREV_WEEKLY=$(echo "$PREV_MANIFEST" | jq -r '.last_weekly // "null"' 2>/dev/null)

# Use jq to build properly escaped JSON
jq -n \
  --arg last_run "$(date -Iseconds)" \
  --arg mode "${MODE}" \
  --arg hourly "$(date -Iseconds)" \
  --arg daily "$PREV_DAILY" \
  --arg weekly "$PREV_WEEKLY" \
  --argjson files "$(printf '%s\n' "${CREATED_FILES[@]}" | jq -R . | jq -s .)" \
  --argjson size "${TOTAL_SIZE}" \
  --argjson errors "${ERRORS}" \
  --arg ts "${TIMESTAMP}" \
  '{
    last_run: $last_run,
    last_mode: $mode,
    last_hourly: $hourly,
    last_daily: $daily,
    last_weekly: $weekly,
    files_created: $files,
    total_size_bytes: $size,
    errors: $errors,
    timestamp: $ts
  }' > "${MANIFEST}"

# Update last_daily and last_weekly if appropriate
if [[ "$MODE" == "daily" || "$MODE" == "weekly" || "$MODE" == "full" ]]; then
    jq ".last_daily = \"$(date -Iseconds)\"" "${MANIFEST}" > "${MANIFEST}.tmp" && mv "${MANIFEST}.tmp" "${MANIFEST}"
fi

if [[ "$MODE" == "weekly" || "$MODE" == "full" ]]; then
    jq ".last_weekly = \"$(date -Iseconds)\"" "${MANIFEST}" > "${MANIFEST}.tmp" && mv "${MANIFEST}.tmp" "${MANIFEST}"
fi

# ========== SUMMARY ==========
log "=== Backup Complete ==="
log "Files created: ${#CREATED_FILES[@]}"
log "Total size: $(numfmt --to=iec-i --suffix=B ${TOTAL_SIZE} 2>/dev/null || echo "${TOTAL_SIZE} bytes")"
log "Errors: ${ERRORS}"

if [[ ${ERRORS} -gt 0 ]]; then
    log "WARNING: Backup completed with errors. Check ${LOG_FILE}"
    exit 1
fi

log "Backup successful!"
exit 0
