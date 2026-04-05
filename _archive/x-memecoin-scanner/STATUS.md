# 🎯 X/Twitter Memecoin Scanner - READY FOR TESTING

## What Was Built

✅ **Complete X/Twitter scanner using twikit** (no API key needed)
✅ **6 optimized search queries** for early memecoin detection
✅ **Confluence detection** (tracks contracts mentioned multiple times)
✅ **Hype scoring** (engagement + keywords)
✅ **JSONL logging** (all signals saved)
✅ **Analysis script** (view top contracts, users, patterns)
✅ **Hermes skill** created for reusability

**Location:** `~/.openclaw/workspace/x-memecoin-scanner/`

---

## Files Created

```
x-memecoin-scanner/
├── scanner.py           # Main scanner (runs every 5 min)
├── analyze.py           # Analyze collected signals
├── test_search.py       # Test authentication
├── .env.template        # Credentials template
├── README.md            # Full documentation
├── STATUS.md            # This file
└── venv/                # Python environment with twikit
```

---

## How It Works

### 1. Authentication
- Uses **your normal X account** (username/email/password)
- NOT developer API keys
- Saves cookies after first login (no re-login needed)

### 2. Scanning Process
Runs 6 search queries every 5 minutes:
- `just launched Solana CA:`
- `new token contract 🚀`
- `fair launch Solana`
- `CA: Solana gem`
- `pump.fun new`
- `raydium just added`

### 3. Signal Extraction
For each tweet:
- Extracts Solana contract addresses (base58, 32-44 chars)
- Calculates hype score (engagement + keywords)
- Logs everything to `logs/x_signals.jsonl`

### 4. Confluence Detection
Tracks contracts mentioned by:
- 2+ different users, OR
- 2+ different search queries

These get flagged as **high-confluence** in `logs/confluence.jsonl`

---

## Setup Instructions

### Step 1: Configure Credentials

```bash
cd ~/.openclaw/workspace/x-memecoin-scanner
cp .env.template .env
nano .env
```

Add your X credentials:
```
X_USERNAME=your_username
X_EMAIL=your_email@example.com
X_PASSWORD=your_password
```

### Step 2: Test First Run

```bash
source venv/bin/activate
python scanner.py
```

Expected output:
```
=== X Memecoin Scanner ===
Time: 2026-04-05T...

Logging in to X...
✅ Logged in and saved cookies

Searching: 'just launched Solana CA:'...
  Found 3 signals
Searching: 'new token contract 🚀'...
  Found 5 signals
...

📊 Total signals found: 12

🎯 STRONG CONFLUENCE (2 contracts):
  AbC123xyz...
    Mentions: 3 | Users: 2 | Total Hype: 45

✅ Scan complete
```

### Step 3: Set Up Cron (Automated Scanning)

```bash
crontab -e
```

Add this line:
```bash
*/5 * * * * cd /home/rob/.openclaw/workspace/x-memecoin-scanner && ./venv/bin/python scanner.py >> logs/cron.log 2>&1
```

This runs the scanner every 5 minutes automatically.

### Step 4: Let It Collect Data

Run for 24-48 hours to collect enough signals for pattern analysis.

### Step 5: Analyze Results

```bash
python analyze.py
```

Shows:
- Top 10 contracts by confluence
- Top signal users (KOLs)
- Query effectiveness
- Average hype scores

---

## Integration with Existing Scanner

### Current State

You have **two scanners** now:

1. **Telegram Scanner** (existing)
   - Location: `~/.openclaw/workspace/autonomous-memecoin-hunter/`
   - Scans: 3 Telegram channels
   - Logs to: `logs/signals.jsonl`

2. **X/Twitter Scanner** (new)
   - Location: `~/.openclaw/workspace/x-memecoin-scanner/`
   - Scans: 6 X search queries
   - Logs to: `logs/x_signals.jsonl`

### Next Step: Build Confluence Engine

**Goal:** Find contracts mentioned on BOTH X and Telegram within 15 minutes = strongest signals

**Implementation:**
```python
# confluence_engine.py (to be built)

# 1. Read X signals
x_signals = load_jsonl('x-memecoin-scanner/logs/x_signals.jsonl')

# 2. Read Telegram signals  
tg_signals = load_jsonl('autonomous-memecoin-hunter/logs/signals.jsonl')

# 3. Find overlaps within 15-min window
for contract in all_contracts:
    x_time = first_x_mention(contract)
    tg_time = first_tg_mention(contract)
    
    if abs(x_time - tg_time) < 15 * 60:  # 15 minutes
        # STRONG MULTI-PLATFORM SIGNAL
        score = calculate_multi_platform_score(contract)
        
        if score >= 10:
            # Auto-enter or alert
            enter_trade(contract)
```

Want me to build this next?

---

## Expected Performance Improvement

### Current (Telegram Only)
- 22% win rate
- Entering late (2+ hours after launch)
- Single-source signals (easy to shill)

### Target (X + Telegram Confluence)
- **35%+ win rate** (earlier entries)
- Catching launches within **30 minutes** of first buzz
- Multi-platform validation (harder to fake)
- Better signal quality (real buzz vs paid shills)

**Why this works:**
- X mentions happen FIRST (lowest latency)
- Telegram validates (not just one person shilling)
- Confluence = multiple independent sources = real hype

---

## Monitoring

### Watch scanner logs
```bash
tail -f logs/cron.log
```

### Check if it's working
```bash
# Count signals collected today
grep "$(date +%Y-%m-%d)" logs/x_signals.jsonl | wc -l

# View last 5 signals
tail -5 logs/x_signals.jsonl | jq .

# See high-confluence contracts
cat logs/confluence.jsonl | jq '.high_confluence | keys' | tail -1
```

---

## Troubleshooting

### "Login failed"
- X may flag VPS IPs as bots
- Try from personal machine or use residential proxy
- Delete `cookies.json` and retry

### "No signals found"
- Normal! Memecoin launches are sporadic
- Let it run for hours to collect data
- Not every 5-min scan will find contracts

### "Too many false positives"
- Tighten search queries (more specific keywords)
- Raise confluence threshold (require 3+ mentions)
- Filter by user follower count (>5K only)

---

## What to Do Now

1. ✅ **Test authentication** - Run `python scanner.py` once
2. ✅ **Set up cron** - Auto-scan every 5 minutes
3. ⏳ **Let it collect data** - Run for 24-48 hours
4. 📊 **Analyze patterns** - Run `python analyze.py`
5. 🔀 **Build confluence engine** - Combine X + Telegram signals

**Want me to:**
- Set up the cron job for you?
- Build the multi-platform confluence engine?
- Test the scanner right now?
- Analyze the existing 28K Moonshot trades for more patterns?
