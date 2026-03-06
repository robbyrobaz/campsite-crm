#!/bin/bash
# ORB overnight monitor — runs every 30 min via systemd
# Checks backtest progress, dispatches next card, sends morning report at 7am MST

NTFY="https://ntfy.sh/nq-pipeline"
LOG="/home/rob/.openclaw/workspace/brain/status/orb_overnight.log"
NQ_DIR="/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE"
KANBAN="http://127.0.0.1:8787"
NOW_MST=$(TZ='America/Phoenix' date '+%H:%M')
NOW_TS=$(date '+%Y-%m-%d %H:%M')

echo "[$NOW_TS] ORB overnight check running" >> $LOG

# Check completed backtests
DONE_FILES=""
[ -f "$NQ_DIR/docs/orb_prop_research/orb_exit_optimization.md" ] && DONE_FILES="$DONE_FILES exit_opt"
[ -f "$NQ_DIR/docs/orb_prop_research/orb_15min_results.md" ] && DONE_FILES="$DONE_FILES 15min_orb"
[ -f "$NQ_DIR/docs/orb_prop_research/orb_8am_results.md" ] && DONE_FILES="$DONE_FILES 8am_orb"
[ -f "$NQ_DIR/docs/orb_prop_research/OVERNIGHT_REPORT.md" ] && DONE_FILES="$DONE_FILES final_report"

echo "[$NOW_TS] Completed: $DONE_FILES" >> $LOG

# Dispatch next planned card if < 3 in progress
IN_PROG=$(curl -s "$KANBAN/api/cards?status=In%20Progress" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('cards',[])))" 2>/dev/null)
PLANNED=$(curl -s "$KANBAN/api/cards?status=Planned" | python3 -c "
import json,sys
cards = json.load(sys.stdin).get('cards',[])
# Only show ORB-related planned cards
orb = [c for c in cards if any(k in c.get('title','').lower() for k in ['orb','8am','combo','mnq'])]
print(len(orb))
" 2>/dev/null)

echo "[$NOW_TS] In Progress: $IN_PROG | Planned ORB: $PLANNED" >> $LOG

# Dispatch if capacity available
if [ "$IN_PROG" -lt 3 ] && [ "$PLANNED" -gt 0 ]; then
    NEXT_ID=$(curl -s "$KANBAN/api/cards?status=Planned" | python3 -c "
import json,sys
cards = json.load(sys.stdin).get('cards',[])
orb = [c for c in cards if any(k in c.get('title','').lower() for k in ['orb','8am','combo','mnq','exit'])]
if orb: print(orb[0]['id'])
" 2>/dev/null)
    if [ -n "$NEXT_ID" ]; then
        RESULT=$(curl -s -X POST "$KANBAN/api/cards/$NEXT_ID/run")
        echo "[$NOW_TS] Dispatched $NEXT_ID: $RESULT" >> $LOG
    fi
fi

# 7:00 AM MST — send morning report
HOUR_MST=$(TZ='America/Phoenix' date '+%H')
MIN_MST=$(TZ='America/Phoenix' date '+%M')
if [ "$HOUR_MST" = "07" ] && [ "$MIN_MST" -lt "35" ]; then
    # Build summary from completed files
    SUMMARY="ORB Overnight Results\n"
    SUMMARY+="========================\n"

    if [ -f "$NQ_DIR/docs/orb_prop_research/OVERNIGHT_REPORT.md" ]; then
        # Extract top recommendation
        REC=$(head -30 "$NQ_DIR/docs/orb_prop_research/OVERNIGHT_REPORT.md" | grep -A5 "RECOMMENDATION\|BEST\|Winner" | head -10)
        SUMMARY+="FINAL REPORT READY\n$REC\n"
    else
        # Partial results
        [ -f "$NQ_DIR/docs/orb_prop_research/orb_exit_optimization.md" ] && SUMMARY+="✅ Exit optimization done\n"
        [ -f "$NQ_DIR/docs/orb_prop_research/orb_15min_results.md" ] && SUMMARY+="✅ 15-min ORB done\n"
        [ -f "$NQ_DIR/docs/orb_prop_research/orb_8am_results.md" ] && SUMMARY+="✅ 8am strategy done\n"
        SUMMARY+="Check: github.com/robbyrobaz/NQ-Trading-PIPELINE/docs/orb_prop_research/"
    fi

    curl -s -X POST "$NTFY" \
        -H "Title: ORB Morning Report — Rob wake up!" \
        -H "Priority: high" \
        -H "Tags: chart_with_upwards_trend" \
        -d "$(echo -e $SUMMARY)" > /dev/null
    echo "[$NOW_TS] Morning report sent to ntfy" >> $LOG
fi
