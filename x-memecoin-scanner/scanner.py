#!/usr/bin/env python3
"""
X/Twitter Memecoin Scanner with twikit
Scans for early memecoin mentions, extracts contracts, tracks confluence
"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict

from twikit import Client
from dotenv import load_dotenv

# Load environment
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

# Credentials
USERNAME = os.getenv('X_USERNAME')
EMAIL = os.getenv('X_EMAIL')
PASSWORD = os.getenv('X_PASSWORD')

# Config
MAX_TWEETS_PER_QUERY = int(os.getenv('MAX_TWEETS_PER_QUERY', '50'))
COOKIES_FILE = BASE_DIR / 'cookies.json'

# Search queries (designed to catch early launches)
SEARCH_QUERIES = [
    'just launched Solana CA:',
    'new token contract 🚀',
    'fair launch Solana',
    'CA: Solana gem',
    'pump.fun new',
    'raydium just added',
]

# Output
SIGNALS_LOG = BASE_DIR / 'logs' / 'x_signals.jsonl'
CONFLUENCE_LOG = BASE_DIR / 'logs' / 'confluence.jsonl'

# Ensure directories exist
SIGNALS_LOG.parent.mkdir(parents=True, exist_ok=True)


def extract_contract_addresses(text: str) -> List[str]:
    """Extract Solana contract addresses (base58, 32-44 chars)"""
    pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    matches = re.findall(pattern, text)
    
    # Filter out common false positives
    filtered = []
    for match in matches:
        if match.lower() not in ['sol', 'usdc', 'usdt', 'wsol']:
            filtered.append(match)
    
    return filtered


def calculate_hype_score(tweet) -> int:
    """Calculate hype score based on engagement and keywords"""
    text = tweet.text.lower()
    
    # Engagement metrics
    score = 0
    score += min(tweet.favorite_count or 0, 50) // 10  # Up to 5 points for likes
    score += min(tweet.retweet_count or 0, 20) // 5    # Up to 4 points for RTs
    score += min(tweet.reply_count or 0, 10) // 2      # Up to 5 points for replies
    
    # Hype keywords
    hype_words = ['🚀', 'moon', '100x', 'gem', 'ape', 'send it', 'x100', 'moonshot']
    for word in hype_words:
        if word in text:
            score += 2
    
    # Bonus for urgency
    if any(w in text for w in ['just launched', 'new', 'early', 'first']):
        score += 3
    
    return score


async def login_or_load_cookies(client: Client) -> bool:
    """Login with credentials or load existing cookies"""
    
    if COOKIES_FILE.exists():
        try:
            client.load_cookies(str(COOKIES_FILE))
            print(f"✅ Loaded cookies from {COOKIES_FILE}")
            return True
        except Exception as e:
            print(f"⚠️  Failed to load cookies: {e}")
            COOKIES_FILE.unlink(missing_ok=True)
    
    # Fresh login
    if not all([USERNAME, EMAIL, PASSWORD]):
        print("❌ Missing credentials in .env")
        return False
    
    print("Logging in to X...")
    try:
        await client.login(
            auth_info_1=USERNAME,
            auth_info_2=EMAIL,
            password=PASSWORD
        )
        client.save_cookies(str(COOKIES_FILE))
        print("✅ Logged in and saved cookies")
        return True
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False


async def search_tweets(client: Client, query: str) -> List[Dict]:
    """Search tweets and extract signals"""
    
    try:
        tweets = await client.search_tweet(
            query, 
            product='Latest',  # Most recent first
            count=MAX_TWEETS_PER_QUERY
        )
        
        signals = []
        for tweet in tweets:
            contracts = extract_contract_addresses(tweet.text)
            if not contracts:
                continue
            
            # Extract tweet data
            signal = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'tweet_id': tweet.id,
                'tweet_created_at': str(tweet.created_at),
                'user': tweet.user.screen_name,
                'user_followers': tweet.user.followers_count,
                'text': tweet.text,
                'contracts': contracts,
                'likes': tweet.favorite_count or 0,
                'retweets': tweet.retweet_count or 0,
                'replies': tweet.reply_count or 0,
                'hype_score': calculate_hype_score(tweet),
                'query': query,
                'url': f"https://x.com/{tweet.user.screen_name}/status/{tweet.id}"
            }
            signals.append(signal)
        
        return signals
    
    except Exception as e:
        print(f"⚠️  Search failed for '{query}': {e}")
        return []


async def scan_all_queries(client: Client) -> List[Dict]:
    """Run all search queries and collect signals"""
    
    all_signals = []
    
    for query in SEARCH_QUERIES:
        print(f"Searching: '{query}'...")
        signals = await search_tweets(client, query)
        all_signals.extend(signals)
        print(f"  Found {len(signals)} signals")
        
        # Rate limiting courtesy pause
        await asyncio.sleep(2)
    
    return all_signals


def calculate_confluence(signals: List[Dict]) -> Dict[str, Dict]:
    """Calculate confluence for each contract (mentions across multiple sources)"""
    
    contract_mentions = defaultdict(lambda: {
        'count': 0,
        'sources': set(),
        'queries': set(),
        'users': set(),
        'total_hype': 0,
        'first_seen': None,
        'tweets': []
    })
    
    for signal in signals:
        for contract in signal['contracts']:
            data = contract_mentions[contract]
            data['count'] += 1
            data['sources'].add('twitter')
            data['queries'].add(signal['query'])
            data['users'].add(signal['user'])
            data['total_hype'] += signal['hype_score']
            
            if data['first_seen'] is None:
                data['first_seen'] = signal['timestamp']
            
            data['tweets'].append({
                'url': signal['url'],
                'user': signal['user'],
                'hype': signal['hype_score']
            })
    
    # Convert sets to lists for JSON serialization
    result = {}
    for contract, data in contract_mentions.items():
        result[contract] = {
            'count': data['count'],
            'sources': list(data['sources']),
            'queries': list(data['queries']),
            'users': list(data['users']),
            'total_hype': data['total_hype'],
            'first_seen': data['first_seen'],
            'tweets': data['tweets']
        }
    
    return result


async def main():
    """Main scanner loop"""
    
    print(f"=== X Memecoin Scanner ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}\n")
    
    # Initialize client
    client = Client('en-US')
    
    # Login
    if not await login_or_load_cookies(client):
        return
    
    # Scan all queries
    signals = await scan_all_queries(client)
    
    # Log all signals
    print(f"\n📊 Total signals found: {len(signals)}")
    with SIGNALS_LOG.open('a') as f:
        for signal in signals:
            f.write(json.dumps(signal) + '\n')
    
    # Calculate confluence
    if signals:
        confluence = calculate_confluence(signals)
        
        # Find high-confluence contracts (mentioned by 2+ queries or users)
        strong_signals = {
            contract: data 
            for contract, data in confluence.items()
            if len(data['queries']) >= 2 or len(data['users']) >= 2
        }
        
        if strong_signals:
            print(f"\n🎯 STRONG CONFLUENCE ({len(strong_signals)} contracts):")
            for contract, data in sorted(strong_signals.items(), key=lambda x: x[1]['total_hype'], reverse=True):
                print(f"  {contract}")
                print(f"    Mentions: {data['count']} | Queries: {len(data['queries'])} | Users: {len(data['users'])}")
                print(f"    Total Hype: {data['total_hype']}")
                print()
            
            # Log confluence
            confluence_entry = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'total_scanned': len(signals),
                'high_confluence': strong_signals
            }
            with CONFLUENCE_LOG.open('a') as f:
                f.write(json.dumps(confluence_entry) + '\n')
        else:
            print(f"\n✅ No high-confluence signals this scan")
    
    print(f"\n✅ Scan complete")


if __name__ == '__main__':
    asyncio.run(main())
