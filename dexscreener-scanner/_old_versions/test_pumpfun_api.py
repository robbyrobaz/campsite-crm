#!/usr/bin/env python3
"""
Test various pump.fun API endpoints
"""

import requests
import json

# Try different endpoints
ENDPOINTS = [
    # Known public APIs
    ("Frontend API (coins latest)", "https://frontend-api.pump.fun/coins?offset=0&limit=10&sort=created_timestamp&order=DESC&includeNsfw=false"),
    ("Frontend API v3 (coins)", "https://frontend-api-v3.pump.fun/coins?offset=0&limit=10&sort=created_timestamp&order=DESC"),
   ("Client API", "https://client-api-2-74b1891ee9f9.herokuapp.com/coins?offset=0&limit=10&sort=created_timestamp&order=DESC"),
    
    # Pumpportal (third-party aggregator)
    ("PumpPortal Latest", "https://pumpportal.fun/api/data/latest"),
    ("PumpPortal Tokens", "https://pumpportal.fun/api/tokens/latest"),
    
    # API documented in some Discord channels
    ("API v1 latest", "https://api.pump.fun/coins/latest"),
    ("Frontend latest", "https://frontend-api.pump.fun/coins/latest"),
]

# Headers to mimic a real browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://pump.fun/',
    'Origin': 'https://pump.fun',
}

def test_endpoint(name, url):
    """Test an endpoint"""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"URL: {url}")
    print('='*60)
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('Content-Type', 'N/A')}")
        
        if resp.status_code == 200:
            # Try to parse JSON
            try:
                data = resp.json()
                print(f"\n✅ SUCCESS - JSON Response:")
                print(json.dumps(data, indent=2)[:2000])  # First 2000 chars
                
                # Save full response
                filename = name.lower().replace(' ', '_').replace('(', '').replace(')', '') + '.json'
                with open(filename, 'w') as f:
                    json.dump(data, f, indent=2)
                print(f"\n💾 Saved to: {filename}")
                
                return True
            except:
                print(f"\n⚠️  Response not JSON:")
                print(resp.text[:500])
        else:
            print(f"\n❌ Failed - Response:")
            print(resp.text[:500])
        
        return False
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


if __name__ == '__main__':
    print("🔍 Testing Pump.fun API Endpoints\n")
    
    successes = []
    
    for name, url in ENDPOINTS:
        if test_endpoint(name, url):
            successes.append(name)
    
    print(f"\n\n{'='*60}")
    print(f"SUMMARY: {len(successes)}/{len(ENDPOINTS)} endpoints working")
    print('='*60)
    
    if successes:
        print("\n✅ Working endpoints:")
        for name in successes:
            print(f"  - {name}")
    else:
        print("\n❌ No working endpoints found")
        print("\nRECOMMENDATION: Use Dexscreener API instead")
        print("Dexscreener already indexes pump.fun tokens with full data:")
        print("  - Profiles: https://api.dexscreener.com/token-profiles/latest/v1")
        print("  - Boosted: https://api.dexscreener.com/token-boosts/latest/v1")
        print("  - Token details: https://api.dexscreener.com/latest/dex/tokens/{address}")
