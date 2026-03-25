#!/usr/bin/env python3
"""
Token Usage Aggregator — reads OpenClaw session JSONL files and writes
a rolling usage summary to brain/status/token_usage.md

Zero extra API calls. Uses data already collected by OpenClaw.
"""

import json
import os
import re
import glob
import time
import subprocess
from datetime import datetime, timezone, timedelta
from collections import defaultdict

SESSIONS_DIR = os.path.expanduser("~/.openclaw/agents/main/sessions")
OUTPUT_FILE = os.path.expanduser("~/.openclaw/workspace/brain/status/token_usage.md")
RATE_LIMIT_CACHE = os.path.expanduser("~/.openclaw/workspace/brain/status/rate_limit_cache.json")
MST = timezone(timedelta(hours=-7))


def parse_ts(ts_val):
    """Parse timestamp — handles both ISO strings and epoch ms."""
    if isinstance(ts_val, (int, float)):
        return ts_val
    if isinstance(ts_val, str):
        try:
            dt = datetime.fromisoformat(ts_val.replace('Z', '+00:00'))
            return dt.timestamp() * 1000
        except:
            return 0
    return 0


def parse_sessions(hours_back=5):
    """Read all session JSONL files, extract usage data within the time window."""
    cutoff_ms = (time.time() - hours_back * 3600) * 1000
    
    usage_by_model = defaultdict(lambda: {
        "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
        "total_tokens": 0, "cost": 0.0, "requests": 0
    })
    
    total = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
             "total_tokens": 0, "cost": 0.0, "requests": 0}
    
    oldest_ts = None
    newest_ts = None
    
    jsonl_files = glob.glob(os.path.join(SESSIONS_DIR, "*.jsonl"))
    
    for fpath in jsonl_files:
        # Skip deleted files
        if ".deleted." in fpath:
            continue
        # Quick size check — skip empty
        if os.path.getsize(fpath) == 0:
            continue
            
        try:
            with open(fpath, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    ts = parse_ts(entry.get("timestamp", 0))
                    if ts < cutoff_ms:
                        continue
                    
                    msg = entry.get("message", {})
                    if not isinstance(msg, dict):
                        continue
                    
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    
                    model = msg.get("model", "unknown")
                    # Simplify model names
                    if "opus" in model:
                        model_key = "opus"
                    elif "sonnet" in model:
                        model_key = "sonnet"
                    elif "haiku" in model:
                        model_key = "haiku"
                    elif "codex" in model or "gpt" in model:
                        model_key = "codex/mini"
                    else:
                        model_key = model
                    
                    inp = usage.get("input", 0)
                    out = usage.get("output", 0)
                    cr = usage.get("cacheRead", 0)
                    cw = usage.get("cacheWrite", 0)
                    tt = usage.get("totalTokens", 0)
                    cost = usage.get("cost", {})
                    cost_total = cost.get("total", 0.0) if isinstance(cost, dict) else 0.0
                    
                    # Accumulate by model
                    m = usage_by_model[model_key]
                    m["input"] += inp
                    m["output"] += out
                    m["cache_read"] += cr
                    m["cache_write"] += cw
                    m["total_tokens"] += tt
                    m["cost"] += cost_total
                    m["requests"] += 1
                    
                    # Accumulate totals
                    total["input"] += inp
                    total["output"] += out
                    total["cache_read"] += cr
                    total["cache_write"] += cw
                    total["total_tokens"] += tt
                    total["cost"] += cost_total
                    total["requests"] += 1
                    
                    if oldest_ts is None or ts < oldest_ts:
                        oldest_ts = ts
                    if newest_ts is None or ts > newest_ts:
                        newest_ts = ts
                        
        except Exception:
            continue
    
    return total, usage_by_model, oldest_ts, newest_ts


def format_tokens(n):
    """Human-readable token count."""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


def _refresh_oauth_token(creds_path):
    """Refresh the OAuth token using the refresh_token from credentials.json.
    Updates the file in-place and returns the new access token, or None on failure."""
    try:
        with open(creds_path, 'r') as f:
            creds = json.load(f)
        refresh_token = creds.get("claudeAiOauth", {}).get("refreshToken", "")
        if not refresh_token:
            return None
        
        result = subprocess.run(
            ["curl", "-sS", "-X", "POST", OAUTH_TOKEN_URL,
             "-H", "Content-Type: application/json",
             "-d", json.dumps({
                 "grant_type": "refresh_token",
                 "refresh_token": refresh_token,
                 "client_id": OAUTH_CLIENT_ID
             })],
            capture_output=True, text=True, timeout=15
        )
        resp = json.loads(result.stdout)
        if "access_token" not in resp:
            # Log the error type for debugging
            err_type = resp.get("error", {}).get("type", "unknown") if isinstance(resp.get("error"), dict) else resp.get("error", "unknown")
            import sys
            print(f"OAuth refresh failed: {err_type}", file=sys.stderr)
            return None
        
        # Update credentials.json with new token
        creds["claudeAiOauth"]["accessToken"] = resp["access_token"]
        if "refresh_token" in resp:
            creds["claudeAiOauth"]["refreshToken"] = resp["refresh_token"]
        creds["claudeAiOauth"]["expiresAt"] = int((time.time() + resp["expires_in"]) * 1000)
        
        with open(creds_path, 'w') as f:
            json.dump(creds, f, indent=2)
        
        return resp["access_token"]
    except Exception:
        return None


def _fetch_usage_with_token(token):
    """Fetch usage data with a specific token. Returns data or None."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-H", f"Authorization: Bearer {token}",
             "-H", "anthropic-beta: oauth-2025-04-20",
             "https://api.anthropic.com/api/oauth/usage"],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        if isinstance(data, dict) and data.get('type') == 'error':
            return None
        return data
    except Exception:
        return None


def _try_fetch_usage(creds_path):
    """Fetch usage data, refreshing the OAuth token if needed."""
    with open(creds_path, 'r') as f:
        creds = json.load(f)
    token = creds.get("claudeAiOauth", {}).get("accessToken", "")
    if not token:
        return None
    
    # Check if token is expired (with 5min buffer)
    expires_at = creds.get("claudeAiOauth", {}).get("expiresAt", 0)
    token_expired = (time.time() * 1000 + 300000) >= expires_at
    
    if not token_expired:
        # Try with current token first
        data = _fetch_usage_with_token(token)
        if data is not None:
            return data
    
    # Token expired or fetch failed — refresh it
    new_token = _refresh_oauth_token(creds_path)
    if not new_token:
        return None
    
    return _fetch_usage_with_token(new_token)


def _validate_usage_data(data):
    """Validate that API response contains real numeric utilization values.
    Returns True only if at least one window has a numeric utilization."""
    if not isinstance(data, dict):
        return False
    for key in ("five_hour", "seven_day", "seven_day_sonnet"):
        window = data.get(key, {})
        if isinstance(window, dict):
            util = window.get("utilization")
            if isinstance(util, (int, float)):
                return True
    return False


def _save_rate_limit_cache(data):
    """Save validated rate limit data to JSON sidecar with timestamp."""
    try:
        cache = {
            "data": data,
            "fetched_at": datetime.now(MST).isoformat(),
            "fetched_ts": time.time(),
        }
        os.makedirs(os.path.dirname(RATE_LIMIT_CACHE), exist_ok=True)
        with open(RATE_LIMIT_CACHE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _load_rate_limit_cache(max_age_hours=24):
    """Load last-known-good rate limit data from JSON sidecar.
    Returns (data, age_minutes) or (None, None) if missing/expired."""
    try:
        if not os.path.exists(RATE_LIMIT_CACHE):
            return None, None
        with open(RATE_LIMIT_CACHE, 'r') as f:
            cache = json.load(f)
        fetched_ts = cache.get("fetched_ts", 0)
        age_seconds = time.time() - fetched_ts
        if age_seconds > max_age_hours * 3600:
            return None, None
        return cache.get("data"), round(age_seconds / 60)
    except Exception:
        return None, None


def fetch_anthropic_usage():
    """Fetch real utilization % from Anthropic OAuth usage endpoint.
    Retries once after 10s to allow gateway to refresh an expired token.
    Only returns data with validated numeric utilization values."""
    creds_path = os.path.expanduser("~/.claude/.credentials.json")
    try:
        data = _try_fetch_usage(creds_path)
        if data is not None and _validate_usage_data(data):
            _save_rate_limit_cache(data)
            return data
        # First attempt failed or returned non-numeric — wait for gateway to refresh token, then retry
        time.sleep(10)
        data = _try_fetch_usage(creds_path)
        if data is not None and _validate_usage_data(data):
            _save_rate_limit_cache(data)
            return data
        return None
    except Exception:
        return None


def write_report():
    now = datetime.now(MST)
    
    # Fetch real Anthropic utilization — use existing values if API temporarily unavailable
    usage_api = fetch_anthropic_usage()
    
    # 5-hour window
    total_5h, by_model_5h, oldest_5h, newest_5h = parse_sessions(hours_back=5)
    # 24-hour window
    total_24h, by_model_24h, _, _ = parse_sessions(hours_back=24)
    
    lines = [
        "# Token Usage",
        f"**Updated:** {now.strftime('%Y-%m-%d %H:%M MST')}",
        "",
    ]
    
    # Anthropic real utilization section
    # Use fresh API data, or fall back to JSON sidecar cache (never regex-parse markdown)
    rate_data = usage_api
    stale_minutes = None
    if not rate_data:
        rate_data, stale_minutes = _load_rate_limit_cache(max_age_hours=168)  # 7 days — show stale data rather than nothing
    
    if rate_data:
        fh = rate_data.get("five_hour", {})
        sd = rate_data.get("seven_day", {})
        sd_sonnet = rate_data.get("seven_day_sonnet", {})
        
        fh_pct = fh.get("utilization", "?")
        sd_pct = sd.get("utilization", "?")
        sd_sonnet_pct = sd_sonnet.get("utilization", "?") if sd_sonnet else "?"
        
        fh_reset = fh.get("resets_at", "")
        sd_reset = sd.get("resets_at", "")
        sd_sonnet_reset = sd_sonnet.get("resets_at", "") if sd_sonnet else sd_reset
        
        # Parse reset times to MST
        def fmt_reset(iso_str):
            if not iso_str:
                return "?"
            try:
                dt = datetime.fromisoformat(iso_str)
                return dt.astimezone(MST).strftime("%b %d %I:%M %p MST")
            except:
                return iso_str
        
        # Warning levels
        fh_warn = " ⚠️" if isinstance(fh_pct, (int, float)) and fh_pct >= 70 else ""
        sd_warn = " 🔴" if isinstance(sd_pct, (int, float)) and sd_pct >= 85 else (" ⚠️" if isinstance(sd_pct, (int, float)) and sd_pct >= 60 else "")
        
        # Label as stale if using cached data
        header = "## ⚡ Anthropic Rate Limits (Live)"
        if stale_minutes is not None:
            header = f"## ⚡ Anthropic Rate Limits (Cached — {stale_minutes}min ago)"
        
        lines.extend([
            header,
            f"| Window | Usage | Resets At |",
            f"|--------|-------|-----------|",
            f"| 5-hour | **{fh_pct}%**{fh_warn} | {fmt_reset(fh_reset)} |",
            f"| 7-day (all) | **{sd_pct}%**{sd_warn} | {fmt_reset(sd_reset)} |",
            f"| 7-day (Sonnet) | **{sd_sonnet_pct}%** | {fmt_reset(sd_sonnet_reset)} |",
            "",
        ])
    
    lines.extend([
        "## Rolling 5-Hour Window",
        f"- **Total Tokens:** {format_tokens(total_5h['total_tokens'])} ({total_5h['requests']} requests)",
        f"- **Input:** {format_tokens(total_5h['input'])} | **Output:** {format_tokens(total_5h['output'])}",
        f"- **Cache Read:** {format_tokens(total_5h['cache_read'])} | **Cache Write:** {format_tokens(total_5h['cache_write'])}",
        f"- **Cost (est):** ${total_5h['cost']:.2f}",
        "",
        "### By Model (5h)",
        "| Model | Requests | Tokens | Output | Cost |",
        "|-------|----------|--------|--------|------|",
    ])
    
    for model in sorted(by_model_5h.keys(), key=lambda k: by_model_5h[k]["total_tokens"], reverse=True):
        m = by_model_5h[model]
        lines.append(f"| {model} | {m['requests']} | {format_tokens(m['total_tokens'])} | {format_tokens(m['output'])} | ${m['cost']:.2f} |")
    
    lines.extend([
        "",
        "## Rolling 24-Hour Window",
        f"- **Total Tokens:** {format_tokens(total_24h['total_tokens'])} ({total_24h['requests']} requests)",
        f"- **Output Tokens:** {format_tokens(total_24h['output'])}",
        f"- **Cost (est):** ${total_24h['cost']:.2f}",
        "",
        "### By Model (24h)",
        "| Model | Requests | Tokens | Output | Cost |",
        "|-------|----------|--------|--------|------|",
    ])
    
    for model in sorted(by_model_24h.keys(), key=lambda k: by_model_24h[k]["total_tokens"], reverse=True):
        m = by_model_24h[model]
        lines.append(f"| {model} | {m['requests']} | {format_tokens(m['total_tokens'])} | {format_tokens(m['output'])} | ${m['cost']:.2f} |")
    
    lines.extend([
        "",
        "---",
        "*Note: Max 5x plan is $100/mo flat. Cost shown is equivalent API pricing, not actual charges.*",
        "*Live utilization from Anthropic OAuth usage API.*",
    ])
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    
    print(f"Written to {OUTPUT_FILE}")
    print(f"5h: {format_tokens(total_5h['total_tokens'])} tokens, {total_5h['requests']} requests, ${total_5h['cost']:.2f}")


if __name__ == "__main__":
    write_report()
