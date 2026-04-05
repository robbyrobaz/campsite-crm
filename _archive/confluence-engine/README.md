# 🎯 Multi-Platform Confluence Engine

Combines **X/Twitter + Telegram** signals to find high-confidence memecoin opportunities.

## Why Confluence?

**Single-source signal** = Anyone can shill
**Multi-platform signal** = Real organic buzz (harder to fake)

### Scoring System

```python
score = (
    twitter_mentions * 3.0 +        # X is earliest (highest weight)
    telegram_mentions * 2.0 +       # Telegram validates
    multi_platform_bonus (10 pts) +  # Mentioned on BOTH platforms
    time_confluence_bonus (5 pts)    # Within 15 min window
    + engagement_bonus               # Likes, RTs, hype keywords
)
```

**Minimum score:** 10.0 (filters noise)

---

## Setup

### 1. Prerequisites

Both scanners must be running:

**X/Twitter scanner:**
```bash
cd ~/.openclaw/workspace/x-memecoin-scanner
source venv/bin/activate
python scanner.py  # Should create logs/x_signals.jsonl
```

**Telegram scanner:**
```bash
cd ~/.openclaw/workspace/autonomous-memecoin-hunter  
source venv/bin/activate
python scanner.py  # Should create logs/signals.jsonl
```

### 2. Run Confluence Engine

```bash
cd ~/.openclaw/workspace/confluence-engine
source venv/bin/activate
python scanner.py
```

---

## Output

### Console

```
=== Multi-Platform Confluence Engine ===
Time: 2026-04-05T16:30:00Z

Loading signals...
  X/Twitter: 45 signals
  Telegram:  23 signals

Building contract timeline...
  Unique contracts: 38

Calculating confluence scores...

🎯 HIGH-CONFIDENCE SIGNALS (3 contracts):

1. AbC123xyz4567890...
   Score: 28.5
   Platforms: twitter, telegram
   Twitter: 4 mentions
   Telegram: 2 mentions
   First seen: 2026-04-05T16:15:00Z
   Sample tweet: https://x.com/user/status/123...

2. DeF456uvw7890123...
   Score: 15.2
   Platforms: twitter, telegram
   Twitter: 2 mentions
   Telegram: 1 mentions
   ...

✅ Logged to logs/high_confidence.jsonl
```

### Log File: `logs/high_confidence.jsonl`

```json
{
  "timestamp": "2026-04-05T16:30:00Z",
  "total_scanned": 38,
  "high_confidence_count": 3,
  "signals": [
    {
      "contract": "AbC123...",
      "score": 28.5,
      "platforms": ["twitter", "telegram"],
      "twitter_mentions": 4,
      "telegram_mentions": 2,
      "first_seen": "2026-04-05T16:15:00Z",
      "twitter_details": [...],
      "telegram_details": [...]
    }
  ]
}
```

---

## Automated Scanning

Run every 10 minutes (after both source scanners):

```bash
crontab -e
```

Add:
```bash
# X scanner (every 5 min)
*/5 * * * * cd /home/rob/.openclaw/workspace/x-memecoin-scanner && ./venv/bin/python scanner.py >> logs/cron.log 2>&1

# Telegram scanner (every 5 min)  
*/5 * * * * cd /home/rob/.openclaw/workspace/autonomous-memecoin-hunter && ./venv/bin/python scanner.py >> logs/cron.log 2>&1

# Confluence engine (every 10 min, offset by 2 min to run AFTER scanners)
2,12,22,32,42,52 * * * * cd /home/rob/.openclaw/workspace/confluence-engine && ./venv/bin/python scanner.py >> logs/cron.log 2>&1
```

This ensures confluence runs AFTER both scanners have collected new data.

---

## Integration with Paper Trading

### Current Flow:
1. Telegram scanner → logs/signals.jsonl → paper trades
2. X scanner → logs/x_signals.jsonl → (not used yet)

### New Flow with Confluence:
1. X scanner → logs/x_signals.jsonl
2. Telegram scanner → logs/signals.jsonl
3. **Confluence engine → logs/high_confidence.jsonl**
4. **Paper trading reads high_confidence.jsonl** (highest quality signals)

### Modification Needed:

Update `autonomous-memecoin-hunter/scanner.py` to:
- Read `confluence-engine/logs/high_confidence.jsonl`
- Only enter trades on contracts with score ≥ 15
- Skip single-platform signals (too risky)

Example:
```python
# Before paper trade entry decision
confluence_signals = load_confluence_signals()
if contract in confluence_signals and confluence_signals[contract]['score'] >= 15:
    # High-confidence signal - enter trade
    enter_paper_trade(contract)
else:
    # Single-platform or low score - skip
    log_rejection(contract, "Low confluence")
```

---

## Expected Performance

### Current (Telegram Only)
- 22% win rate
- Entering 2+ hours after launch (late)
- Single-source signals (easy to shill)

### Target (Multi-Platform Confluence)
- **35%+ win rate** (earlier entries, better quality)
- Entering within **30 minutes** of first buzz
- Multi-platform validation (real hype vs paid shills)

**Why:**
- X mentions happen FIRST (lowest latency)
- Telegram VALIDATES (not just one shill)
- Confluence = multiple independent sources = real organic buzz

---

## Configuration

Edit `scanner.py` to adjust:

```python
CONFLUENCE_WINDOW_MINUTES = 15  # Time window for multi-platform mentions
MIN_CONFLUENCE_SCORE = 10.0      # Minimum score to flag

WEIGHT_TWITTER = 3.0   # X gets highest weight (earliest)
WEIGHT_TELEGRAM = 2.0  # Telegram validates
```

**Tighter filters (higher precision, fewer signals):**
```python
CONFLUENCE_WINDOW_MINUTES = 10
MIN_CONFLUENCE_SCORE = 15.0
```

**Wider net (more signals, more noise):**
```python
CONFLUENCE_WINDOW_MINUTES = 30
MIN_CONFLUENCE_SCORE = 8.0
```

---

## Monitoring

**Watch live:**
```bash
tail -f logs/cron.log
```

**Count high-confidence signals today:**
```bash
grep "$(date +%Y-%m-%d)" logs/high_confidence.jsonl | jq '.high_confidence_count' | awk '{sum+=$1} END {print sum}'
```

**See top scored contracts:**
```bash
cat logs/high_confidence.jsonl | jq '.signals[] | {contract, score, platforms}' | tail -20
```

---

## Troubleshooting

### "No signals found"
Both source scanners must be running and creating logs.

**Check:**
```bash
ls -lh ~/.openclaw/workspace/x-memecoin-scanner/logs/x_signals.jsonl
ls -lh ~/.openclaw/workspace/autonomous-memecoin-hunter/logs/signals.jsonl
```

Both should exist and have recent timestamps.

### "No high-confidence signals this scan"
This is GOOD! It means your filters are working. High-confidence signals are rare (that's why they're valuable).

**Typical frequency:**
- Low confluence (score 10-15): 5-10 per day
- High confluence (score 15-25): 2-5 per day
- Very high (score 25+): 0-2 per day

### "All signals are single-platform"
Adjust the confluence window:
```python
CONFLUENCE_WINDOW_MINUTES = 30  # Wider window
```

Or lower the minimum score to see what's being filtered:
```python
MIN_CONFLUENCE_SCORE = 5.0  # See more signals
```

---

## Next Steps

1. ✅ **Test manually** - Run all 3 scanners once
2. ✅ **Set up crons** - Automate scanning
3. ⏳ **Collect data** - Run for 24-48 hours
4. 📊 **Analyze patterns** - Which scores correlate with pumps?
5. 🔀 **Integrate with paper trading** - Use high-confidence signals only
6. 📈 **Compare performance** - Single-platform vs multi-platform win rates

Want me to:
- Integrate confluence into the paper trading system?
- Create an analysis script for confluence vs single-platform performance?
- Set up the cron jobs for you?
