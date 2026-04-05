#!/bin/bash
# 🚀 Multi-Source Memecoin Scanner + Paper Trader
# Runs Telegram scanner + Multi-source scanner together

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   🚀 STARTING MULTI-SOURCE MEMECOIN TRADING SYSTEM 🚀       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Activate venv
cd ~/.openclaw/workspace/dexscreener-scanner
source venv/bin/activate

# Start Telegram scanner in background (if not already running)
TELEGRAM_SCANNER=~/.openclaw/workspace/autonomous-memecoin-hunter/scanner.py

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
echo "🚀 Starting Multi-Source Scanner + Paper Trader..."
echo "   Press Ctrl+C to stop"
echo ""

# Run main scanner in foreground
python scanner_multi_source.py
