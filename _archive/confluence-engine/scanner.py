#!/usr/bin/env python3
"""
Multi-Platform Confluence Engine
Combines X/Twitter + Telegram signals to find high-confidence contracts
"""

import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Input sources
X_SIGNALS = Path.home() / '.openclaw/workspace/x-memecoin-scanner/logs/x_signals.jsonl'
TG_SIGNALS = Path.home() / '.openclaw/workspace/autonomous-memecoin-hunter/logs/signals.jsonl'

# Output
BASE_DIR = Path(__file__).parent
CONFLUENCE_LOG = BASE_DIR / 'logs' / 'high_confidence.jsonl'
CONFLUENCE_LOG.parent.mkdir(parents=True, exist_ok=True)

# Confluence settings
CONFLUENCE_WINDOW_MINUTES = 15  # Signals must be within 15 min of each other
MIN_CONFLUENCE_SCORE = 10.0      # Minimum score to flag as high-confidence

# Platform weights (X is earliest, Telegram validates)
WEIGHT_TWITTER = 3.0
WEIGHT_TELEGRAM = 2.0


def parse_timestamp(ts_str: str) -> float:
    """Parse ISO timestamp to Unix timestamp"""
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.timestamp()
    except:
        return 0.0


def load_x_signals(hours_back=2) -> List[Dict]:
    """Load X/Twitter signals from last N hours"""
    if not X_SIGNALS.exists():
        return []
    
    cutoff = datetime.now(timezone.utc).timestamp() - (hours_back * 3600)
    signals = []
    
    try:
        for line in X_SIGNALS.read_text().strip().split('\n'):
            if not line:
                continue
            signal = json.loads(line)
            ts = parse_timestamp(signal.get('timestamp', ''))
            if ts >= cutoff:
                signals.append(signal)
    except Exception as e:
        print(f"⚠️  Error loading X signals: {e}")
    
    return signals


def load_telegram_signals(hours_back=2) -> List[Dict]:
    """Load Telegram signals from last N hours"""
    if not TG_SIGNALS.exists():
        return []
    
    cutoff = datetime.now(timezone.utc).timestamp() - (hours_back * 3600)
    signals = []
    
    try:
        for line in TG_SIGNALS.read_text().strip().split('\n'):
            if not line:
                continue
            signal = json.loads(line)
            ts = parse_timestamp(signal.get('timestamp', ''))
            if ts >= cutoff:
                signals.append(signal)
    except Exception as e:
        print(f"⚠️  Error loading Telegram signals: {e}")
    
    return signals


def build_contract_timeline(x_signals: List[Dict], tg_signals: List[Dict]) -> Dict:
    """Build timeline of all contract mentions across platforms"""
    
    timeline = defaultdict(lambda: {
        'twitter_mentions': [],
        'telegram_mentions': [],
        'first_seen': None,
        'platforms': set(),
    })
    
    # Add X mentions
    for signal in x_signals:
        for contract in signal.get('contracts', []):
            data = timeline[contract]
            data['twitter_mentions'].append({
                'timestamp': parse_timestamp(signal['timestamp']),
                'user': signal.get('user', ''),
                'hype_score': signal.get('hype_score', 0),
                'url': signal.get('url', ''),
                'likes': signal.get('likes', 0),
                'retweets': signal.get('retweets', 0),
            })
            data['platforms'].add('twitter')
    
    # Add Telegram mentions
    for signal in tg_signals:
        contract = signal.get('contract_address')
        if not contract:
            continue
        
        data = timeline[contract]
        data['telegram_mentions'].append({
            'timestamp': parse_timestamp(signal['timestamp']),
            'channel': signal.get('channel', ''),
            'hype_score': signal.get('hype_score', 0),
            'message': signal.get('message_text', '')[:100],
        })
        data['platforms'].add('telegram')
    
    # Find first mention for each contract
    for contract, data in timeline.items():
        all_timestamps = []
        all_timestamps.extend([m['timestamp'] for m in data['twitter_mentions']])
        all_timestamps.extend([m['timestamp'] for m in data['telegram_mentions']])
        
        if all_timestamps:
            data['first_seen'] = min(all_timestamps)
    
    return timeline


def calculate_confluence_score(contract: str, data: Dict) -> float:
    """Calculate confluence score for a contract"""
    
    score = 0.0
    
    # Platform diversity bonus
    platforms = len(data['platforms'])
    if platforms >= 2:
        score += 10.0  # Strong multi-platform bonus
    
    # Twitter signals
    twitter_count = len(data['twitter_mentions'])
    twitter_hype = sum(m['hype_score'] for m in data['twitter_mentions'])
    twitter_engagement = sum(m['likes'] + m['retweets'] for m in data['twitter_mentions'])
    
    score += twitter_count * WEIGHT_TWITTER
    score += (twitter_hype / 10.0) * WEIGHT_TWITTER  # Normalize hype
    score += (twitter_engagement / 20.0)  # Engagement bonus
    
    # Telegram signals
    telegram_count = len(data['telegram_mentions'])
    telegram_hype = sum(m['hype_score'] for m in data['telegram_mentions'])
    
    score += telegram_count * WEIGHT_TELEGRAM
    score += (telegram_hype / 10.0) * WEIGHT_TELEGRAM
    
    # Time confluence bonus (mentions within window)
    if platforms >= 2:
        # Check if X and Telegram mentions are within the confluence window
        twitter_times = [m['timestamp'] for m in data['twitter_mentions']]
        telegram_times = [m['timestamp'] for m in data['telegram_mentions']]
        
        for t_time in twitter_times:
            for tg_time in telegram_times:
                time_diff = abs(t_time - tg_time)
                if time_diff <= (CONFLUENCE_WINDOW_MINUTES * 60):
                    score += 5.0  # Bonus for tight timing
                    break
    
    return score


def find_high_confidence_signals():
    """Main confluence detection"""
    
    print(f"=== Multi-Platform Confluence Engine ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}\n")
    
    # Load signals from last 2 hours
    print("Loading signals...")
    x_signals = load_x_signals(hours_back=2)
    tg_signals = load_telegram_signals(hours_back=2)
    
    print(f"  X/Twitter: {len(x_signals)} signals")
    print(f"  Telegram:  {len(tg_signals)} signals")
    
    if not x_signals and not tg_signals:
        print("\n⚠️  No signals found. Make sure both scanners are running!")
        return
    
    # Build contract timeline
    print("\nBuilding contract timeline...")
    timeline = build_contract_timeline(x_signals, tg_signals)
    
    print(f"  Unique contracts: {len(timeline)}")
    
    # Calculate scores
    print("\nCalculating confluence scores...")
    scored_contracts = []
    
    for contract, data in timeline.items():
        score = calculate_confluence_score(contract, data)
        
        if score >= MIN_CONFLUENCE_SCORE:
            scored_contracts.append({
                'contract': contract,
                'score': score,
                'platforms': list(data['platforms']),
                'twitter_mentions': len(data['twitter_mentions']),
                'telegram_mentions': len(data['telegram_mentions']),
                'first_seen': datetime.fromtimestamp(data['first_seen'], tz=timezone.utc).isoformat() if data['first_seen'] else None,
                'twitter_details': data['twitter_mentions'][:3],  # Top 3
                'telegram_details': data['telegram_mentions'][:3],
            })
    
    # Sort by score
    scored_contracts.sort(key=lambda x: x['score'], reverse=True)
    
    if scored_contracts:
        print(f"\n🎯 HIGH-CONFIDENCE SIGNALS ({len(scored_contracts)} contracts):\n")
        
        for i, item in enumerate(scored_contracts, 1):
            print(f"{i}. {item['contract'][:20]}...")
            print(f"   Score: {item['score']:.1f}")
            print(f"   Platforms: {', '.join(item['platforms'])}")
            print(f"   Twitter: {item['twitter_mentions']} mentions")
            print(f"   Telegram: {item['telegram_mentions']} mentions")
            print(f"   First seen: {item['first_seen']}")
            
            # Show sample tweets
            if item['twitter_details']:
                print(f"   Sample tweet: {item['twitter_details'][0]['url']}")
            
            print()
        
        # Log to file
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_scanned': len(timeline),
            'high_confidence_count': len(scored_contracts),
            'signals': scored_contracts,
        }
        
        with CONFLUENCE_LOG.open('a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        print(f"✅ Logged to {CONFLUENCE_LOG}")
    
    else:
        print(f"\n✅ No high-confidence signals this scan")
        print(f"   (Minimum score: {MIN_CONFLUENCE_SCORE})")
        print(f"   (Contracts scanned: {len(timeline)})")


if __name__ == '__main__':
    find_high_confidence_signals()
