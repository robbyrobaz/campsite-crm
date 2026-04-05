#!/usr/bin/env python3
"""
AI Token Usage Analyzer - OpenClaw + Hermes
Parses all session JSONL files from both systems for comprehensive 30-day usage report
"""
import json
import glob
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple

def parse_openclaw_sessions(days=30) -> Dict:
    """Parse OpenClaw agent sessions for token usage"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = cutoff.timestamp() * 1000
    
    usage_by_model = defaultdict(lambda: {
        'requests': 0,
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_read': 0,
        'cache_write': 0,
        'total_tokens': 0,
        'cost': 0.0
    })
    
    agents_dir = Path.home() / '.openclaw/agents'
    session_count = 0
    
    for agent_dir in agents_dir.glob('*/sessions'):
        if not agent_dir.exists():
            continue
        
        agent_name = agent_dir.parent.name
        
        # Include all session files
        for fpath in list(agent_dir.glob("*.jsonl")) + list(agent_dir.glob("*.jsonl.reset.*")) + list(agent_dir.glob("*.jsonl.deleted.*")):
            if not fpath.exists() or fpath.stat().st_size == 0:
                continue
            
            try:
                with open(fpath, 'r') as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                            ts = entry.get("timestamp", 0)
                            
                            # Parse timestamp
                            if isinstance(ts, str):
                                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                                ts_ms = dt.timestamp() * 1000
                            else:
                                ts_ms = ts
                            
                            if ts_ms < cutoff_ms:
                                continue
                            
                            # Extract usage data
                            msg = entry.get("message", {})
                            usage = msg.get("usage")
                            if not usage:
                                continue
                            
                            model = msg.get("model", "unknown")
                            
                            # Normalize model name
                            if "opus" in model.lower():
                                model_key = "anthropic-opus"
                            elif "sonnet" in model.lower():
                                model_key = "anthropic-sonnet"
                            elif "haiku" in model.lower():
                                model_key = "anthropic-haiku"
                            elif "gpt-5" in model.lower() or "codex" in model.lower():
                                model_key = "openai-gpt5-codex"
                            elif "nemotron" in model.lower():
                                model_key = "openrouter-nemotron"
                            else:
                                model_key = model
                            
                            # Aggregate usage
                            usage_by_model[model_key]['requests'] += 1
                            usage_by_model[model_key]['input_tokens'] += usage.get('input', 0)
                            usage_by_model[model_key]['output_tokens'] += usage.get('output', 0)
                            usage_by_model[model_key]['cache_read'] += usage.get('cacheRead', 0)
                            usage_by_model[model_key]['cache_write'] += usage.get('cacheWrite', 0)
                            usage_by_model[model_key]['total_tokens'] += usage.get('totalTokens', 0)
                            
                            cost_data = usage.get('cost', {})
                            if isinstance(cost_data, dict):
                                usage_by_model[model_key]['cost'] += cost_data.get('total', 0)
                            
                            session_count += 1
                            
                        except Exception as e:
                            continue
            except Exception as e:
                continue
    
    return {
        'system': 'OpenClaw',
        'sessions_analyzed': session_count,
        'usage_by_model': dict(usage_by_model)
    }

def parse_hermes_sessions(days=30) -> Dict:
    """Parse Hermes sessions (main + profiles) for token usage
    
    NOTE: Hermes doesn't track actual API usage in its database, only estimated
    token counts based on character length. If Hermes uses the same Anthropic API
    key as OpenClaw, the actual usage is already captured in OpenClaw's data.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_sec = cutoff.timestamp()  # Hermes uses SECONDS, not milliseconds!
    
    usage_by_model = defaultdict(lambda: {
        'requests': 0,
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_read': 0,
        'cache_write': 0,
        'total_tokens': 0,
        'cost': 0.0,
        'estimated': True  # Flag that these are estimates, not actual
    })
    
    session_count = 0
    
    # Parse from SQLite databases (Hermes stores in state.db, not JSONL)
    
    import sqlite3
    
    # Check main Hermes database
    hermes_db = Path.home() / '.hermes/state.db'
    
    # Check profile databases
    hermes_profiles = Path.home() / '.hermes/profiles'
    
    all_dbs = [hermes_db]
    if hermes_profiles.exists():
        for profile_dir in hermes_profiles.iterdir():
            profile_db = profile_dir / 'state.db'
            if profile_db.exists():
                all_dbs.append(profile_db)
    
    for db_path in all_dbs:
        if not db_path.exists():
            continue
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Query sessions table for usage data
            cursor.execute("""
                SELECT model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, started_at
                FROM sessions
                WHERE started_at > ?
            """, (cutoff_sec,))
            
            for row in cursor.fetchall():
                model, input_tok, output_tok, cache_read, cache_write, ts = row
                
                if not model:
                    model = "unknown"
                
                # Normalize model name
                if "opus" in model.lower():
                    model_key = "anthropic-opus"
                elif "sonnet" in model.lower():
                    model_key = "anthropic-sonnet"
                elif "haiku" in model.lower():
                    model_key = "anthropic-haiku"
                else:
                    model_key = model
                
                # Aggregate usage (these are estimates, not actual API counts)
                usage_by_model[model_key]['requests'] += 1
                usage_by_model[model_key]['input_tokens'] += input_tok or 0
                usage_by_model[model_key]['output_tokens'] += output_tok or 0
                usage_by_model[model_key]['cache_read'] += cache_read or 0
                usage_by_model[model_key]['cache_write'] += cache_write or 0
                usage_by_model[model_key]['total_tokens'] += (input_tok or 0) + (output_tok or 0) + (cache_read or 0) + (cache_write or 0)
                
                session_count += 1
            
            conn.close()
        except Exception as e:
            continue
    
    return {
        'system': 'Hermes',
        'sessions_analyzed': session_count,
        'usage_by_model': dict(usage_by_model)
    }

def format_tokens(num):
    """Format token counts with M/K suffixes"""
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    return str(num)

def generate_report(openclaw_data, hermes_data, days=30):
    """Generate comprehensive markdown report"""
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)
    
    report = f"""# AI Token Usage Report
**Period:** {start_date.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')} ({days} days)
**Generated:** {now.strftime('%Y-%m-%d %H:%M:%S UTC')}

---

## Summary

### OpenClaw
- **Sessions Analyzed:** {openclaw_data['sessions_analyzed']:,}
- **Total Models:** {len(openclaw_data['usage_by_model'])}
- **Data Quality:** ✅ Actual API usage (from provider responses)

### Hermes  
- **Sessions Analyzed:** {hermes_data['sessions_analyzed']:,}
- **Total Models:** {len(hermes_data['usage_by_model'])}
- **Data Quality:** ⚠️ Estimated token counts (character-based, not actual API usage)

**IMPORTANT:** If OpenClaw and Hermes use the same Anthropic API key, all usage is billed together.
The OpenClaw data above likely includes Hermes usage (both hit the same account).
Hermes estimates below are for informational purposes only - they may double-count with OpenClaw.

---

## OpenClaw Usage by Model

"""
    
    # OpenClaw table
    oc_models = sorted(openclaw_data['usage_by_model'].items(), key=lambda x: x[1]['total_tokens'], reverse=True)
    
    report += "| Model | Requests | Input | Output | Cache Read | Cache Write | Total Tokens | Est. Cost |\n"
    report += "|-------|----------|-------|--------|------------|-------------|--------------|----------|\n"
    
    oc_totals = {
        'requests': 0,
        'input': 0,
        'output': 0,
        'cache_read': 0,
        'cache_write': 0,
        'total': 0,
        'cost': 0.0
    }
    
    for model, stats in oc_models:
        report += f"| **{model}** | {stats['requests']:,} | {format_tokens(stats['input_tokens'])} | {format_tokens(stats['output_tokens'])} | {format_tokens(stats['cache_read'])} | {format_tokens(stats['cache_write'])} | **{format_tokens(stats['total_tokens'])}** | ${stats['cost']:.2f} |\n"
        
        oc_totals['requests'] += stats['requests']
        oc_totals['input'] += stats['input_tokens']
        oc_totals['output'] += stats['output_tokens']
        oc_totals['cache_read'] += stats['cache_read']
        oc_totals['cache_write'] += stats['cache_write']
        oc_totals['total'] += stats['total_tokens']
        oc_totals['cost'] += stats['cost']
    
    report += f"| **TOTAL** | **{oc_totals['requests']:,}** | **{format_tokens(oc_totals['input'])}** | **{format_tokens(oc_totals['output'])}** | **{format_tokens(oc_totals['cache_read'])}** | **{format_tokens(oc_totals['cache_write'])}** | **{format_tokens(oc_totals['total'])}** | **${oc_totals['cost']:.2f}** |\n\n"
    
    # Hermes table
    report += "---\n\n## Hermes Usage by Model (ESTIMATED - Not Actual API Usage)\n\n"
    report += "⚠️ **Note:** These are estimated token counts from Hermes database, not actual API-reported usage.\n"
    report += "If Hermes uses the same API key as OpenClaw, this usage is already counted above.\n\n"
    
    h_models = sorted(hermes_data['usage_by_model'].items(), key=lambda x: x[1]['total_tokens'], reverse=True)
    
    report += "| Model | Requests | Input | Output | Cache Read | Cache Write | Total Tokens | Est. Cost |\n"
    report += "|-------|----------|-------|--------|------------|-------------|--------------|----------|\n"
    
    h_totals = {
        'requests': 0,
        'input': 0,
        'output': 0,
        'cache_read': 0,
        'cache_write': 0,
        'total': 0,
        'cost': 0.0
    }
    
    for model, stats in h_models:
        report += f"| **{model}** | {stats['requests']:,} | {format_tokens(stats['input_tokens'])} | {format_tokens(stats['output_tokens'])} | {format_tokens(stats['cache_read'])} | {format_tokens(stats['cache_write'])} | **{format_tokens(stats['total_tokens'])}** | ${stats['cost']:.2f} |\n"
        
        h_totals['requests'] += stats['requests']
        h_totals['input'] += stats['input_tokens']
        h_totals['output'] += stats['output_tokens']
        h_totals['cache_read'] += stats['cache_read']
        h_totals['cache_write'] += stats['cache_write']
        h_totals['total'] += stats['total_tokens']
        h_totals['cost'] += stats['cost']
    
    report += f"| **TOTAL** | **{h_totals['requests']:,}** | **{format_tokens(h_totals['input'])}** | **{format_tokens(h_totals['output'])}** | **{format_tokens(h_totals['cache_read'])}** | **{format_tokens(h_totals['cache_write'])}** | **{format_tokens(h_totals['total'])}** | **${h_totals['cost']:.2f}** |\n\n"
    
    # Combined totals
    combined_total = oc_totals['total'] + h_totals['total']
    combined_cost = oc_totals['cost'] + h_totals['cost']
    combined_requests = oc_totals['requests'] + h_totals['requests']
    
    report += f"""---

## Combined Totals (OpenClaw + Hermes)

- **Total Requests:** {combined_requests:,}
- **Total Tokens:** {format_tokens(combined_total)} ({combined_total:,})
- **Estimated Cost:** ${combined_cost:.2f}
- **Cost per Day:** ${combined_cost/days:.2f}
- **Projected Monthly:** ${(combined_cost/days)*30:.2f}

### Cache Efficiency
- **Cache Read Tokens:** {format_tokens(oc_totals['cache_read'] + h_totals['cache_read'])}
- **Cache Hit Rate:** {((oc_totals['cache_read'] + h_totals['cache_read']) / combined_total * 100):.1f}%

---

## Current Subscription

**Claude Max 20x:** $200/month

### Analysis
- **Actual Usage:** ${(combined_cost/days)*30:.2f}/month (projected)
- **Subscription Value:** {'✅ Good deal' if (combined_cost/days)*30 > 200 else '⚠️ May be overpaying'}
- **Cache Savings:** Estimated ${((oc_totals['cache_read'] + h_totals['cache_read']) * 0.003 / 1000):.2f} saved via prompt caching

---

## Alternative Provider Options

### OpenRouter
- **Pros:** Access to multiple models, pay-per-use, no subscription
- **Cons:** No prompt caching on most models
- **Estimated Cost:** ${combined_cost:.2f} for this {days}-day period (without caching benefits)

### Direct Anthropic API
- **Pros:** Full caching support, usage-based pricing
- **Cons:** Higher per-token cost than subscription if usage is heavy
- **Estimated Cost:** ${combined_cost:.2f} for this {days}-day period

### Keep Claude Max 20x If:
1. Cache hit rate stays above 80% (currently {((oc_totals['cache_read'] + h_totals['cache_read']) / combined_total * 100):.1f}%)
2. Projected monthly > $200 (currently ${(combined_cost/days)*30:.2f})
3. Need higher rate limits for bursts

### Switch to Pay-Per-Use If:
1. Usage drops significantly
2. Cache hit rate falls below 50%
3. Projected monthly consistently < $150

---

**Next Steps:**
1. Monitor usage for another 30 days
2. Compare cache efficiency trends
3. Test OpenRouter for non-cached workloads
4. Evaluate if Haiku can replace Sonnet for some tasks

"""
    
    return report

if __name__ == "__main__":
    print("Analyzing OpenClaw sessions...")
    openclaw_data = parse_openclaw_sessions(days=30)
    
    print("Analyzing Hermes sessions...")
    hermes_data = parse_hermes_sessions(days=30)
    
    print("Generating report...")
    report = generate_report(openclaw_data, hermes_data, days=30)
    
    # Save to repo
    output_path = Path.home() / '.openclaw/workspace/brain/reports/ai-usage-30day-report.md'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        f.write(report)
    
    print(f"\n✅ Report saved to: {output_path}")
    print(f"\nOpenClaw: {openclaw_data['sessions_analyzed']} sessions, {len(openclaw_data['usage_by_model'])} models")
    print(f"Hermes: {hermes_data['sessions_analyzed']} sessions, {len(hermes_data['usage_by_model'])} models")
    print("\nPreview:\n")
    print(report[:1000] + "...\n")
