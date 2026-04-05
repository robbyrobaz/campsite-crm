#!/usr/bin/env python3
"""
Dexscreener New Token Scanner v2
Uses Dexscreener API to find newest Solana pairs
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

import requests

# Output
BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SIGNALS_LOG = LOGS_DIR / 'new_tokens.jsonl'
SEEN_CONTRACTS = BASE_DIR / 'seen_contracts.txt'

# Dexscreener API endpoints
# Note: Dexscreener doesn't have a public "new pairs" endpoint
# But we can use their search/profile APIs
DEXSCREENER_LATEST = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_BOOSTED = "https://api.dexscreener.com/token-boosts/latest/v1"
DEXSCREENER_PAIRS = "https://api.dexscreener.com/latest/dex/pairs/solana/{pair_address}"
DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search?q={query}"

# Filters
MIN_LIQUIDITY_USD = 100    # Very low threshold for testing (new tokens start small)
MAX_AGE_HOURS = 168        # Tokens <1 week old (7 days)


def load_seen_contracts() -> set:
    """Load already-seen contracts"""
    if not SEEN_CONTRACTS.exists():
        return set()
    return set(SEEN_CONTRACTS.read_text().strip().split('\n'))


def save_contract(contract: str):
    """Mark contract as seen"""
    with SEEN_CONTRACTS.open('a') as f:
        f.write(f"{contract}\n")


def get_latest_profiles() -> List[Dict]:
    """Get latest token profiles from Dexscreener"""
    try:
        response = requests.get(DEXSCREENER_LATEST, timeout=10)
        if response.status_code != 200:
            print(f"  ⚠️  Latest profiles API returned {response.status_code}")
            return []
        
        data = response.json()
        return data if isinstance(data, list) else []
    
    except Exception as e:
        print(f"  ⚠️  Error fetching latest profiles: {e}")
        return []


def get_boosted_tokens() -> List[Dict]:
    """Get boosted/promoted tokens (often new listings)"""
    try:
        response = requests.get(DEXSCREENER_BOOSTED, timeout=10)
        if response.status_code != 200:
            return []
        
        data = response.json()
        return data if isinstance(data, list) else []
    
    except Exception as e:
        return []


def search_new_solana_tokens() -> List[Dict]:
    """Search for recently created Solana tokens"""
    keywords = ['sol', 'solana', 'pump', 'new', 'launch']
    all_results = []
    
    for keyword in keywords:
        try:
            url = DEXSCREENER_SEARCH.format(query=keyword)
            response = requests.get(url, timeout=10)
            
            if response.status_code != 200:
                continue
            
            data = response.json()
            pairs = data.get('pairs', [])
            
            # Filter for Solana only
            solana_pairs = [p for p in pairs if p.get('chainId') == 'solana']
            all_results.extend(solana_pairs)
            
            time.sleep(1)  # Rate limit
        
        except Exception as e:
            continue
    
    return all_results


def calculate_age_hours(pair_created_at: int) -> float:
    """Calculate token age in hours"""
    if not pair_created_at:
        return 999
    
    now = datetime.now(timezone.utc).timestamp()
    age_seconds = now - (pair_created_at / 1000)
    return age_seconds / 3600


def calculate_score(pair: Dict) -> float:
    """Calculate token quality score"""
    score = 0.0
    
    liq = float(pair.get('liquidity', {}).get('usd', 0))
    vol_24h = float(pair.get('volume', {}).get('h24', 0))
    price_change_1h = float(pair.get('priceChange', {}).get('h1', 0))
    
    # Liquidity
    if liq >= 10000:
        score += 10
    elif liq >= 5000:
        score += 7
    elif liq >= 1000:
        score += 4
    elif liq >= 500:
        score += 2
    
    # Volume
    if vol_24h >= 50000:
        score += 8
    elif vol_24h >= 10000:
        score += 5
    elif vol_24h >= 1000:
        score += 2
    
    # Price movement
    if price_change_1h > 20:
        score += 10
    elif price_change_1h > 10:
        score += 6
    elif price_change_1h > 0:
        score += 2
    
    # Transaction activity
    txns = pair.get('txns', {}).get('h1', {})
    total_txns = txns.get('buys', 0) + txns.get('sells', 0)
    if total_txns >= 100:
        score += 8
    elif total_txns >= 50:
        score += 5
    elif total_txns >= 10:
        score += 2
    
    # Age
    age = calculate_age_hours(pair.get('pairCreatedAt', 0))
    if age < 1:
        score += 15
    elif age < 6:
        score += 10
    elif age < 24:
        score += 5
    elif age < 48:
        score += 2
    
    return score


def process_pair(pair: Dict) -> Optional[Dict]:
    """Process a pair and extract relevant data"""
    try:
        contract = pair.get('baseToken', {}).get('address')
        if not contract:
            return None
        
        age_hours = calculate_age_hours(pair.get('pairCreatedAt', 0))
        liq = float(pair.get('liquidity', {}).get('usd', 0))
        
        # Apply filters
        if age_hours > MAX_AGE_HOURS:
            return None
        
        if liq < MIN_LIQUIDITY_USD:
            return None
        
        token = {
            'contract': contract,
            'name': pair.get('baseToken', {}).get('name', ''),
            'symbol': pair.get('baseToken', {}).get('symbol', ''),
            'price_usd': float(pair.get('priceUsd', 0)),
            'liquidity_usd': liq,
            'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
            'price_change_5m': float(pair.get('priceChange', {}).get('m5', 0)),
            'price_change_1h': float(pair.get('priceChange', {}).get('h1', 0)),
            'price_change_24h': float(pair.get('priceChange', {}).get('h24', 0)),
            'txns_1h_buys': pair.get('txns', {}).get('h1', {}).get('buys', 0),
            'txns_1h_sells': pair.get('txns', {}).get('h1', {}).get('sells', 0),
            'age_hours': age_hours,
            'dex': pair.get('dexId', ''),
            'pair_address': pair.get('pairAddress', ''),
            'url': pair.get('url', ''),
            'fdv': pair.get('fdv', 0),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        
        token['score'] = calculate_score(pair)
        
        return token
    
    except Exception as e:
        return None


def main():
    """Main scanner"""
    
    print(f"=== Dexscreener New Token Scanner v2 ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}\n")
    
    # Get pairs from multiple sources
    print("Fetching latest profiles...")
    profiles = get_latest_profiles()
    print(f"  Found {len(profiles)} profiles")
    
    print("Fetching boosted tokens...")
    boosted = get_boosted_tokens()
    print(f"  Found {len(boosted)} boosted")
    
    print("Searching for new Solana tokens...")
    search_results = search_new_solana_tokens()
    print(f"  Found {len(search_results)} from search")
    
    # Combine and deduplicate
    all_pairs = search_results
    seen_addresses = set()
    
    # Process pairs
    new_tokens = []
    seen_contracts = load_seen_contracts()
    
    for pair in all_pairs:
        contract = pair.get('baseToken', {}).get('address')
        if not contract:
            continue
        
        if contract in seen_addresses or contract in seen_contracts:
            continue
        
        seen_addresses.add(contract)
        
        token = process_pair(pair)
        if token:
            new_tokens.append(token)
            save_contract(contract)
        else:
            # Debug: why was it filtered?
            age = calculate_age_hours(pair.get('pairCreatedAt', 0))
            liq = float(pair.get('liquidity', {}).get('usd', 0))
            symbol = pair.get('baseToken', {}).get('symbol', 'UNK')
            print(f"  ⏭️  {symbol}: age={age:.1f}h (max={MAX_AGE_HOURS}), liq=${liq:.0f} (min=${MIN_LIQUIDITY_USD})")
    
    if not new_tokens:
        print("\n✅ No new tokens matching criteria")
        return
    
    # Sort by score
    new_tokens.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n🎯 NEW TOKENS ({len(new_tokens)}):\n")
    
    for i, token in enumerate(new_tokens[:15], 1):
        print(f"{i}. {token['symbol']} ({token['name']})")
        print(f"   Score: {token['score']:.1f} | Age: {token['age_hours']:.1f}h")
        print(f"   Liquidity: ${token['liquidity_usd']:,.0f} | Vol 24h: ${token['volume_24h']:,.0f}")
        print(f"   Price Δ 1h: {token['price_change_1h']:+.1f}% | Txns 1h: {token['txns_1h_buys']}B/{token['txns_1h_sells']}S")
        print(f"   {token['url']}")
        print()
    
    # Log
    with SIGNALS_LOG.open('a') as f:
        for token in new_tokens:
            f.write(json.dumps(token) + '\n')
    
    print(f"✅ Logged {len(new_tokens)} tokens to {SIGNALS_LOG}")


if __name__ == '__main__':
    main()
