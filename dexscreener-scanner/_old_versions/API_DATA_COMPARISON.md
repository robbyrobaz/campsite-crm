# 🔥 Pump.fun + Dexscreener API Data Comparison

## ✅ WORKING APIs

### 1. Pump.fun API v3 (DIRECT SOURCE)
**Endpoint:** `https://frontend-api-v3.pump.fun/coins`

**Parameters:**
- `offset=0` - Pagination offset
- `limit=50` - Number of tokens (max unknown, tested with 10)
- `sort=created_timestamp` - Sort by creation time
- `order=DESC` - Newest first

**Data Available:**
```json
{
  "mint": "CONTRACT_ADDRESS",
  "name": "Token Name",
  "symbol": "SYMBOL",
  "description": "Token description",
  
  "created_timestamp": 1775417297000,  // EXACT CREATION TIME!
  "last_trade_timestamp": 1775417306000,
  
  "twitter": "https://x.com/...",
  "telegram": "https://t.me/...",
  "website": "https://...",
  
  "market_cap": 28.14,
  "usd_market_cap": 2252.53,
  "ath_market_cap": 3035.58,
  "ath_market_cap_timestamp": 1775417297000,
  
  "real_sol_reserves": 98765434,       // REAL LIQUIDITY
  "real_token_reserves": 789579081289035,
  "virtual_sol_reserves": 30098765434,  // Bonding curve reserves
  "virtual_token_reserves": 1069479081289035,
  
  "reply_count": 2,                     // ENGAGEMENT!
  "is_currently_live": false,
  "nsfw": false,
  "is_banned": false,
  "complete": false                     // Graduated to Raydium?
}
```

**Advantages:**
✅ EARLIEST POSSIBLE - tokens appear here FIRST
✅ Exact creation timestamp (millisecond precision)
✅ Real-time engagement metrics (reply_count)
✅ Bonding curve status (complete = graduated to Raydium)
✅ ATH market cap tracking
✅ Ban/NSFW filters

**Disadvantages:**
❌ No price history
❌ No transaction counts
❌ No price change percentages
❌ No volume data by timeframe

---

### 2. Dexscreener API (AGGREGATOR)
**Endpoints:**
- Profiles: `https://api.dexscreener.com/token-profiles/latest/v1`
- Boosted: `https://api.dexscreener.com/token-boosts/latest/v1`
- Token Details: `https://api.dexscreener.com/latest/dex/tokens/{address}`

**Data Available:**
```json
{
  "chainId": "solana",
  "dexId": "pumpfun",                   // DEX identifier
  "baseToken": {
    "address": "CONTRACT",
    "name": "Token Name",
    "symbol": "SYMBOL"
  },
  
  "pairCreatedAt": 1775416525000,
  "pairAddress": "PAIR_ADDRESS",
  
  "priceUsd": "0.00001947",
  "priceNative": "0.0000002428",
  
  "txns": {
    "m5": {"buys": 1099, "sells": 606},  // TRANSACTION COUNTS!
    "h1": {"buys": 1392, "sells": 767},
    "h6": {"buys": 1392, "sells": 767},
    "h24": {"buys": 1392, "sells": 767}
  },
  
  "volume": {                            // VOLUME BY TIMEFRAME!
    "m5": 19658.47,
    "h1": 38628.94,
    "h6": 38628.94,
    "h24": 38628.94
  },
  
  "priceChange": {                       // PRICE CHANGE %!
    "m5": 138,
    "h1": 621,
    "h6": 621,
    "h24": 621
  },
  
  "liquidity": {
    "usd": 19471.52,
    "base": 59602,
    "quote": 15635
  },
  
  "fdv": 19471.52,
  "marketCap": 19471.52,
  
  "info": {
    "imageUrl": "https://...",
    "socials": [
      {"url": "https://x.com/...", "type": "twitter"}
    ]
  },
  
  "boosts": {
    "active": 10                         // PAID PROMOTION!
  }
}
```

**Advantages:**
✅ Transaction counts by timeframe (5m, 1h, 6h, 24h)
✅ Volume tracking
✅ Price change percentages
✅ Buy/sell ratio data
✅ Liquidity in USD
✅ Boost detection (paid promotion indicator!)
✅ Works for ALL DEXes (not just pump.fun)

**Disadvantages:**
❌ Slight delay (tokens appear ~2-5 min after pump.fun)
❌ Less engagement data
❌ No bonding curve info
❌ No graduated/complete status

---

## 🎯 BEST STRATEGY: Use BOTH!

### Workflow:

**1. Primary Source: Pump.fun API**
- Catches tokens at creation (EARLIEST!)
- Get exact timestamp, engagement, bonding curve status
- Filter out banned/NSFW immediately

**2. Validation: Dexscreener API**
- Add price action data (txns, volume, price changes)
- Detect if token is being boosted (paid shill!)
- Calculate buy/sell ratios

**3. Combine Data:**
```python
{
  # From pump.fun:
  'contract': pumpfun['mint'],
  'created_at': pumpfun['created_timestamp'],
  'twitter': pumpfun['twitter'],
  'telegram': pumpfun['telegram'],
  'engagement': pumpfun['reply_count'],
  'is_graduated': pumpfun['complete'],
  
  # From dexscreener:
  'price_change_1h': dex['priceChange']['h1'],
  'volume_1h': dex['volume']['h1'],
  'buys_1h': dex['txns']['h1']['buys'],
  'sells_1h': dex['txns']['h1']['sells'],
  'buy_ratio': buys / sells,
  'is_boosted': dex.get('boosts', {}).get('active', 0) > 0,
  
  # Combined score:
  'score': calculate_combined_score()
}
```

---

## 📊 Data Coverage Comparison

| Feature | Pump.fun API | Dexscreener |
|---------|--------------|-------------|
| **Speed** | ⭐⭐⭐⭐⭐ (instant) | ⭐⭐⭐⭐ (2-5min delay) |
| **Creation time** | ✅ Exact ms | ✅ Exact ms |
| **Social links** | ✅ Direct from creator | ✅ From profile |
| **Engagement** | ✅ reply_count | ❌ None |
| **Transaction counts** | ❌ None | ✅ By timeframe |
| **Volume** | ❌ None | ✅ By timeframe |
| **Price change** | ❌ None | ✅ By timeframe |
| **Liquidity (real)** | ✅ SOL reserves | ✅ USD value |
| **Bonding curve** | ✅ Full data | ❌ None |
| **Graduated status** | ✅ `complete` flag | ❌ None |
| **Boost detection** | ❌ None | ✅ Active boosts |
| **Ban/NSFW** | ✅ Flags | ❌ None |
| **Buy/Sell ratio** | ❌ None | ✅ Calculated |
| **Coverage** | pump.fun only | All DEXes |

---

## 🚀 Implementation Priority

### Phase 1: Dual-Source Scanner (TODAY)
Build scanner that:
1. Polls pump.fun API every 30 sec for new tokens
2. For each new token, query Dexscreener after 2 min
3. Combine data and score
4. Log high-confidence signals

**Expected: 10-20 high-quality signals/day**

### Phase 2: Real-time Integration (THIS WEEK)
- Integrate with paper trading
- Auto-enter on multi-source high scores
- Track pump.fun vs Telegram timing

### Phase 3: Advanced Filtering (NEXT WEEK)
- Machine learning on engagement patterns
- Graduated token tracking
- Boost avoidance logic

---

## 📁 File Locations

**Test Scripts:**
- `test_pumpfun_api.py` - Endpoint discovery tool
- `frontend_api_v3_coins.json` - Sample pump.fun response
- `dex_pumpfun.json` - Sample Dexscreener response

**Scanners:**
- `scanner_live.py` - Current Dexscreener-only scanner
- `scanner_combined.py` - TODO: Pump.fun + Dexscreener

---

## 💡 Key Insights

1. **Pump.fun = Fastest Source** - Tokens appear here BEFORE Dexscreener
2. **Dexscreener = Best Analytics** - Transaction/volume/price data
3. **Combined = Highest Confidence** - Both sources = real token
4. **Engagement Matters** - `reply_count` on pump.fun = community interest
5. **Boost Detection** - Dexscreener shows paid promotion
6. **Graduated Tokens** - `complete: true` means moved to Raydium (bigger pool)

---

**Want me to build the combined scanner now?**
