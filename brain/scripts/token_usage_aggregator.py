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


def write_report():
    now = datetime.now(MST)
    
    # 5-hour window
    total_5h, by_model_5h, oldest_5h, newest_5h = parse_sessions(hours_back=5)
    # 24-hour window
    total_24h, by_model_24h, _, _ = parse_sessions(hours_back=24)
    
    lines = [
        "# Token Usage",
        f"**Updated:** {now.strftime('%Y-%m-%d %H:%M MST')}",
        "",
        "## Rolling 5-Hour Window",
        f"- **Total Tokens:** {format_tokens(total_5h['total_tokens'])} ({total_5h['requests']} requests)",
        f"- **Input:** {format_tokens(total_5h['input'])} | **Output:** {format_tokens(total_5h['output'])}",
        f"- **Cache Read:** {format_tokens(total_5h['cache_read'])} | **Cache Write:** {format_tokens(total_5h['cache_write'])}",
        f"- **Cost (est):** ${total_5h['cost']:.2f}",
        "",
        "### By Model (5h)",
        "| Model | Requests | Tokens | Output | Cost |",
        "|-------|----------|--------|--------|------|",
    ]
    
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
        f"*Anthropic doesn't publish the Max 5x rate limit denominator, so exact utilization % is unknown.*",
    ])
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    
    print(f"Written to {OUTPUT_FILE}")
    print(f"5h: {format_tokens(total_5h['total_tokens'])} tokens, {total_5h['requests']} requests, ${total_5h['cost']:.2f}")


if __name__ == "__main__":
    write_report()
