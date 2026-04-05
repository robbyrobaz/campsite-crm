#!/usr/bin/env python3
"""
Token Outcome Tracker
Checks back on discovered tokens at intervals to track outcomes
Critical for evaluating scoring system effectiveness
"""

import json
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional

# Paths
BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / 'logs'

SCORED_LOG = LOGS_DIR / 'scored_tokens.jsonl'
TRACKING_LOG = LOGS_DIR / 'token_tracking.jsonl'
OUTCOMES_LOG = LOGS_DIR / 'token_outcomes.jsonl'

# API
DEX_TOKEN_API = "https://api.dexscreener.com/latest/dex/tokens/{address}"

# Tracking intervals (minutes after discovery)
CHECK_INTERVALS = [5, 30, 60, 360, 1440]  # 5min, 30min, 1hr, 6hr, 24hr


def load_tokens_to_track() -> list:
    """Load tokens that need outcome tracking"""
    if not SCORED_LOG.exists():
        return []
    
    tokens = []
    tracked_contracts = set()
    
    # Load already tracked
    if TRACKING_LOG.exists():
        with TRACKING_LOG.open('r') as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                tracked_contracts.add(data['contract'])
    
    # Load scored tokens
    with SCORED_LOG.open('r') as f:
        for line in f:
            if not line.strip():
                continue
            
            token = json.loads(line)
            contract = token['contract']
            
            # Skip if already being tracked
            if contract in tracked_contracts:
                continue
            
            # Add to tracking
            tokens.append({
                'contract': contract,
                'symbol': token['symbol'],
                'name': token['name'],
                'initial_score': token['score'],
                'discovered_at': token['scored_timestamp'],
                'created_at': token['created_timestamp'],
                'twitter': token.get('twitter'),
                'telegram': token.get('telegram'),
                'initial_liquidity_usd': token['details'].get('liquidity_usd', 0),
            })
            
            tracked_contracts.add(contract)
    
    return tokens


def get_token_state(contract: str) -> Optional[Dict]:
    """Get current state from Dexscreener"""
    try:
        url = DEX_TOKEN_API.format(address=contract)
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            pairs = data.get('pairs', [])
            if pairs:
                pair = pairs[0]
                
                return {
                    'price_usd': float(pair.get('priceUsd', 0)),
                    'market_cap': float(pair.get('marketCap', 0)),
                    'fdv': float(pair.get('fdv', 0)),
                    'liquidity_usd': float(pair.get('liquidity', {}).get('usd', 0)),
                    'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
                    'volume_1h': float(pair.get('volume', {}).get('h1', 0)),
                    'price_change_24h': float(pair.get('priceChange', {}).get('h24', 0)),
                    'price_change_1h': float(pair.get('priceChange', {}).get('h1', 0)),
                    'txns_24h_buys': pair.get('txns', {}).get('h24', {}).get('buys', 0),
                    'txns_24h_sells': pair.get('txns', {}).get('h24', {}).get('sells', 0),
                }
        
        return None
    
    except Exception as e:
        return None


def calculate_age_minutes(created_at_ms: int) -> float:
    """Calculate age in minutes"""
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    return (now_ms - created_at_ms) / 60000


def determine_outcome(token: Dict, snapshots: list) -> str:
    """Determine final outcome of a token"""
    
    if not snapshots:
        return 'NO_DATA'
    
    # Get peak and current values
    initial_liq = token['initial_liquidity_usd']
    peak_mc = max([s.get('market_cap', 0) for s in snapshots])
    current_mc = snapshots[-1].get('market_cap', 0)
    current_liq = snapshots[-1].get('liquidity_usd', 0)
    
    # Check if rugged (liquidity pulled or way down)
    if current_liq < initial_liq * 0.1:  # Lost 90%+ liquidity
        return 'RUGGED'
    
    # Check price action from initial to peak
    if peak_mc > initial_liq * 10:  # 10x+ market cap
        return 'MOONED'
    elif peak_mc > initial_liq * 3:  # 3-10x
        return 'WINNER'
    elif peak_mc > initial_liq * 1.5:  # 1.5-3x
        return 'SMALL_WIN'
    elif current_mc < initial_liq * 0.3:  # Down 70%+
        return 'DUMPED'
    else:
        return 'FLAT'


def track_cycle():
    """One tracking cycle"""
    
    print(f"\n{'='*60}")
    print(f"📊 OUTCOME TRACKER - {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    print(f"{'='*60}")
    
    # Load tokens to track
    new_tokens = load_tokens_to_track()
    print(f"📝 {len(new_tokens)} new tokens to track")
    
    # Start tracking new tokens
    for token in new_tokens:
        tracking_entry = {
            **token,
            'tracking_started': datetime.now(timezone.utc).isoformat(),
            'snapshots': [],
            'status': 'TRACKING',
        }
        
        # Log to tracking file
        with TRACKING_LOG.open('a') as f:
            f.write(json.dumps(tracking_entry) + '\n')
        
        print(f"  📍 Started tracking: {token['symbol']} (Score: {token['initial_score']})")
    
    # Check tokens that need updates
    if not TRACKING_LOG.exists():
        print("No tokens being tracked yet")
        return
    
    # Load all tracking entries
    tracking_data = []
    with TRACKING_LOG.open('r') as f:
        for line in f:
            if line.strip():
                tracking_data.append(json.loads(line))
    
    # Group by contract (latest entry per contract)
    latest_tracking = {}
    for entry in tracking_data:
        contract = entry['contract']
        latest_tracking[contract] = entry
    
    print(f"\n🔍 Checking {len(latest_tracking)} tracked tokens...")
    
    updates = 0
    completed = 0
    
    for contract, token in latest_tracking.items():
        # Skip if already completed
        if token.get('status') == 'COMPLETED':
            continue
        
        # Calculate age
        created_at = token['created_at']
        age_min = calculate_age_minutes(created_at)
        
        # Get existing snapshots
        snapshots = token.get('snapshots', [])
        snapshot_ages = [s['age_minutes'] for s in snapshots]
        
        # Check which intervals need snapshots
        for interval in CHECK_INTERVALS:
            # Skip if we already have a snapshot near this interval
            if any(abs(sa - interval) < 2 for sa in snapshot_ages):
                continue
            
            # Skip if token isn't old enough yet
            if age_min < interval:
                continue
            
            # Get current state
            print(f"  📸 {token['symbol']}: Taking {interval}min snapshot...")
            state = get_token_state(contract)
            
            if state:
                snapshot = {
                    'age_minutes': round(age_min, 1),
                    'interval': interval,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    **state
                }
                
                snapshots.append(snapshot)
                updates += 1
                
                # Show summary
                mc_change = ((state['market_cap'] / token['initial_liquidity_usd']) - 1) * 100 if token['initial_liquidity_usd'] > 0 else 0
                print(f"    MC: ${state['market_cap']:.0f} ({mc_change:+.0f}%), Liq: ${state['liquidity_usd']:.0f}")
            else:
                print(f"    ⚠️  No data available")
            
            time.sleep(0.5)  # Rate limit
        
        # Check if complete (have all intervals or >24hr old)
        has_all_intervals = all(
            any(abs(s['age_minutes'] - interval) < 2 for s in snapshots)
            for interval in CHECK_INTERVALS
        )
        
        is_old_enough = age_min > max(CHECK_INTERVALS) + 60  # 1hr past last interval
        
        if has_all_intervals or is_old_enough:
            # Determine outcome
            outcome = determine_outcome(token, snapshots)
            
            outcome_entry = {
                'contract': contract,
                'symbol': token['symbol'],
                'name': token['name'],
                'initial_score': token['initial_score'],
                'created_at': created_at,
                'discovered_at': token['discovered_at'],
                'tracking_completed': datetime.now(timezone.utc).isoformat(),
                'age_at_completion': round(age_min, 1),
                'snapshots': snapshots,
                'outcome': outcome,
                'peak_market_cap': max([s.get('market_cap', 0) for s in snapshots]) if snapshots else 0,
                'final_market_cap': snapshots[-1].get('market_cap', 0) if snapshots else 0,
                'final_liquidity': snapshots[-1].get('liquidity_usd', 0) if snapshots else 0,
            }
            
            # Log outcome
            with OUTCOMES_LOG.open('a') as f:
                f.write(json.dumps(outcome_entry) + '\n')
            
            completed += 1
            print(f"  ✅ {token['symbol']}: {outcome} (Age: {age_min:.0f}min, Snapshots: {len(snapshots)})")
            
            # Update tracking status
            token['status'] = 'COMPLETED'
            token['snapshots'] = snapshots
        
        # Update tracking log
        if snapshots != token.get('snapshots', []):
            token['snapshots'] = snapshots
            with TRACKING_LOG.open('a') as f:
                f.write(json.dumps(token) + '\n')
    
    print(f"\n{'='*60}")
    print(f"📊 SUMMARY: {updates} snapshots taken, {completed} tokens completed")
    print(f"{'='*60}")


def main():
    """Main loop"""
    
    print("""
╔══════════════════════════════════════════════════════════════╗
║             📊 TOKEN OUTCOME TRACKER 📊                      ║
║                                                              ║
║   Tracks tokens over time to measure scoring effectiveness  ║
║   Intervals: 5min, 30min, 1hr, 6hr, 24hr                   ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    print(f"📁 Logs: {LOGS_DIR}")
    print(f"🔄 Checking every 5 minutes...\n")
    
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            
            try:
                track_cycle()
            except Exception as e:
                print(f"\n❌ Error in tracking cycle: {e}")
                import traceback
                traceback.print_exc()
            
            print(f"\n⏳ Waiting 5 minutes... (Cycle #{cycle_count})")
            time.sleep(300)  # 5 minutes
    
    except KeyboardInterrupt:
        print(f"\n\n🛑 Tracker stopped. Total cycles: {cycle_count}")


if __name__ == '__main__':
    main()
