#!/bin/bash
# 🚀 Complete Multi-Source Trading System
# Runs ALL components for full data collection

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   🚀 COMPLETE MULTI-SOURCE TRADING SYSTEM 🚀                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

cd ~/.openclaw/workspace/dexscreener-scanner
source venv/bin/activate

# Check if Telegram scanner is running
if pgrep -f "python.*autonomous-memecoin-hunter.*scanner.py" > /dev/null; then
    echo "✅ Telegram scanner already running"
else
    echo "🚀 Starting Telegram scanner..."
    cd ~/.openclaw/workspace/autonomous-memecoin-hunter
    source venv/bin/activate
    nohup python scanner.py > logs/scanner.log 2>&1 &
    echo "   PID: $!"
    cd ~/.openclaw/workspace/dexscreener-scanner
    source venv/bin/activate
fi

echo ""
echo "🚀 Starting all components..."
echo ""

# Start outcome tracker in background
if pgrep -f "python.*outcome_tracker.py" > /dev/null; then
    echo "✅ Outcome tracker already running"
else
    echo "📊 Starting outcome tracker (tracks tokens over time)..."
    nohup python outcome_tracker.py > logs/outcome_tracker.log 2>&1 &
    echo "   PID: $!"
fi

# Start position monitor in background
if pgrep -f "python.*position_monitor.py" > /dev/null; then
    echo "✅ Position monitor already running"
else
    echo "💼 Starting position monitor (watches for exits)..."
    nohup python position_monitor.py > logs/position_monitor.log 2>&1 &
    echo "   PID: $!"
fi

echo ""
echo "🚀 Starting main scanner (foreground)..."
echo "   Press Ctrl+C to stop main scanner only"
echo "   (other components will keep running in background)"
echo ""

# Run main scanner in foreground
python scanner_multi_source.py
