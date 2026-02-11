#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INBOX_DIR="$ROOT/inbox"
TEMPLATE="$ROOT/templates/session-summary.md"

TITLE_RAW="${1:-session}"
SLUG="$(echo "$TITLE_RAW" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')"
DATE="$(date +%F)"
OUT="$INBOX_DIR/${DATE}-${SLUG}.md"

mkdir -p "$INBOX_DIR"
cp "$TEMPLATE" "$OUT"

sed -i "s/{{date}}/$DATE/g; s/{{title}}/$TITLE_RAW/g" "$OUT"

echo "Created: $OUT"
