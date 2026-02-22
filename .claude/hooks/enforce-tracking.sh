#!/bin/bash
# Enforce kanban tracking: log all Task spawns.
# The discipline is now: create a kanban card before doing work.
# This hook logs Task spawns for audit trail.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null)

if [ "$TOOL_NAME" = "Task" ]; then
  # Log the spawn for audit
  echo "[$(date -Iseconds)] Task spawned" >> /home/rob/.openclaw/workspace/kanban-dashboard/logs/task-audit.log
fi

exit 0
