#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECTS_DIR="$ROOT/brain/projects"
TEMPLATE="$ROOT/brain/templates/project-update.md"

PROJECT_RAW="${1:-new-project}"
SLUG="$(echo "$PROJECT_RAW" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')"
DATE="$(date +%F)"
OUT="$PROJECTS_DIR/${SLUG}.md"

mkdir -p "$PROJECTS_DIR"

if [[ -f "$OUT" ]]; then
  echo "Exists: $OUT"
  echo "Tip: append a dated update section manually."
  exit 0
fi

cp "$TEMPLATE" "$OUT"
sed -i "s/{{project-slug}}/$SLUG/g; s/{{date}}/$DATE/g" "$OUT"

echo "Created: $OUT"
