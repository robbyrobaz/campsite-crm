#!/usr/bin/env python3
"""
Task Picker Helper - Analyzes kanban cards and recommends which to work on next.

Usage:
    python3 brain/tools/task_picker.py
    
Returns JSON with recommended card ID and reasoning.
"""

import requests
import json
import sys
from datetime import datetime

KANBAN_API = "http://127.0.0.1:8787/api"

def get_cards(status):
    """Fetch cards by status."""
    response = requests.get(f"{KANBAN_API}/cards", params={"status": status})
    return response.json().get("cards", [])

def score_card(card):
    """
    Score a card based on multiple criteria.
    Higher score = higher priority.
    """
    score = 0
    title = (card.get("title") or "").lower()
    description = (card.get("description") or "").lower()
    project_path = card.get("project_path") or ""
    
    # Quick wins (bug fixes, config changes, tests)
    quick_win_keywords = ["bug", "fix", "config", "test", "lint", "gate", "tune", "update"]
    if any(kw in title or kw in description for kw in quick_win_keywords):
        score += 10
    
    # Blofin work (active project)
    if "blofin" in title or "blofin" in description or "blofin-stack" in project_path:
        score += 5
    
    # Numerai work (active project)
    if "numerai" in title or "numerai" in description:
        score += 3
    
    # Documentation/code quality (lower priority)
    low_priority_keywords = ["documentation", "readme", "refactor", "optimize"]
    if any(kw in title or kw in description for kw in low_priority_keywords):
        score -= 3
    
    # Complex tasks (design, architecture, multi-step)
    complex_keywords = ["design", "architecture", "sweep", "analyze"]
    if any(kw in title or kw in description for kw in complex_keywords):
        score -= 5  # Prefer simpler tasks for autonomous work
    
    # Has project path (better scoped)
    if project_path:
        score += 2
    
    # Penalize vague titles
    if len(card.get("title", "")) < 20:
        score -= 2
    
    return score

def recommend_task():
    """Recommend the best task to work on."""
    # Get available cards
    planned = get_cards("Planned")
    inbox = get_cards("Inbox")
    
    all_available = planned + inbox
    
    if not all_available:
        return {
            "recommended": None,
            "reason": "No available tasks in Planned or Inbox"
        }
    
    # Score all cards
    scored_cards = []
    for card in all_available:
        score = score_card(card)
        scored_cards.append({
            "card": card,
            "score": score
        })
    
    # Sort by score (highest first)
    scored_cards.sort(key=lambda x: x["score"], reverse=True)
    
    # Return top recommendation
    top = scored_cards[0]
    return {
        "recommended_id": top["card"]["id"],
        "title": top["card"]["title"],
        "score": top["score"],
        "reason": f"Highest priority score ({top['score']}) among {len(all_available)} available tasks",
        "project_path": top["card"].get("project_path", "N/A")
    }

if __name__ == "__main__":
    try:
        result = recommend_task()
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)
