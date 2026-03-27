#!/usr/bin/env python3
"""
SBIR/STTR Daily Monitor
Checks sbir.gov for new funding opportunities matching OpenClaw/robotics/AI keywords
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Keywords to match (case-insensitive)
KEYWORDS = [
    "robotics", "robot", "manipulation", "gripper", "dexterous",
    "artificial intelligence", "AI", "agent", "automation",
    "embodied", "tactile", "vision", "perception",
    "manufacturing", "assembly", "autonomous", "autonomy",
    "machine learning", "reinforcement learning", "control systems"
]

# Target agencies (most relevant for OpenClaw)
TARGET_AGENCIES = ["NSF", "DoD", "NASA", "DOE", "DHS", "Air Force", "Navy", "Army"]

DATA_DIR = Path.home() / ".openclaw/workspace/data/sbir"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SEEN_FILE = DATA_DIR / "seen_topics.json"
LOG_FILE = DATA_DIR / "monitor.log"


def log(msg):
    """Append to log file and print."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_seen():
    """Load previously seen topic IDs."""
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    """Save seen topic IDs."""
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f, indent=2)


def fetch_topics():
    """Fetch current SBIR topics from sbir.gov."""
    url = "https://www.sbir.gov/api/topics.json"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log(f"Error fetching topics: {e}")
        return []


def matches_keywords(topic):
    """Check if topic matches any of our keywords."""
    text = f"{topic.get('title', '')} {topic.get('description', '')} {topic.get('agency', '')}".lower()
    return any(kw.lower() in text for kw in KEYWORDS)


def matches_agency(topic):
    """Check if topic is from a target agency."""
    agency = topic.get("agency", "").upper()
    return any(target.upper() in agency for target in TARGET_AGENCIES)


def format_alert(topic):
    """Format topic as alert message."""
    return f"""
🚀 NEW SBIR OPPORTUNITY

Agency: {topic.get('agency', 'Unknown')}
Topic: {topic.get('topic_number', 'N/A')} - {topic.get('title', 'No title')}
Open Date: {topic.get('open_date', 'TBD')}
Close Date: {topic.get('close_date', 'TBD')}
Phase: {topic.get('phase', 'N/A')}

Description:
{topic.get('description', 'No description')[:500]}...

URL: https://www.sbir.gov/sbirsearch/detail/{topic.get('topic_id', '')}

Keywords matched: {', '.join([kw for kw in KEYWORDS if kw.lower() in f"{topic.get('title', '')} {topic.get('description', '')}".lower()])}
"""


def send_telegram_alert(message):
    """Send alert via OpenClaw message tool (Telegram)."""
    # This would integrate with OpenClaw's messaging
    # For now, just log it
    log(f"ALERT:\n{message}")
    # TODO: Add actual Telegram notification via OpenClaw API


def main():
    log("=== SBIR Monitor Run ===")
    
    seen = load_seen()
    topics = fetch_topics()
    
    if not topics:
        log("No topics returned from API (may still be down post-reauthorization)")
        return
    
    log(f"Fetched {len(topics)} total topics")
    
    new_matches = []
    for topic in topics:
        topic_id = topic.get("topic_id") or topic.get("topic_number")
        if not topic_id:
            continue
            
        if topic_id in seen:
            continue
            
        # Check if relevant
        if matches_keywords(topic) or matches_agency(topic):
            new_matches.append(topic)
            seen.add(topic_id)
    
    if new_matches:
        log(f"Found {len(new_matches)} new relevant opportunities")
        for topic in new_matches:
            alert = format_alert(topic)
            send_telegram_alert(alert)
            # Also save to file
            match_file = DATA_DIR / f"match_{topic.get('topic_id', 'unknown')}.json"
            with open(match_file, "w") as f:
                json.dump(topic, f, indent=2)
    else:
        log("No new relevant opportunities")
    
    save_seen(seen)
    log("=== Run Complete ===\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(1)
