#!/usr/bin/env bash
set -euo pipefail

# Reads brain/status/status.json and renders a human-readable STATUS.md
# Run manually or via heartbeat to keep STATUS.md current

BRAIN_DIR="$HOME/.openclaw/workspace/brain"
STATUS_JSON="$BRAIN_DIR/status/status.json"
STATUS_MD="$BRAIN_DIR/STATUS.md"

if [[ ! -f "$STATUS_JSON" ]]; then
    echo "Error: $STATUS_JSON not found" >&2
    exit 1
fi

# Parse JSON with jq
LAST_UPDATED=$(jq -r '.lastUpdated // "unknown"' "$STATUS_JSON")
GATEWAY=$(jq -r '.systemHealth.gateway // "unknown"' "$STATUS_JSON")
SERVICES=$(jq -r '.systemHealth.services // "unknown"' "$STATUS_JSON")
CPU_TEMP=$(jq -r '.systemHealth.cpu_temp // "unknown"' "$STATUS_JSON")
DISK_PCT=$(jq -r '.systemHealth.disk_pct // "unknown"' "$STATUS_JSON")
HEALTH_CHECK=$(jq -r '.systemHealth.lastCheck // "unknown"' "$STATUS_JSON")
ACTIVE_COUNT=$(jq '.activeTasks | length' "$STATUS_JSON")
QUEUED_COUNT=$(jq '.queued | length' "$STATUS_JSON")
RECENT_COUNT=$(jq '.recentlyCompleted | length' "$STATUS_JSON")
INCIDENT_COUNT=$(jq '.incidents | length' "$STATUS_JSON")

# Write STATUS.md atomically
TMPFILE=$(mktemp "$STATUS_MD.XXXXXX")

cat > "$TMPFILE" <<STATUSEOF
# Jarvis Status

**Last updated:** $LAST_UPDATED

## System Health

| Metric | Value |
|--------|-------|
| Gateway | $GATEWAY |
| Services | $SERVICES |
| CPU Temp | $CPU_TEMP |
| Disk | $DISK_PCT |
| Last Check | $HEALTH_CHECK |

## Active Tasks ($ACTIVE_COUNT)

STATUSEOF

if [[ "$ACTIVE_COUNT" -gt 0 ]]; then
    jq -r '.activeTasks[] | "- **\(.title)** (\(.status)) — started \(.startedAt // "unknown")"' "$STATUS_JSON" >> "$TMPFILE"
else
    echo "_None_" >> "$TMPFILE"
fi

cat >> "$TMPFILE" <<STATUSEOF

## Queued ($QUEUED_COUNT)

STATUSEOF

if [[ "$QUEUED_COUNT" -gt 0 ]]; then
    jq -r '.queued[] | "- \(.title)"' "$STATUS_JSON" >> "$TMPFILE"
else
    echo "_None_" >> "$TMPFILE"
fi

cat >> "$TMPFILE" <<STATUSEOF

## Recently Completed ($RECENT_COUNT)

STATUSEOF

if [[ "$RECENT_COUNT" -gt 0 ]]; then
    jq -r '.recentlyCompleted[] | "- **\(.title)** (\(.status))"' "$STATUS_JSON" >> "$TMPFILE"
else
    echo "_None_" >> "$TMPFILE"
fi

if [[ "$INCIDENT_COUNT" -gt 0 ]]; then
    cat >> "$TMPFILE" <<STATUSEOF

## Incidents ($INCIDENT_COUNT)

STATUSEOF
    jq -r '.incidents[] | "- \(.severity // "info"): \(.message // "no details")"' "$STATUS_JSON" >> "$TMPFILE"
fi

echo "" >> "$TMPFILE"
echo "_Rendered by render-status.sh_" >> "$TMPFILE"

# Atomic rename
mv "$TMPFILE" "$STATUS_MD"
echo "Rendered $STATUS_MD"
