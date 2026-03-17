#!/usr/bin/env python3
"""
Builder QA Audit — Verify recently completed kanban cards actually did their work.

Run this every 4h to catch builders that marked cards Done without executing.
Returns exit code 1 if issues found (for alerting).

Usage: python3 builder_qa_audit.py [--hours 6] [--reopen]
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

KANBAN_API = "http://127.0.0.1:8787/api"
WORKSPACE = Path("/home/rob/.openclaw/workspace")

def get_recent_done_cards(hours: int = 6) -> list:
    """Fetch cards marked Done in the last N hours."""
    cutoff_ms = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
    result = subprocess.run(
        ["curl", "-s", f"{KANBAN_API}/cards?status=Done"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    cards = data.get("cards", data) if isinstance(data, dict) else data
    return [c for c in cards if c.get("updated_at", 0) > cutoff_ms]

def get_card_log(card_id: str) -> str:
    """Read the builder log for a card."""
    log_path = WORKSPACE / "kanban-dashboard" / "logs" / f"{card_id}.log"
    if log_path.exists():
        return log_path.read_text()
    return ""

def check_for_planning_only(log: str) -> bool:
    """Detect if builder just planned but didn't execute."""
    planning_phrases = [
        r"ready to proceed\?",
        r"shall i continue\?",
        r"do you want me to",
        r"should i implement",
        r"would you like me to",
        r"let me know if you",
        r"waiting for confirmation",
        r"proceed with implementation\?",
    ]
    log_lower = log.lower()
    # Check last 2000 chars of log for planning phrases
    tail = log_lower[-2000:] if len(log_lower) > 2000 else log_lower
    for phrase in planning_phrases:
        if re.search(phrase, tail):
            return True
    return False

def verify_blofin_card(card: dict) -> tuple[bool, str]:
    """Verify Blofin-related cards."""
    title = card.get("title", "").lower()
    
    # Check null scores fix
    if "null" in title and "score" in title:
        db_path = WORKSPACE / "blofin-stack" / "data" / "blofin_monitor.db"
        if db_path.exists():
            db = sqlite3.connect(str(db_path))
            r = db.execute("SELECT COUNT(*), SUM(CASE WHEN ml_score IS NULL THEN 1 ELSE 0 END) FROM scores").fetchone()
            db.close()
            if r[0] and r[1]:
                null_pct = 100 * r[1] / r[0]
                if null_pct > 20:  # Should be <10% after fix
                    return False, f"Null scores still at {null_pct:.1f}% (expected <20%)"
    
    # Check leverage engine
    if "leverage" in title and "engine" in title:
        engine_path = WORKSPACE / "blofin-stack" / "utils" / "leverage_engine.py"
        if not engine_path.exists():
            return False, "leverage_engine.py not created"
    
    return True, "OK"

def verify_nq_card(card: dict) -> tuple[bool, str]:
    """Verify NQ-related cards."""
    title = card.get("title", "").lower()
    
    # Check calendar integration
    if "calendar" in title:
        cal_path = WORKSPACE / "NQ-Trading-PIPELINE" / "pipeline" / "calendar_utils.py"
        if not cal_path.exists():
            return False, "calendar_utils.py not created"
    
    # Check ETB registration
    if "etb" in title or "equal_tops" in title:
        watcher_path = WORKSPACE / "NQ-Trading-PIPELINE" / "pipeline" / "smb_watcher.py"
        if watcher_path.exists():
            content = watcher_path.read_text()
            if "equal_tops_bottoms" not in content:
                return False, "ETB not registered in smb_watcher.py"
    
    return True, "OK"

def verify_moonshot_card(card: dict) -> tuple[bool, str]:
    """Verify Moonshot-related cards."""
    title = card.get("title", "").lower()
    
    # Check null scores
    if "null" in title and "score" in title:
        db_path = WORKSPACE / "blofin-moonshot" / "data" / "moonshot.db"
        if db_path.exists():
            db = sqlite3.connect(str(db_path))
            r = db.execute("SELECT COUNT(*), SUM(CASE WHEN ml_score IS NULL THEN 1 ELSE 0 END) FROM scores").fetchone()
            db.close()
            if r[0] and r[1]:
                null_pct = 100 * r[1] / r[0]
                if null_pct > 20:
                    return False, f"Null scores still at {null_pct:.1f}% (expected <20%)"
    
    # Check feature importance
    if "feature" in title and "importance" in title:
        # Should have created analysis output
        analysis_files = list((WORKSPACE / "blofin-moonshot").glob("**/feature_importance*.json"))
        analysis_files += list((WORKSPACE / "blofin-moonshot").glob("**/feature_importance*.csv"))
        if not analysis_files:
            return False, "No feature importance output files created"
    
    return True, "OK"

def reopen_card(card_id: str):
    """Move card back to Planned for re-execution."""
    subprocess.run([
        "curl", "-s", "-X", "PATCH",
        f"{KANBAN_API}/cards/{card_id}",
        "-H", "content-type: application/json",
        "-d", json.dumps({"status": "Planned"})
    ], capture_output=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=6, help="Check cards from last N hours")
    parser.add_argument("--reopen", action="store_true", help="Reopen failed cards to Planned")
    args = parser.parse_args()
    
    cards = get_recent_done_cards(args.hours)
    print(f"Checking {len(cards)} cards marked Done in last {args.hours}h...\n")
    
    issues = []
    
    for card in cards:
        card_id = card["id"]
        title = card.get("title", "")[:60]
        project = card.get("project_path", "")
        
        # Check log for planning-only pattern
        log = get_card_log(card_id)
        if check_for_planning_only(log):
            issues.append({
                "card_id": card_id,
                "title": title,
                "issue": "Builder asked permission instead of executing",
                "severity": "HIGH"
            })
            if args.reopen:
                reopen_card(card_id)
            continue
        
        # Project-specific verification
        passed, msg = True, "OK"
        if "blofin-stack" in project:
            passed, msg = verify_blofin_card(card)
        elif "NQ-Trading" in project:
            passed, msg = verify_nq_card(card)
        elif "blofin-moonshot" in project:
            passed, msg = verify_moonshot_card(card)
        
        if not passed:
            issues.append({
                "card_id": card_id,
                "title": title,
                "issue": msg,
                "severity": "MEDIUM"
            })
            if args.reopen:
                reopen_card(card_id)
    
    # Report
    if issues:
        print("=" * 60)
        print(f"FOUND {len(issues)} ISSUES:")
        print("=" * 60)
        for iss in issues:
            print(f"\n[{iss['severity']}] {iss['title']}")
            print(f"  Card: {iss['card_id']}")
            print(f"  Issue: {iss['issue']}")
            if args.reopen:
                print(f"  Action: Reopened to Planned")
        print()
        sys.exit(1)
    else:
        print(f"✓ All {len(cards)} cards verified OK")
        sys.exit(0)

if __name__ == "__main__":
    main()
