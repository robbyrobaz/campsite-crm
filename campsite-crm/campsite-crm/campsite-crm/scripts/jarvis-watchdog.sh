#!/usr/bin/env bash
set -euo pipefail

# Jarvis Watchdog — Independent of OpenClaw
# Monitors the gateway service and restarts it with circuit breaker logic.
# Circuit breaker: max 3 restarts in 30 minutes, then exponential backoff.
# Sends ntfy.sh alerts for all state changes.

NTFY_TOPIC="jarvis-omen-claw"
GATEWAY_SERVICE="openclaw-gateway.service"
BROWSER_SERVICE="openclaw-browser.service"
OPENCLAW_BIN="/home/rob/.npm-global/bin/openclaw"
STATE_FILE="/tmp/jarvis-watchdog-state.json"
CHECK_INTERVAL=1800  # seconds between checks (30 minutes)
HEALTH_TIMEOUT=30  # seconds

# Initialize state file if missing
init_state() {
    if [[ ! -f "$STATE_FILE" ]]; then
        cat > "$STATE_FILE" <<'EOF'
{"restarts":[],"backoff_until":0,"consecutive_failures":0}
EOF
    fi
}

# Send ntfy notification
notify() {
    local title="$1"
    local message="$2"
    local priority="${3:-default}"
    local tags="${4:-robot}"

    curl -sf \
        -H "Title: $title" \
        -H "Priority: $priority" \
        -H "Tags: $tags" \
        -d "$message" \
        "https://ntfy.sh/$NTFY_TOPIC" >/dev/null 2>&1 || true
}

# Get current epoch
now() {
    date +%s
}

# Check if service is running
is_service_active() {
    systemctl --user is-active --quiet "$GATEWAY_SERVICE"
}

# Check browser service as part of OpenClaw baseline
is_browser_active() {
    systemctl --user is-active --quiet "$BROWSER_SERVICE"
}

# Check full OpenClaw health (telegram/session checks)
is_openclaw_healthy() {
    timeout "$HEALTH_TIMEOUT" "$OPENCLAW_BIN" health >/tmp/jarvis-watchdog-health.log 2>&1
}

# Count restarts in the last 30 minutes
recent_restart_count() {
    local cutoff=$(( $(now) - 1800 ))
    jq "[.restarts[] | select(. > $cutoff)] | length" "$STATE_FILE"
}

# Check if we're in backoff period
in_backoff() {
    local backoff_until
    backoff_until=$(jq -r '.backoff_until' "$STATE_FILE")
    [[ $(now) -lt $backoff_until ]]
}

# Record a restart
record_restart() {
    local current_time
    current_time=$(now)
    local cutoff=$(( current_time - 1800 ))
    # Add new restart, prune old ones
    local tmp
    tmp=$(mktemp)
    jq ".restarts = [.restarts[] | select(. > $cutoff)] + [$current_time] | .consecutive_failures = .consecutive_failures + 1" "$STATE_FILE" > "$tmp"
    mv "$tmp" "$STATE_FILE"
}

# Reset failure count on successful check
reset_failures() {
    local tmp
    tmp=$(mktemp)
    jq '.consecutive_failures = 0' "$STATE_FILE" > "$tmp"
    mv "$tmp" "$STATE_FILE"
}

# Set backoff period based on consecutive failures
set_backoff() {
    local failures
    failures=$(jq -r '.consecutive_failures' "$STATE_FILE")
    # Exponential backoff: 5min, 15min, 30min (capped)
    local backoff_seconds
    case $failures in
        1) backoff_seconds=300 ;;
        2) backoff_seconds=900 ;;
        *) backoff_seconds=1800 ;;
    esac
    local backoff_until=$(( $(now) + backoff_seconds ))
    local tmp
    tmp=$(mktemp)
    jq ".backoff_until = $backoff_until" "$STATE_FILE" > "$tmp"
    mv "$tmp" "$STATE_FILE"
    echo $backoff_seconds
}

# Main watchdog loop
main() {
    init_state
    notify "Jarvis Watchdog Started" "Monitoring OpenClaw services and health every ${CHECK_INTERVAL}s" "low" "eyes"

    while true; do
        if is_service_active && is_browser_active && is_openclaw_healthy; then
            # Service is healthy — reset failure counter if it was elevated
            local failures
            failures=$(jq -r '.consecutive_failures' "$STATE_FILE")
            if [[ "$failures" -gt 0 ]]; then
                reset_failures
                notify "OpenClaw Recovered" "Health restored after $failures restart attempt(s)" "default" "white_check_mark"
            fi
        else
            # OpenClaw is unhealthy
            if in_backoff; then
                local backoff_until
                backoff_until=$(jq -r '.backoff_until' "$STATE_FILE")
                local remaining=$(( backoff_until - $(now) ))
                # Only log occasionally, not every check
                :
            else
                local recent
                recent=$(recent_restart_count)
                if [[ "$recent" -ge 3 ]]; then
                    # Circuit breaker tripped
                    local backoff_secs
                    backoff_secs=$(set_backoff)
                    local backoff_min=$(( backoff_secs / 60 ))
                    notify "CIRCUIT BREAKER TRIPPED" "OpenClaw unhealthy $recent times in 30min. Backing off ${backoff_min}m. Manual intervention may be needed." "urgent" "rotating_light"
                else
                    # Attempt restart of both baseline services
                    record_restart
                    notify "OpenClaw Unhealthy — Restarting" "Attempt $(( recent + 1 ))/3 in last 30 minutes" "high" "warning"
                    systemctl --user restart "$BROWSER_SERVICE" "$GATEWAY_SERVICE" 2>/dev/null || true
                    sleep 5
                    if is_service_active && is_browser_active && is_openclaw_healthy; then
                        notify "OpenClaw Restarted" "Services recovered and health check passed" "default" "white_check_mark"
                    else
                        notify "Restart Failed" "OpenClaw did not recover. Last health output in /tmp/jarvis-watchdog-health.log" "high" "x"
                    fi
                fi
            fi
        fi

        sleep "$CHECK_INTERVAL"
    done
}

main "$@"
