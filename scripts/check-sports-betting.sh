#!/bin/bash

# Monitor sports-betting-arb GitHub Actions runs
# Runs at :02 every 5 minutes to check on the previous scan

REPO="robbyrobaz/sports-betting-arb"
LOG_FILE="/home/rob/.openclaw/workspace/logs/sports-betting-monitor.log"

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Checking sports-betting-arb status..." >> $LOG_FILE

# Get latest workflow run
LATEST_RUN=$(gh run list --repo $REPO --limit 1 --json status,conclusion,name,updatedAt,displayTitle -t '{{.[0].status}} {{.[0].conclusion}} {{.[0].name}}' 2>/dev/null)

echo "  Latest run: $LATEST_RUN" >> $LOG_FILE

# Check for failures
if echo "$LATEST_RUN" | grep -q "failure\|error"; then
    echo "  ⚠️  ALERT: Run failed!" >> $LOG_FILE
    echo "View at: https://github.com/$REPO/actions"
else
    echo "  ✅ Status OK" >> $LOG_FILE
fi

# Get latest report timestamp
LATEST_REPORT=$(ls -t /tmp/sports-betting-arb/reports/daily_report_*.json 2>/dev/null | head -1)
if [ -n "$LATEST_REPORT" ]; then
    REPORT_TIME=$(stat -c %y "$LATEST_REPORT" 2>/dev/null | cut -d' ' -f1-2)
    echo "  Latest report: $REPORT_TIME" >> $LOG_FILE
fi

echo "" >> $LOG_FILE
