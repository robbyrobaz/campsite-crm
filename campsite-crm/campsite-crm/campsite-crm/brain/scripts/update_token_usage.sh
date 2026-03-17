#!/bin/bash
# Lightweight token usage updater — runs as systemd timer, zero AI tokens
cd /home/rob/.openclaw/workspace
python3 brain/scripts/token_usage_aggregator.py 2>/dev/null
