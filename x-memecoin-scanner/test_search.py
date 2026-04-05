#!/usr/bin/env python3
"""
Test X/Twitter scanning with twikit
Quick verification that auth + search works
"""

import asyncio
import json
import re
from twikit import Client
from pathlib import Path

# Credentials (you'll need a normal X account - not developer account!)
# Add these to .env later
USERNAME = input("X username: ")
EMAIL = input("X email: ")
PASSWORD = input("X password: ")

async def test_search():
    """Test basic search functionality"""
    
    client = Client('en-US')
    
    print("Logging in...")
    await client.login(
        auth_info_1=USERNAME,
        auth_info_2=EMAIL,
        password=PASSWORD
    )
    
    # Save cookies for future use (no re-login needed)
    cookies_path = Path('cookies.json')
    client.save_cookies(str(cookies_path))
    print(f"✅ Logged in! Cookies saved to {cookies_path}")
    
    # Test search for memecoin keywords
    print("\nSearching for 'just launched Solana CA:'...")
    tweets = await client.search_tweet('just launched Solana CA:', product='Latest', count=10)
    
    print(f"\nFound {len(tweets)} tweets:\n")
    
    for i, tweet in enumerate(tweets, 1):
        # Extract contract addresses (Solana base58, 32-44 chars)
        text = tweet.text
        contract_pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
        contracts = re.findall(contract_pattern, text)
        
        print(f"{i}. @{tweet.user.screen_name} ({tweet.created_at})")
        print(f"   Text: {text[:100]}...")
        if contracts:
            print(f"   🎯 Contract: {contracts[0]}")
        print()

if __name__ == '__main__':
    asyncio.run(test_search())
