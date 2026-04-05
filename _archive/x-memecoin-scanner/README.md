# X/Twitter Memecoin Scanner

Scans X/Twitter for early memecoin mentions using **twikit** (no API key needed).

## Features

✅ **No paid API** - Uses normal X account with cookie auth
✅ **Multiple search queries** - 6 optimized queries for early launches
✅ **Contract extraction** - Auto-detects Solana addresses
✅ **Confluence scoring** - Tracks contracts mentioned by multiple sources
✅ **Hype scoring** - Weights tweets by engagement + keywords
✅ **JSONL logging** - All signals saved for analysis

---

## Setup (5 minutes)

### 1. Install Dependencies

Already done if you followed the initial setup:
```bash
cd ~/.openclaw/workspace/x-memecoin-scanner
source venv/bin/activate
```

### 2. Configure Credentials

```bash
cp .env.template .env
nano .env
```

Add your **normal X account credentials** (NOT developer API):
```bash
X_USERNAME=your_x_username
X_EMAIL=your_email@example.com
X_PASSWORD=your_password
```

⚠️ **Important:** This uses your regular X account to browse tweets (like you would in a browser). No special API access needed.

### 3. Test First Run

```bash
source venv/bin/activate
python scanner.py
```

On first run:
- Logs in with your credentials
- Saves cookies to `cookies.json` (reused for future runs)
- Searches 6 queries for memecoin mentions
- Logs all signals to `logs/x_signals.jsonl`
- Shows high-confluence contracts (mentioned multiple times)

---

## Automated Scanning

### Run Every 5 Minutes with Cron

```bash
crontab -e
```

Add:
```bash
*/5 * * * * cd /home/rob/.openclaw/workspace/x-memecoin-scanner && ./venv/bin/python scanner.py >> logs/cron.log 2>&1
```

This runs the scanner every 5 minutes automatically.

---

## What Gets Logged

### `logs/x_signals.jsonl`
Every tweet with a contract address:
```json
{
  "timestamp": "2026-04-05T15:30:00Z",
  "tweet_id": "1234567890",
  "user": "crypto_degen",
  "user_followers": 15000,
  "text": "🚀 NEW GEM just launched! CA: AbC123...",
  "contracts": ["AbC123..."],
  "likes": 45,
  "retweets": 12,
  "replies": 8,
  "hype_score": 15,
  "query": "just launched Solana CA:",
  "url": "https://x.com/crypto_degen/status/1234567890"
}
```

### `logs/confluence.jsonl`
High-confluence contracts (multiple mentions):
```json
{
  "timestamp": "2026-04-05T15:30:00Z",
  "total_scanned": 142,
  "high_confluence": {
    "AbC123...": {
      "count": 5,
      "queries": ["just launched Solana CA:", "new token contract 🚀"],
      "users": ["user1", "user2", "user3"],
      "total_hype": 78,
      "first_seen": "2026-04-05T15:25:00Z",
      "tweets": [...]
    }
  }
}
```

---

## Search Queries (Optimized for Early Detection)

1. `just launched Solana CA:` - Catches immediate launches
2. `new token contract 🚀` - General new tokens with hype
3. `fair launch Solana` - Fair launch announcements
4. `CA: Solana gem` - Gems with contract addresses
5. `pump.fun new` - Pump.fun launches (common memecoin platform)
6. `raydium just added` - Raydium DEX listings

You can modify these in `scanner.py` → `SEARCH_QUERIES`

---

## Confluence Scoring

**Strong Signal = Multiple Independent Mentions**

A contract gets flagged as "high confluence" when:
- Mentioned by 2+ different search queries, OR
- Mentioned by 2+ different users

This filters out single-shill posts and finds coins getting real buzz.

---

## Integration with Existing Memecoin Scanner

### Merge with Telegram Scanner

The existing `~/.openclaw/workspace/autonomous-memecoin-hunter/` scans 3 Telegram channels.

**To combine both:**

1. Both scanners log to JSONL files
2. Create a "confluence engine" that reads both:
   - `x-memecoin-scanner/logs/x_signals.jsonl`
   - `autonomous-memecoin-hunter/logs/signals.jsonl`
3. Find contracts mentioned on BOTH X and Telegram within 15 minutes
4. Those are the strongest signals → auto-enter

I can build this confluence engine next if you want multi-platform signal detection.

---

## Monitoring

**Watch live:**
```bash
tail -f logs/cron.log
```

**Check signals found today:**
```bash
cat logs/x_signals.jsonl | jq 'select(.timestamp | startswith("2026-04-05"))' | jq -s 'length'
```

**See high-confluence contracts:**
```bash
cat logs/confluence.jsonl | jq '.high_confluence | keys'
```

---

## Rate Limits & Best Practices

**twikit uses cookies (not official API), so:**
- ✅ No hard rate limits like API
- ⚠️ Don't spam searches (2-second pause between queries)
- ✅ Cookies last ~30 days (auto-refreshed on each run)
- ⚠️ Use residential IP if possible (VPS IPs get flagged more)

If you see login errors:
1. Check if X flagged your account (try logging in via browser)
2. Delete `cookies.json` and re-run (forces fresh login)
3. Use a different account if needed

---

## Next Steps

1. ✅ **Test it** - Run `python scanner.py` once manually
2. ✅ **Set up cron** - Auto-scan every 5 minutes
3. ✅ **Let it collect data** - Run for 24 hours
4. 📊 **Analyze patterns** - Which contracts got multiple mentions?
5. 🔀 **Build confluence engine** - Merge X + Telegram signals

Want me to:
- Build the confluence engine (combines X + Telegram)?
- Create an analyzer script to find patterns?
- Set up the cron job for you?
