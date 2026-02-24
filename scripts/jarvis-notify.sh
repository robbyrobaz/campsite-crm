#!/usr/bin/env bash
set -euo pipefail

# Jarvis ntfy.sh notification helper
# Usage: jarvis-notify.sh <title> <message> [priority] [tags]
# Priority: min, low, default, high, urgent
# Tags: comma-separated emoji shortcodes (e.g., "warning,robot")

NTFY_TOPIC="jarvis-omen-claw"

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <title> <message> [priority] [tags]" >&2
    exit 1
fi

TITLE="$1"
MESSAGE="$2"
PRIORITY="${3:-default}"
TAGS="${4:-robot}"

curl -sf \
    -H "Title: $TITLE" \
    -H "Priority: $PRIORITY" \
    -H "Tags: $TAGS" \
    -d "$MESSAGE" \
    "https://ntfy.sh/$NTFY_TOPIC"
