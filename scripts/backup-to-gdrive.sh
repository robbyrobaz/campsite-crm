#!/usr/bin/env bash
# Off-site DB backup -> Google Drive (rclone remote "gdrive").
# Complements backup-all.sh, which is LOCAL-ONLY on /mnt/data.
# Also covers ~8 DBs that backup-all.sh misses entirely.
#
#   destination: gdrive:Omen-Claw Laptop Backups/databases/
#   restore:     download the .gz, gunzip it. No tooling, no password.
#
# NOTE: restic was tried (2026-08-17) for true incremental dedup and FAILED
# twice with Google RATE_LIMIT_EXCEEDED. rclone's shared OAuth client_id has a
# per-minute quota far below restic's request rate, and --pack-size 128 did not
# close the gap. A handful of large .gz uploads stays under the quota; hundreds
# of small pack/index writes do not. Revisit only with a private client_id.
set -uo pipefail

RCLONE=/home/rob/bin/rclone
REMOTE="gdrive:Omen-Claw Laptop Backups/databases"
VERSIONS="gdrive:Omen-Claw Laptop Backups/previous-versions"
STAGE=/mnt/data/backups/gdrive-stage
LOG=/mnt/data/backups/gdrive-backup.log
MANIFEST=/mnt/data/backups/gdrive-manifest.json
DATE=$(date +%Y-%m-%d)
ERRORS=(); WARNINGS=()

# NOTE: log() writes to STDERR, not stdout. snapshot() returns the artifact name
# on stdout via `art=$(snapshot ...)`, so anything log() emitted on stdout would be
# captured into $art. That is what happened whenever a DuckDB copy tore and retried:
# the retry line landed in the array key, the manifest heredoc died with
# "SyntaxError: unterminated string literal", and gdrive-manifest.json stopped being
# written (frozen 2026-08-19 -> 2026-08-22). Keep the >&2. (fixed 2026-08-22)
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG" >&2; }
fail() { log "ERROR: $*"; ERRORS+=("$*"); }

mkdir -p "$STAGE"

# --- DB list: path|type  (sqlite|duckdb) ------------------------------------
DBS=(
  # -- NQ / futures research
  "/home/rob/infrastructure/ibkr/data/nq_feed.duckdb|duckdb"
  "/home/rob/infrastructure/ibkr/data/ibkr_options.duckdb|duckdb"
  "/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/data/nq_pipeline.db|sqlite"
  # NQ2 dropped 2026-08-22 (Rob: no longer used). It derived the SAME artifact name
  # as NQ-Trading-PIPELINE's nq_pipeline.db -- basename(dirname)__basename gives
  # "data__nq_pipeline.db" for both -- so NQ2 was snapshotted second and silently
  # overwrote the LIVE pipeline DB in the stage dir. Drive held NQ2's 2.4MB copy, not
  # the pipeline's 10.5MB one. Do not re-add without a unique name.
  "/home/rob/.openclaw/workspace/nq-l2-scalping/data/l2_signals.db|sqlite"
  "/home/rob/.openclaw/workspace/futures_prospector/prospector.db|sqlite"
  "/home/rob/judas-futures-workshop/judasfutures.db|sqlite"
  "/home/rob/judas-agentic-crew/judas_crew.db|sqlite"
  "/home/rob/judas-agentic-crew/outputs/flow_state.db|sqlite"
  "/mnt/data/market_macro.db|sqlite"
  "/mnt/data/backtest_results.db|sqlite"
  # -- Options research (MISSING from backup-all.sh)
  "/home/rob/options-recorder/data/options_chain.duckdb|duckdb"
  "/home/rob/options-recorder/data/paper_trades.duckdb|duckdb"
  "/home/rob/options-recorder/data/red_calendar.duckdb|duckdb"
  "/home/rob/options-recorder/research/extension_exit/chain_snapshot.duckdb|duckdb"
  "/home/rob/options-recorder/research/extension_exit/paper_snapshot.duckdb|duckdb"
  # -- Agents / infra state
  "/home/rob/.hermes/state.db|sqlite"
  "/home/rob/.hermes/profiles/church/state.db|sqlite"
  "/home/rob/.hermes/profiles/nq/state.db|sqlite"
  "/home/rob/.hermes/profiles/reef/state.db|sqlite"
  "/home/rob/.hermes/profiles/sp/state.db|sqlite"
  "/home/rob/go-trader/shared_tools/trading_bot.db|sqlite"
  "/home/rob/.openclaw/workspace/jarvis-home-energy/energy_data.db|sqlite"
  # -- Businesses
  "/home/rob/website-sales-ai/leads.db|sqlite"
  "/home/rob/flight-deal-radar/radar.db|sqlite"
  "/home/rob/x402-insights/data/stats.db|sqlite"
  "/home/rob/x402-insights/data/tx_tape.db|sqlite"
  "/home/rob/x402-insights/data/serve.db|sqlite"
  # -- Dormant but irreplaceable. Unchanged files are skipped by --checksum,
  #    so this costs one upload, ever.
  #    NOTE: reef.db (38GB DuckDB) deliberately excluded — add a line to include.
  "/home/rob/hl-momentum/momentum.db|sqlite"
)

# --- snapshot + verify + compress -------------------------------------------
snapshot() {
  local src="$1" kind="$2" name out
  name="$(basename "$(dirname "$src")")__$(basename "$src")"
  out="${STAGE}/${name}"

  if [[ "$kind" == "sqlite" ]]; then
    # .backup is safe against a live writer
    if ! sqlite3 "$src" ".backup '${out}'" 2>>"$LOG"; then
      fail "sqlite .backup failed: $src"; return 1
    fi
    if ! sqlite3 "$out" "PRAGMA integrity_check;" 2>>"$LOG" | head -1 | grep -q '^ok$'; then
      fail "integrity_check FAILED: $name"; rm -f "$out"; return 1
    fi
  else
    # DuckDB has no online-backup API and /home is ext4 (no snapshots), so this
    # is a plain cp of a file a live writer may be mutating. A copy that spans a
    # checkpoint comes out torn ("No more data remaining in MetadataReader").
    # It usually succeeds -- it failed once at midday RTH when tick rate peaks --
    # so retry rather than stopping the collector. NEVER upload an unverified copy.
    local attempt ok=0
    for attempt in 1 2 3; do
      if ! cp "$src" "$out" 2>>"$LOG"; then fail "cp failed: $src"; return 1; fi
      if python3 - "$out" <<'DUCKCHECK' 2>>"$LOG"
import sys, duckdb
con = duckdb.connect(sys.argv[1], read_only=True)
con.execute("SHOW TABLES").fetchall()
con.close()
DUCKCHECK
      then
        ok=1
        [[ $attempt -gt 1 ]] && log "    (opened cleanly on attempt ${attempt})"
        break
      else
        log "    attempt ${attempt}/3: copy was torn, retrying in 30s"
        sleep 30
      fi
    done
    if (( ok == 0 )); then
      fail "duckdb open FAILED after 3 attempts: $name (live writer; previous Drive copy retained)"
      rm -f "$out"; return 1
    fi
  fi

  local sz; sz=$(stat -c%s "$out")
  (( sz < 10240 )) && WARNINGS+=("$name is only ${sz}B — likely an empty shell")
  gzip -1 -f "$out" || { fail "gzip failed: $name"; return 1; }
  echo "${name}.gz"
}

log "=== Off-site DB backup -> Google Drive starting ==="
rm -f "${STAGE}"/*
declare -A SIZES
declare -A SRCSTAMP

# Fingerprint of each source file at its last successful backup: "<size>:<mtime>".
# sqlite .backup output is not byte-stable, so an unchanged DB would otherwise
# re-compress to different bytes, defeat rclone --checksum, re-upload in full,
# and shove the old copy into version history. Frozen DBs (momentum.db, last
# written 2026-06-27) cost >1GB/night for nothing. Skip them at the source.
declare -A PREVSTAMP OLDSIZES
if [[ -f "$MANIFEST" ]]; then
  while IFS=$'\t' read -r k v; do OLDSIZES["$k"]="$v"; done < <(python3 -c "
import json
try:
    d=json.load(open('$MANIFEST')).get('artifacts',{})
    [print(f'{k}\t{v}') for k,v in d.items()]
except Exception: pass")
  while IFS=$'\t' read -r k v; do PREVSTAMP["$k"]="$v"; done < <(python3 -c "
import json
try:
    d=json.load(open('$MANIFEST')).get('sources',{})
    [print(f'{k}\t{v}') for k,v in d.items()]
except Exception: pass")
fi
for entry in "${DBS[@]}"; do
  IFS='|' read -r src kind <<< "$entry"
  [[ -f "$src" ]] || { log "SKIP (not found): $src"; continue; }

  name="$(basename "$(dirname "$src")")__$(basename "$src")"
  stamp="$(stat -c '%s:%Y' "$src")"
  SRCSTAMP["${name}.gz"]="$stamp"
  if [[ "${PREVSTAMP[${name}.gz]:-}" == "$stamp" ]]; then
    log "UNCHANGED, skipping: $(basename "$src")"
    SIZES["${name}.gz"]="${OLDSIZES[${name}.gz]:-0}"
    continue
  fi

  log "Snapshotting $(basename "$src")"
  if art=$(snapshot "$src" "$kind"); then
    SIZES["$art"]=$(stat -c%s "${STAGE}/${art}")
    log "  ok — $(numfmt --to=iec "${SIZES[$art]}")"
  fi
done

# --- shrink guard vs previous run -------------------------------------------
if [[ -f "$MANIFEST" ]]; then
  while IFS=$'\t' read -r k v; do
    cur="${SIZES[$k]:-MISSING}"
    if [[ "$cur" == "MISSING" ]]; then
      WARNINGS+=("$k was backed up last run but is MISSING now")
    elif [[ -n "${v:-}" && "$v" -gt 0 ]] && (( cur * 100 < v * 80 )); then
      WARNINGS+=("$k shrank $(( 100 - cur*100/v ))% since last run (${v} -> ${cur})")
    fi
  done < <(python3 -c "
import json
try:
    d=json.load(open('$MANIFEST')).get('artifacts',{})
    [print(f'{k}\t{v}') for k,v in d.items()]
except Exception: pass")
fi

python3 - "$MANIFEST" <<PY
import json,sys
arts = {}
srcs = {}
$(for k in "${!SIZES[@]}"; do echo "arts['$k'] = ${SIZES[$k]}"; done)
$(for k in "${!SRCSTAMP[@]}"; do echo "srcs['$k'] = '${SRCSTAMP[$k]}'"; done)
json.dump({"date":"$DATE","artifacts":arts,"sources":srcs,
           "total_bytes":sum(arts.values())}, open(sys.argv[1],'w'), indent=2)
PY

# --- upload ------------------------------------------------------------------
# Stable filenames + --checksum: unchanged DBs are skipped entirely.
# Superseded copies move to previous-versions/<date>/ instead of being lost.
log "Uploading to Drive..."
if ! "$RCLONE" copy "$STAGE" "$REMOTE" \
      --checksum \
      --backup-dir "${VERSIONS}/${DATE}" \
      --transfers 2 --checkers 4 \
      --bwlimit 8M \
      --drive-chunk-size 32M \
      --log-file "$LOG" --log-level INFO --stats 5m; then
  fail "rclone upload failed"
fi

"$RCLONE" copy "$MANIFEST" "$REMOTE" >/dev/null 2>&1

# --- prune version history (keep 30 days) ------------------------------------
"$RCLONE" lsf "$VERSIONS" --dirs-only 2>/dev/null | tr -d '/' | sort | head -n -30 | \
  while read -r old; do
    [[ -n "$old" ]] && log "Pruning old versions: $old" && \
      "$RCLONE" purge "${VERSIONS}/${old}" >/dev/null 2>&1
  done

rm -f "${STAGE}"/*

REMOTE_TOTAL=$("$RCLONE" size "$REMOTE" --json 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print(f\"{d['count']} files, {d['bytes']/1e9:.2f} GB\")" 2>/dev/null || echo "unknown")
log "Drive now holds: $REMOTE_TOTAL"

# --- notify ------------------------------------------------------------------
notify() {
  set -a; source /home/rob/flight-deal-radar/.env 2>/dev/null; set +a
  [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]] || return 0
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" -d text="$1" >/dev/null
}

if (( ${#ERRORS[@]} > 0 )); then
  log "=== COMPLETED WITH ${#ERRORS[@]} ERRORS ==="
  notify "🚨 Off-site DB backup FAILED ($(date '+%b %d')):
$(printf '%s\n' "${ERRORS[@]}")
Log: $LOG"
  exit 1
elif (( ${#WARNINGS[@]} > 0 )); then
  log "=== COMPLETED WITH WARNINGS ==="
  printf '%s\n' "${WARNINGS[@]}" | tee -a "$LOG"
  notify "⚠️ Off-site DB backup warnings ($(date '+%b %d')):
$(printf '%s\n' "${WARNINGS[@]}")
Drive: $REMOTE_TOTAL"
else
  log "=== COMPLETE — $REMOTE_TOTAL ==="
fi
