# AI Pricing Reference (April 2026)

**NEVER quote $2,000+/month costs for Rob's usage again!**

## Rob's Actual Usage (30 days)
- Total: 2.25B tokens
- Fresh input: 63.5M
- Cache write: 272.6M  
- Cache read: 1,908.4M (84.7% hit rate!)
- Output: 7.7M

## Correct Pricing (OpenRouter + 5.5% fee)

### MiniMax M2.5 (BEST VALUE)
- Input: $0.118/M
- Cache read: $0.059/M
- Output: $0.99/M
- **Rob's cost: ~$140-170/mo**
- Automatic caching, no code changes
- 80%+ quality on coding/agents

### DeepSeek V3.2
- Input: $0.26/M
- Cache read: $0.13/M
- Output: $0.38/M
- **Rob's cost: ~$290-330/mo**
- Automatic caching

### Claude Sonnet 4.6 (via OpenRouter)
- Input: $3.00/M
- Cache read: $0.30/M
- Output: $15.00/M
- **Rob's cost: ~$800/mo** (not $2,000+!)

### Current: Claude Max 20x
- **Flat $200/mo** unlimited

## Recommendation
Switch to MiniMax M2.5 on OpenRouter to save $30-60/mo vs Claude Max subscription.

## Updated in:
- `~/.openclaw/workspace/brain/reports/ai-usage-30day-report.md`
- `~/.openclaw/openclaw.json` (model pricing config)
- This reference doc
