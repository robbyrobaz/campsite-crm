# 🚀 Multi-Source Memecoin Scanner + Paper Trader

**Status:** LIVE (Deployed April 5, 2026)
**Strategy:** Find the 5% winners, cut the 50% rugs, let winners run 10x-100x

---

## System Architecture

### Active Components:

#### 1. **Multi-Source Scanner** (`dexscreener-scanner/`)
Main scanner combining three data sources:
- 🔥 **Pump.fun API** - Catches tokens at creation (0-30 sec)
- 📊 **Dexscreener API** - Validates with price/volume data (2-5 min delay)
- 📱 **Telegram Scanner** - Social proof from 3 quality channels

**Run it:**
```bash
cd dexscreener-scanner
./RUN_SCANNER.sh
```

**Key files:**
- `scanner_multi_source.py` - Main scanner
- `MASTER_STRATEGY.md` - Complete strategy documentation
- `README_LIVE.md` - Operational guide
- `logs/*.jsonl` - All data (tokens, scores, trades)

#### 2. **Telegram Scanner** (`autonomous-memecoin-hunter/`)
Monitors 3 quality Telegram channels for memecoin mentions:
- @gmgnsignals (100 contracts/day)
- @XAceCalls (83 contracts/day)
- @NewDexListings (5 contracts/day)

**Run it:**
```bash
cd autonomous-memecoin-hunter
source venv/bin/activate
python scanner.py
```

**Key files:**
- `scanner.py` - Telegram monitoring bot
- `logs/signals.jsonl` - All Telegram mentions
- `.env` - Telegram API credentials (not committed)

---

## How It Works

### Multi-Source Scoring (0-100 points)

**Speed (0-30):** Earlier = better (<5min = 30pts)
**Liquidity (0-15):** More $ = safer (>$50k = 15pts)
**Engagement (0-15):** Real people = demand (>100 engaged = 15pts)
**Price Action (0-20):** Pumping = momentum (>100% = 20pts)
**Buy Pressure (0-10):** Buys > Sells = bullish (3:1 ratio = 10pts)
**Multi-Source Bonus (0-15):** All 3 sources = max confidence (15pts)
**Red Flags (subtract):** Banned (-100), NSFW (-20), heavy boost (-10), late to party (-15)

### Entry Tiers

**Tier 1 (80-100 score):** $15 position (3x size) - MAXIMUM CONFIDENCE
**Tier 2 (60-79 score):** $10 position (2x size) - HIGH CONFIDENCE
**Tier 3 (40-59 score):** $5 position (1x size) - MEDIUM CONFIDENCE
**Tier 4 (<40 score):** Skip - not enough conviction

### Exit Strategy (CRITICAL)

**Stop Loss:** -30% (cut losers FAST, no exceptions)

**Take Profit (scale out):**
- +50%: Sell 20% (recover entry, free ride the rest)
- +100%: Sell 20% (lock profit)
- +200%: Sell 20% (lock more)
- +500%: Sell 20% (getting serious)
- +1000%: Sell 20% (final exit)

**Moon Bag:** Keep final 20% (catch 100x outliers)

---

## Expected Performance

**Reality:**
- 50%+ will rug → -30% loss each
- 30% break even or small loss
- 10-20% WIN BIG → +500% to +1000%

**The Math:**
- Enter 10 positions/day
- 8-10 fail at -30% = -$40-50 loss
- 2-3 break even = -$5 loss
- 1-2 WIN at +500-1000% = +$100-500 gain
- **Net: +$45 to +$445/day**

**Key Insight:** We don't need high win rate. We need to cut losers fast and let winners run. A few 10x winners pay for all the small losses.

---

## Data Collection

**All forward test data logged to:**
```
dexscreener-scanner/logs/
├── pumpfun_tokens.jsonl      # Raw Pump.fun data
├── scored_tokens.jsonl        # Every token scored
├── paper_trades.jsonl         # Entry/exit log
└── open_positions.jsonl       # Current positions

autonomous-memecoin-hunter/logs/
├── signals.jsonl              # Telegram mentions
├── paper_trades.jsonl         # (Deprecated - using main scanner now)
└── rejections.jsonl           # (Deprecated)
```

**After 3-7 days:** Analyze which scores predicted winners, optimize weights

---

## Archive

**Old/deprecated code moved to:**
- `_archive/` - Old scanner approaches (confluence-engine, x-memecoin-scanner)
- `dexscreener-scanner/_old_versions/` - Previous scanner iterations
- `autonomous-memecoin-hunter/_old_tools/` - Discovery/analysis tools

---

## Quick Commands

**Start everything:**
```bash
cd ~/.openclaw/workspace/dexscreener-scanner
./RUN_SCANNER.sh
```

**Check recent trades:**
```bash
tail -20 dexscreener-scanner/logs/paper_trades.jsonl | jq .
```

**Check high scores:**
```bash
cat dexscreener-scanner/logs/scored_tokens.jsonl | jq 'select(.score >= 60)'
```

**Stop scanner:**
```bash
# Press Ctrl+C in the terminal running it
# Or: pkill -f scanner_multi_source.py
```

---

## Strategy Reference

**Full documentation:** `dexscreener-scanner/MASTER_STRATEGY.md`

**Key Principle (Rob's directive):**
> "FT is FREE. Expect 95% losers. Only track top performers. Never report aggregate metrics. LET WINNERS RUN."

---

## Status

✅ Multi-source scanner LIVE
✅ Telegram scanner ACTIVE (3 channels)
✅ Paper trading ENABLED ($100 starting balance)
✅ Data collection RUNNING
✅ All logs being saved for analysis
✅ Repository CLEAN (old code archived)

**Next milestone:** 3-7 days forward data → Analyze → Optimize scoring → Deploy v2

🚀🚀🚀
