#!/usr/bin/env python3
"""
Dexscreener + Pump.fun Real-Time Scanner
Gets NEWEST tokens from multiple sources
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

SIGNALS_LOG = LOGS_DIR / 'live_tokens.jsonl'
SEEN_FILE = BASE_DIR / 'seen_tokens.txt'

# APIs
DEX_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEX_BOOSTED = "https://api.dexscreener.com/token-boosts/latest/v1"
DEX_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/{address}"

# Filters
MAX_AGE_MINUTES = 60      # Only tokens <60 min old
MIN_LIQUIDITY = 500       # Minimum $500 liquidity
MIN_VOLUME_1H = 100       # Minimum $100 volume in 1h


def load_seen() -> set:
    """Load seen tokens"""
    if not SEEN_FILE.exists():
        return set()
    return set(SEEN_FILE.read_text().strip().split('\n'))


def mark_seen(address: str):
    """Mark token as seen"""
    with SEEN_FILE.open('a') as f:
        f.write(f"{address}\n")


def get_token_addresses() -> List[str]:
    """Get latest token addresses from Dexscreener"""
    addresses = set()
    
    # Get from profiles
    try:
        resp = requests.get(DEX_PROFILES, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for item in data:
                if item.get('chainId') == 'solana':
                    addr = item.get('tokenAddress')
                    if addr:
                        addresses.add(addr)
            print(f"  Profiles: {len(addresses)} Solana tokens")
    except Exception as e:
        print(f"  ⚠️  Profiles error: {e}")
    
    # Get from boosted
    try:
        resp = requests.get(DEX_BOOSTED, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for item in data:
                if item.get('chainId') == 'solana':
                    addr = item.get('tokenAddress')
                    if addr:
                        addresses.add(addr)
            print(f"  Boosted: {len(addresses)} total Solana tokens")
    except Exception as e:
        print(f"  ⚠️  Boosted error: {e}")
    
    return list(addresses)


def get_pair_data(address: str) -> Optional[Dict]:
    """Get full pair data for a token"""
    try:
        url = DEX_TOKEN.format(address=address)
        resp = requests.get(url, timeout=10)
        
        if resp.status_code != 200:
            return None
        
        data = resp.json()
        pairs = data.get('pairs', [])
        
        if not pairs:
            return None
        
        # Get the main pair (usually pump.fun or raydium)
        pair = pairs[0]
        
        return pair
    
    except Exception as e:
        return None


def calculate_age_minutes(created_at_ms: int) -> float:
    """Calculate age in minutes from millisecond timestamp"""
    if not created_at_ms:
        return 999999
    
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    age_ms = now_ms - created_at_ms
    return age_ms / 1000 / 60  # Convert to minutes


def calculate_score(pair: Dict, age_minutes: float) -> float:
    """Score a token"""
    score = 0.0
    
    # Get metrics
    liq = float(pair.get('liquidity', {}).get('usd', 0))
    vol_1h = float(pair.get('volume', {}).get('h1', 0))
    price_change_1h = float(pair.get('priceChange', {}).get('h1', 0))
    
    txns_1h = pair.get('txns', {}).get('h1', {})
    buys = txns_1h.get('buys', 0)
    sells = txns_1h.get('sells', 0)
    total_txns = buys + sells
    
    # Age score (NEWEST = highest score)
    if age_minutes < 5:
        score += 50  # BRAND NEW!
    elif age_minutes < 15:
        score += 30
    elif age_minutes < 30:
        score += 20
    elif age_minutes < 60:
        score += 10
    
    # Liquidity
    if liq >= 10000:
        score += 15
    elif liq >= 5000:
        score += 10
    elif liq >= 1000:
        score += 5
    elif liq >= 500:
        score += 2
    
    # Volume
    if vol_1h >= 10000:
        score += 15
    elif vol_1h >= 5000:
        score += 10
    elif vol_1h >= 1000:
        score += 5
    elif vol_1h >= 100:
        score += 2
    
    # Price action
    if price_change_1h > 50:
        score += 20  # PUMPING
    elif price_change_1h > 20:
        score += 10
    elif price_change_1h > 0:
        score += 3
    
    # Activity
    if total_txns >= 100:
        score += 10
    elif total_txns >= 50:
        score += 5
    elif total_txns >= 10:
        score += 2
    
    # Buy/sell ratio (more buys = good)
    if sells > 0:
        buy_ratio = buys / sells
        if buy_ratio > 2.0:
            score += 10
        elif buy_ratio > 1.5:
            score += 5
    
    return score


def scan():
    """Main scan"""
    
    print(f"=== Dexscreener Live Scanner ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}\n")
    
    # Get token addresses
    print("Fetching token addresses...")
    addresses = get_token_addresses()
    
    if not addresses:
        print("⚠️  No addresses found")
        return
    
    # Filter to unseen
    seen = load_seen()
    new_addresses = [a for a in addresses if a not in seen]
    
    print(f"  Total: {len(addresses)}")
    print(f"  New (unseen): {len(new_addresses)}\n")
    
    if not new_addresses:
        print("✅ No new tokens")
        return
    
    # Get pair data for each
    print("Fetching pair data...")
    new_tokens = []
    
    for i, address in enumerate(new_addresses[:30], 1):  # Limit to 30 to avoid rate limits
        print(f"  [{i}/{min(30, len(new_addresses))}] {address[:10]}...", end=' ')
        
        pair = get_pair_data(address)
        
        if not pair:
            print("❌ No pair data")
            continue
        
        # Calculate age
        created_at = pair.get('pairCreatedAt', 0)
        age_minutes = calculate_age_minutes(created_at)
        
        # Apply filters
        if age_minutes > MAX_AGE_MINUTES:
            print(f"⏭️  Too old ({age_minutes:.0f}m)")
            continue
        
        liq = float(pair.get('liquidity', {}).get('usd', 0))
        if liq < MIN_LIQUIDITY:
            print(f"⏭️  Low liq (${liq:.0f})")
            continue
        
        vol_1h = float(pair.get('volume', {}).get('h1', 0))
        if vol_1h < MIN_VOLUME_1H:
            print(f"⏭️  Low vol (${vol_1h:.0f})")
            continue
        
        # Build token object
        token = {
            'contract': address,
            'name': pair.get('baseToken', {}).get('name', ''),
            'symbol': pair.get('baseToken', {}).get('symbol', ''),
            'age_minutes': age_minutes,
            'price_usd': float(pair.get('priceUsd', 0)),
            'liquidity_usd': liq,
            'volume_1h': vol_1h,
            'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
            'price_change_5m': float(pair.get('priceChange', {}).get('m5', 0)),
            'price_change_1h': float(pair.get('priceChange', {}).get('h1', 0)),
            'txns_1h_buys': pair.get('txns', {}).get('h1', {}).get('buys', 0),
            'txns_1h_sells': pair.get('txns', {}).get('h1', {}).get('sells', 0),
            'dex': pair.get('dexId', ''),
            'pair_address': pair.get('pairAddress', ''),
            'url': pair.get('url', ''),
            'socials': pair.get('info', {}).get('socials', []),
            'websites': pair.get('info', {}).get('websites', []),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        
        token['score'] = calculate_score(pair, age_minutes)
        
        new_tokens.append(token)
        mark_seen(address)
        
        print(f"✅ Score: {token['score']:.0f}, Age: {age_minutes:.0f}m")
        
        time.sleep(0.3)  # Rate limit
    
    if not new_tokens:
        print("\n✅ No tokens passed filters")
        return
    
    # Sort by score
    new_tokens.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n🎯 NEW TOKENS ({len(new_tokens)}):\n")
    
    for i, t in enumerate(new_tokens[:10], 1):
        print(f"{i}. {t['symbol']} - {t['name']}")
        print(f"   Score: {t['score']:.0f} | Age: {t['age_minutes']:.0f}min | Dex: {t['dex']}")
        print(f"   Liq: ${t['liquidity_usd']:,.0f} | Vol 1h: ${t['volume_1h']:,.0f}")
        print(f"   Price Δ 1h: {t['price_change_1h']:+.1f}% | Txns: {t['txns_1h_buys']}B/{t['txns_1h_sells']}S")
        
        if t['socials']:
            twitter = [s['url'] for s in t['socials'] if s.get('type') == 'twitter']
            if twitter:
                print(f"   Twitter: {twitter[0]}")
        
        print(f"   {t['url']}")
        print()
    
    # Log all
    with SIGNALS_LOG.open('a') as f:
        for t in new_tokens:
            f.write(json.dumps(t) + '\n')
    
    print(f"✅ Logged {len(new_tokens)} tokens to {SIGNALS_LOG}")


if __name__ == '__main__':
    scan()
