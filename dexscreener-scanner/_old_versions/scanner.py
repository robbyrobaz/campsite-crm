#!/usr/bin/env python3
"""
Dexscreener New Token Scanner
Monitors https://dexscreener.com/solana for new listings
FASTEST source - tokens appear here BEFORE Telegram/X
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

# Output
BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SIGNALS_LOG = LOGS_DIR / 'new_tokens.jsonl'
SEEN_CONTRACTS = BASE_DIR / 'seen_contracts.txt'

# Dexscreener URLs
DEXSCREENER_SOLANA = "https://dexscreener.com/solana"
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/tokens/{contract}"

# Filters
MIN_LIQUIDITY_USD = 1000  # Minimum $1k liquidity (filters rug pulls)
MAX_AGE_HOURS = 24        # Only tokens <24h old


def load_seen_contracts() -> set:
    """Load already-seen contracts"""
    if not SEEN_CONTRACTS.exists():
        return set()
    return set(SEEN_CONTRACTS.read_text().strip().split('\n'))


def save_contract(contract: str):
    """Mark contract as seen"""
    with SEEN_CONTRACTS.open('a') as f:
        f.write(f"{contract}\n")


def get_token_info(contract: str) -> Optional[Dict]:
    """Get detailed token info from Dexscreener API"""
    try:
        url = DEXSCREENER_API.format(contract=contract)
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        if not data.get('pairs'):
            return None
        
        # Get the main pair (usually first one)
        pair = data['pairs'][0]
        
        return {
            'contract': contract,
            'name': pair.get('baseToken', {}).get('name', ''),
            'symbol': pair.get('baseToken', {}).get('symbol', ''),
            'price_usd': float(pair.get('priceUsd', 0)),
            'liquidity_usd': float(pair.get('liquidity', {}).get('usd', 0)),
            'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
            'price_change_5m': float(pair.get('priceChange', {}).get('m5', 0)),
            'price_change_1h': float(pair.get('priceChange', {}).get('h1', 0)),
            'price_change_24h': float(pair.get('priceChange', {}).get('h24', 0)),
            'txns_5m': pair.get('txns', {}).get('m5', {}),
            'txns_1h': pair.get('txns', {}).get('h1', {}),
            'txns_24h': pair.get('txns', {}).get('h24', {}),
            'pair_created_at': pair.get('pairCreatedAt', 0),
            'dex': pair.get('dexId', ''),
            'pair_address': pair.get('pairAddress', ''),
            'url': pair.get('url', ''),
            'socials': {
                'website': pair.get('info', {}).get('websites', []),
                'twitter': pair.get('info', {}).get('socials', []),
            }
        }
    
    except Exception as e:
        print(f"⚠️  Error fetching {contract}: {e}")
        return None


def calculate_age_hours(pair_created_at: int) -> float:
    """Calculate token age in hours"""
    if not pair_created_at:
        return 999  # Unknown age = skip
    
    now = datetime.now(timezone.utc).timestamp()
    age_seconds = now - (pair_created_at / 1000)  # API returns milliseconds
    return age_seconds / 3600


def calculate_score(token: Dict) -> float:
    """Calculate token quality score"""
    score = 0.0
    
    # Liquidity score (higher = safer)
    if token['liquidity_usd'] >= 10000:
        score += 10
    elif token['liquidity_usd'] >= 5000:
        score += 7
    elif token['liquidity_usd'] >= 1000:
        score += 4
    
    # Volume score
    if token['volume_24h'] >= 50000:
        score += 8
    elif token['volume_24h'] >= 10000:
        score += 5
    elif token['volume_24h'] >= 1000:
        score += 2
    
    # Price movement (momentum)
    if token['price_change_1h'] > 20:
        score += 10  # Strong pump
    elif token['price_change_1h'] > 10:
        score += 6
    elif token['price_change_1h'] > 0:
        score += 2
    
    # Transaction count (activity)
    txns_1h = token.get('txns_1h', {})
    total_txns_1h = txns_1h.get('buys', 0) + txns_1h.get('sells', 0)
    if total_txns_1h >= 100:
        score += 8
    elif total_txns_1h >= 50:
        score += 5
    elif total_txns_1h >= 10:
        score += 2
    
    # Age bonus (newer = earlier entry)
    age_hours = calculate_age_hours(token['pair_created_at'])
    if age_hours < 1:
        score += 15  # VERY new
    elif age_hours < 6:
        score += 10
    elif age_hours < 24:
        score += 5
    
    # Socials bonus (has website/twitter = more legit)
    if token['socials']['website']:
        score += 3
    if token['socials']['twitter']:
        score += 3
    
    return score


def scan_new_tokens() -> List[Dict]:
    """Scan Dexscreener for new Solana tokens"""
    
    print(f"Scanning Dexscreener...")
    
    try:
        # Get the main Solana page
        response = requests.get(DEXSCREENER_SOLANA, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract token addresses from the page
        # Dexscreener embeds them in links and data attributes
        contract_pattern = r'[1-9A-HJ-NP-Za-km-z]{32,44}'
        contracts = set(re.findall(contract_pattern, response.text))
        
        # Filter to valid Solana addresses
        contracts = {c for c in contracts if len(c) >= 32 and c not in ['sol', 'usdc', 'usdt']}
        
        print(f"  Found {len(contracts)} potential tokens")
        
        # Load seen contracts
        seen = load_seen_contracts()
        new_contracts = [c for c in contracts if c not in seen]
        
        print(f"  {len(new_contracts)} new (unseen)")
        
        if not new_contracts:
            return []
        
        # Get detailed info for new tokens
        new_tokens = []
        for contract in new_contracts[:50]:  # Limit to 50 per scan
            token_info = get_token_info(contract)
            
            if not token_info:
                print(f"    ⚠️  {contract[:10]}... - No API data")
                continue
            
            # Apply filters
            age_hours = calculate_age_hours(token_info['pair_created_at'])
            
            if age_hours > MAX_AGE_HOURS:
                print(f"    ⏭️  {token_info.get('symbol', 'UNK')} - Too old ({age_hours:.1f}h)")
                continue  # Too old
            
            if token_info['liquidity_usd'] < MIN_LIQUIDITY_USD:
                print(f"    ⏭️  {token_info.get('symbol', 'UNK')} - Low liquidity (${token_info['liquidity_usd']:.0f})")
                continue  # Not enough liquidity (likely rug)
            
            # Calculate score
            token_info['score'] = calculate_score(token_info)
            token_info['age_hours'] = age_hours
            token_info['timestamp'] = datetime.now(timezone.utc).isoformat()
            
            new_tokens.append(token_info)
            save_contract(contract)
            
            # Rate limit
            time.sleep(0.5)
        
        return new_tokens
    
    except Exception as e:
        print(f"❌ Scan failed: {e}")
        return []


def main():
    """Main scanner"""
    
    print(f"=== Dexscreener New Token Scanner ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}\n")
    
    # Scan for new tokens
    tokens = scan_new_tokens()
    
    if not tokens:
        print("\n✅ No new tokens found")
        return
    
    # Sort by score
    tokens.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n🎯 NEW TOKENS ({len(tokens)}):\n")
    
    for i, token in enumerate(tokens[:10], 1):  # Top 10
        print(f"{i}. {token['symbol']} ({token['name']})")
        print(f"   Contract: {token['contract'][:20]}...")
        print(f"   Score: {token['score']:.1f}")
        print(f"   Age: {token['age_hours']:.1f}h")
        print(f"   Liquidity: ${token['liquidity_usd']:,.0f}")
        print(f"   Volume 24h: ${token['volume_24h']:,.0f}")
        print(f"   Price Change 1h: {token['price_change_1h']:+.1f}%")
        print(f"   URL: {token['url']}")
        print()
    
    # Log all tokens
    with SIGNALS_LOG.open('a') as f:
        for token in tokens:
            f.write(json.dumps(token) + '\n')
    
    print(f"✅ Logged {len(tokens)} tokens to {SIGNALS_LOG}")


if __name__ == '__main__':
    main()
