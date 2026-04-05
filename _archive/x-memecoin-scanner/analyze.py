#!/usr/bin/env python3
"""
Analyze X scanner results
Shows top contracts, hype scores, user reach
"""

import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

SIGNALS_LOG = Path(__file__).parent / 'logs' / 'x_signals.jsonl'

def load_signals(hours_back=24):
    """Load signals from last N hours"""
    if not SIGNALS_LOG.exists():
        return []
    
    cutoff = datetime.now().timestamp() - (hours_back * 3600)
    signals = []
    
    for line in SIGNALS_LOG.read_text().strip().split('\n'):
        if not line:
            continue
        signal = json.loads(line)
        # Parse ISO timestamp
        ts = datetime.fromisoformat(signal['timestamp'].replace('Z', '+00:00')).timestamp()
        if ts >= cutoff:
            signals.append(signal)
    
    return signals


def analyze():
    """Analyze collected signals"""
    
    signals = load_signals(24)
    
    if not signals:
        print("No signals found in last 24 hours")
        print("Run the scanner first: python scanner.py")
        return
    
    print(f"=== X Scanner Analysis (Last 24h) ===\n")
    print(f"Total signals: {len(signals)}\n")
    
    # Contract frequency
    contract_data = defaultdict(lambda: {
        'count': 0,
        'users': set(),
        'queries': set(),
        'total_hype': 0,
        'total_likes': 0,
        'total_rts': 0,
        'tweets': []
    })
    
    for signal in signals:
        for contract in signal['contracts']:
            data = contract_data[contract]
            data['count'] += 1
            data['users'].add(signal['user'])
            data['queries'].add(signal['query'])
            data['total_hype'] += signal['hype_score']
            data['total_likes'] += signal['likes']
            data['total_rts'] += signal['retweets']
            data['tweets'].append(signal['url'])
    
    # Top contracts by confluence
    top_contracts = sorted(
        contract_data.items(),
        key=lambda x: (len(x[1]['users']), x[1]['total_hype']),
        reverse=True
    )[:10]
    
    if top_contracts:
        print("🎯 TOP 10 CONTRACTS (by confluence):\n")
        for i, (contract, data) in enumerate(top_contracts, 1):
            print(f"{i}. {contract}")
            print(f"   Mentions: {data['count']} tweets")
            print(f"   Users: {len(data['users'])} different accounts")
            print(f"   Queries: {len(data['queries'])} search terms")
            print(f"   Hype Score: {data['total_hype']}")
            print(f"   Engagement: {data['total_likes']} likes, {data['total_rts']} RTs")
            print(f"   First tweet: {data['tweets'][0]}")
            print()
    
    # Top users
    user_signals = defaultdict(int)
    user_reach = {}
    for signal in signals:
        user_signals[signal['user']] += 1
        user_reach[signal['user']] = signal['user_followers']
    
    top_users = sorted(user_signals.items(), key=lambda x: x[1], reverse=True)[:5]
    
    print("\n👥 TOP SIGNAL USERS:\n")
    for user, count in top_users:
        print(f"  @{user}: {count} signals ({user_reach[user]:,} followers)")
    
    # Query effectiveness
    query_counts = defaultdict(int)
    for signal in signals:
        query_counts[signal['query']] += 1
    
    print("\n🔍 QUERY EFFECTIVENESS:\n")
    for query, count in sorted(query_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  '{query}': {count} signals")
    
    # Average hype
    avg_hype = sum(s['hype_score'] for s in signals) / len(signals)
    print(f"\n📊 Average Hype Score: {avg_hype:.1f}")


if __name__ == '__main__':
    analyze()
