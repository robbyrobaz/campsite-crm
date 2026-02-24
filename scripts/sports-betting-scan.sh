#!/bin/bash

# Sports Betting Scan Pipeline - Runs every 5 minutes locally
# Then pushes results to GitHub automatically

REPO_DIR="/tmp/sports-betting-arb"
LOG_FILE="/home/rob/.openclaw/workspace/logs/sports-betting-scan.log"

mkdir -p "$(dirname "$LOG_FILE")"

{
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] Starting scan..."
    
    cd "$REPO_DIR" || exit 1
    
    # 1. Scrape odds
    if ! python3 scripts/scraper.py >> /tmp/scraper.log 2>&1; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ❌ Scraper failed"
        exit 1
    fi
    
    # 2. Detect arbs
    if ! python3 scripts/detector.py >> /tmp/detector.log 2>&1; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ❌ Detector failed"
        exit 1
    fi
    
    # 3. Generate JSON reports
    if ! python3 scripts/report.py >> /tmp/report.log 2>&1; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ❌ Report generator failed"
        exit 1
    fi
    
    # 4. Move JSON to raw/
    mv reports/*.json raw/ 2>/dev/null
    
    # 5. Format to markdown
    if ! python3 scripts/format-report.py >> /tmp/format.log 2>&1; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ❌ Format script failed"
        exit 1
    fi
    
    # 6. Commit and push to GitHub
    git add reports/ history/ raw/ 2>/dev/null
    if git commit -m "Auto-scan: $(date +'%Y-%m-%d %H:%M:%S') — Fresh odds + arbs detected" --allow-empty >> /tmp/git.log 2>&1; then
        if git push >> /tmp/git.log 2>&1; then
            echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✅ Scan complete + pushed to GitHub"
        else
            echo "[$(date +'%Y-%m-%d %H:%M:%S')] ⚠️  Scan complete but push failed"
        fi
    fi
    
} >> "$LOG_FILE" 2>&1
