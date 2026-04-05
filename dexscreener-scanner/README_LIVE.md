# 🚀 LIVE MULTI-SOURCE MEMECOIN SCANNER + PAPER TRADER

**Status:** DEPLOYED AND RUNNING
**Reset:** April 5, 2026 7:35 PM MST
**Starting Balance:** $100

---

## What This Does

**FINDS WINNERS IN REAL-TIME:**
- 🔥 Pump.fun API - Catches tokens at creation (0-30 sec)
- 📊 Dexscreener - Validates with price/volume data (2+ min)
- 📱 Telegram - Adds social proof (30min - 3hr)

**SCORES EVERY TOKEN (0-100):**
- Speed (0-30): Earlier = better
- Liquidity (0-15): More = safer
- Engagement (0-15): Real people = real demand
- Price Action (0-20): Pumping = momentum
- Buy Pressure (0-10): Buys > Sells = bullish
- Multi-Source (0-15): All 3 sources = max confidence
- Red Flags: Banned, NSFW, heavy boost, late to party

**AUTO-ENTERS PAPER TRADES:**
- Score 80-100 (Tier 1): $15 position (3x)
- Score 60-79 (Tier 2): $10 position (2x)
- Score 40-59 (Tier 3): $5 position (1x)
- Score <60: Skip

**EXIT STRATEGY:**
- Stop Loss: -30% (cut losers FAST)
- Take Profit: 20% at each level (+50%, +100%, +200%, +500%, +1000%)
- Moon Bag: Keep final 20% (catch 100x outliers)

---

## Quick Start

**START EVERYTHING:**
```bash
cd ~/.openclaw/workspace/dexscreener-scanner
./RUN_SCANNER.sh
```

This starts:
1. Telegram scanner (background)
2. Multi-source scanner + paper trader (foreground)

**STOP:**
- Press `Ctrl+C`

---

## What Gets Logged

**All data saved to `logs/`:**

```
logs/
├── pumpfun_tokens.jsonl      # Raw pump.fun data
├── scored_tokens.jsonl        # All scored tokens (for analysis)
├── paper_trades.jsonl         # All entries/exits
└── open_positions.jsonl       # Current positions
```

**Every token gets logged with:**
- Score breakdown (speed, liquidity, engagement, etc)
- Entry decision (tier, position size)
- Outcome tracking (for future analysis)

---

## Expected Performance

**Reality Check:**
- 50%+ will rug/fail → -30% stop loss
- 30% will break even/small loss
- 10-20% will WIN → +200% to +1000%

**Key to Profit:**
- Cut losers at -30% (no exceptions!)
- Let winners run to +500-1000%
- A few 10x winners pay for many small losses

**Target (after system learns):**
- 35-40% win rate
- Average winner: 5x-10x
- Average loser: -30%
- Net: Profitable

---

## Monitoring

**Watch it run:**
```bash
cd ~/.openclaw/workspace/dexscreener-scanner
./RUN_SCANNER.sh
```

**Check recent trades:**
```bash
tail -20 logs/paper_trades.jsonl | jq .
```

**Check scored tokens:**
```bash
tail -10 logs/scored_tokens.jsonl | jq '.symbol, .score, .details'
```

**Count by tier:**
```bash
cat logs/scored_tokens.jsonl | jq -r .score | awk '{
  if ($1>=80) tier1++;
  else if ($1>=60) tier2++;
  else if ($1>=40) tier3++;
  else tier4++;
}
END {
  print "Tier 1 (80-100): " tier1
  print "Tier 2 (60-79): " tier2  
  print "Tier 3 (40-59): " tier3
  print "Tier 4 (<40): " tier4
}'
```

---

## File Structure

```
~/.openclaw/workspace/dexscreener-scanner/
├── scanner_multi_source.py       # MAIN SCANNER
├── RUN_SCANNER.sh                # START SCRIPT
├── MASTER_STRATEGY.md            # Full strategy doc
├── API_DATA_COMPARISON.md        # Data sources explained
├── BACKTEST_REALITY_CHECK.md     # Why we're forward testing
├── README_LIVE.md                # THIS FILE
│
├── logs/
│   ├── pumpfun_tokens.jsonl     # Raw data
│   ├── scored_tokens.jsonl      # Scored + analyzed
│   ├── paper_trades.jsonl       # Trade log
│   └── open_positions.jsonl     # Current positions
│
└── venv/                         # Python environment
```

---

## Next Steps

**After 3-7 days of data collection:**
1. Analyze `scored_tokens.jsonl` + `paper_trades.jsonl`
2. Check: Do high scores correlate with winners?
3. Optimize: Adjust scoring weights based on real data
4. Deploy: Updated scoring to production

**For now:**
- Let it run and collect data
- Trust the scoring (it's our best guess)
- Focus on letting winners run
- Cut losers at -30%

---

## The Goal

**Make money while collecting data to make MORE money.**

- 50% will rug → Expected, priced in
- Few big winners → Where profit comes from
- System learns → Gets better over time

**Rob's directive:** "FT is FREE. Expect 95% losers. Only track top performers. LET WINNERS RUN."

---

## Status

✅ **LIVE AND RUNNING**
✅ **All data reset (clean slate)**
✅ **Starting balance: $100**
✅ **Multi-source scoring active**
✅ **Paper trading enabled**
✅ **Logging everything for analysis**

**LET'S GO! 🚀**
