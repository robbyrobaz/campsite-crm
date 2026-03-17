#!/usr/bin/env python3
"""
Daily Anthropic 7-day quota estimator.
Calculates current burn rate and projects if we'll hit the limit before reset.
"""

import json
import os
from datetime import datetime, timezone, timedelta

MST = timezone(timedelta(hours=-7))

def load_rate_limit_data():
    """Load Anthropic OAuth rate limit data from cache."""
    cache_path = os.path.expanduser("~/.openclaw/workspace/brain/status/rate_limit_cache.json")
    if not os.path.exists(cache_path):
        return None
    
    with open(cache_path) as f:
        cache = json.load(f)
    
    seven_day = cache.get("data", {}).get("seven_day", {})
    return {
        "utilization": seven_day.get("utilization"),
        "resets_at": seven_day.get("resets_at"),
    }

def parse_reset_time(iso_str):
    """Parse ISO timestamp to datetime."""
    if not iso_str:
        return None
    try:
        # Handle fractional seconds and timezone
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.astimezone(MST)
    except:
        return None

def estimate_quota():
    """Run the quota estimation."""
    now = datetime.now(MST)
    
    # Load current rate limit state
    data = load_rate_limit_data()
    if not data or data["utilization"] is None:
        print("⚠️  No rate limit data available")
        return
    
    current_pct = data["utilization"]
    reset_dt = parse_reset_time(data["resets_at"])
    
    if not reset_dt:
        print("⚠️  Cannot parse reset time")
        return
    
    # Calculate window timing
    # The 7-day window resets every 7 days, so it started 7 days before reset
    window_start = reset_dt - timedelta(days=7)
    hours_elapsed = (now - window_start).total_seconds() / 3600
    hours_remaining = (reset_dt - now).total_seconds() / 3600
    
    # Burn rate calculation
    burn_rate_per_hour = current_pct / hours_elapsed if hours_elapsed > 0 else 0
    
    # Projection
    additional_usage = burn_rate_per_hour * hours_remaining
    projected_total = current_pct + additional_usage
    
    headroom = 100 - current_pct
    safe_rate_per_hour = headroom / hours_remaining if hours_remaining > 0 else 0
    
    # Output
    print("=" * 60)
    print("ANTHROPIC 7-DAY QUOTA ESTIMATE")
    print("=" * 60)
    print()
    print(f"📅 Window: {window_start.strftime('%b %d %I:%M %p')} → {reset_dt.strftime('%b %d %I:%M %p MST')}")
    print(f"⏱️  Elapsed: {hours_elapsed:.1f}h ({hours_elapsed/24:.1f} days)")
    print(f"⏱️  Remaining: {hours_remaining:.1f}h ({hours_remaining/24:.1f} days)")
    print()
    print(f"📊 Current: {current_pct:.1f}%")
    print(f"📈 Burn rate: {burn_rate_per_hour:.3f}%/hour = {burn_rate_per_hour*24:.1f}%/day")
    print()
    print(f"🎯 PROJECTION (if burn rate continues):")
    print(f"   Additional usage: +{additional_usage:.1f}%")
    print(f"   Projected total: {projected_total:.1f}%")
    print()
    
    if projected_total >= 100:
        overage = projected_total - 100
        print(f"🔴 WILL HIT LIMIT (overage: {overage:.1f}%)")
        print(f"   Must reduce to: ≤{safe_rate_per_hour:.3f}%/hour (≤{safe_rate_per_hour*24:.1f}%/day)")
        reduction_pct = ((burn_rate_per_hour - safe_rate_per_hour) / burn_rate_per_hour) * 100
        print(f"   Reduction needed: {reduction_pct:.1f}% of current rate")
    elif projected_total >= 95:
        margin = 100 - projected_total
        print(f"🟡 TIGHT (margin: {margin:.1f}%)")
        print(f"   Safe daily rate: ≤{safe_rate_per_hour*24:.1f}%/day")
    else:
        margin = 100 - projected_total
        print(f"🟢 SAFE (margin: {margin:.1f}%)")
        print(f"   Can sustain: ≤{safe_rate_per_hour*24:.1f}%/day")
    
    print()
    print("=" * 60)

if __name__ == "__main__":
    estimate_quota()
