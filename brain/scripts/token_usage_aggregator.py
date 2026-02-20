#!/usr/bin/env python3
"""
Token Usage Aggregator — reads OpenClaw session JSONL files and writes
a rolling usage summary to brain/status/token_usage.md

Zero extra API calls. Uses data already collected by OpenClaw.
"""

import json
import os
import glob
import time
import subprocess
from datetime import datetime, timezone, timedelta
from collections import defaultdict

SESSIONS_DIR = os.path.expanduser("~/.openclaw/agents/main/sessions")
OUTPUT_FILE = os.path.expanduser("~/.openclaw/workspace/brain/status/token_usage.md")
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


def fetch_anthropic_usage():
    """Fetch real utilization % from Anthropic OAuth usage endpoint."""
    creds_path = os.path.expanduser("~/.claude/.credentials.json")
    try:
        with open(creds_path, 'r') as f:
            creds = json.load(f)
        token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        if not token:
            return None
        result = subprocess.run(
            ["curl", "-s", "-H", f"Authorization: Bearer {token}",
             "-H", "anthropic-beta: oauth-2025-04-20",
             "https://api.anthropic.com/api/oauth/usage"],
            capture_output=True, text=True, timeout=10
        )
        return json.loads(result.stdout)
    except Exception:
        return None


def write_report():
    now = datetime.now(MST)
    
    # Fetch real Anthropic utilization
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
    if usage_api:
        fh = usage_api.get("five_hour", {})
        sd = usage_api.get("seven_day", {})
        sd_sonnet = usage_api.get("seven_day_sonnet", {})
        
        fh_pct = fh.get("utilization", "?")
        sd_pct = sd.get("utilization", "?")
        sd_sonnet_pct = sd_sonnet.get("utilization", "?") if sd_sonnet else "?"
        
        fh_reset = fh.get("resets_at", "")
        sd_reset = sd.get("resets_at", "")
        
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
        
        lines.extend([
            "## ⚡ Anthropic Rate Limits (Live)",
            f"| Window | Usage | Resets At |",
            f"|--------|-------|-----------|",
            f"| 5-hour | **{fh_pct}%**{fh_warn} | {fmt_reset(fh_reset)} |",
            f"| 7-day (all) | **{sd_pct}%**{sd_warn} | {fmt_reset(sd_reset)} |",
            f"| 7-day (Sonnet) | **{sd_sonnet_pct}%** | {fmt_reset(sd_reset)} |",
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
