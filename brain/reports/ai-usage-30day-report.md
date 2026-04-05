# AI Token Usage Report
**Period:** 2026-03-06 to 2026-04-05 (30 days)
**Generated:** 2026-04-05 02:46:14 UTC

---

## Summary

### OpenClaw
- **Sessions Analyzed:** 34,399
- **Total Models:** 15
- **Data Quality:** ✅ Actual API usage (from provider responses)

### Hermes  
- **Sessions Analyzed:** 52
- **Total Models:** 2
- **Data Quality:** ⚠️ Estimated token counts (character-based, not actual API usage)

**IMPORTANT:** OpenClaw and Hermes use the same OAuth account and are billed together by Anthropic.
The sessions are SEPARATE (OpenClaw = automated agents, Hermes = your interactive CLI sessions).
This report is the ONLY billing aggregator - the combined total below is your actual usage.

---

## OpenClaw Usage by Model

| Model | Requests | Input | Output | Cache Read | Cache Write | Total Tokens | Est. Cost |
|-------|----------|-------|--------|------------|-------------|--------------|----------|
| **anthropic-sonnet** | 16,840 | 55.3K | 4.9M | 920.3M | 186.8M | **1112.1M** | $1050.77 |
| **anthropic-opus** | 6,130 | 7.8K | 2.3M | 915.9M | 85.0M | **1003.2M** | $1046.58 |
| **openai-gpt5-codex** | 713 | 23.2M | 258.8K | 73.1M | 0 | **96.6M** | $80.23 |
| **openrouter-nemotron** | 1,491 | 40.0M | 239.8K | 0 | 0 | **40.3M** | $0.00 |
| **anthropic-haiku** | 143 | 793 | 50.0K | 4.8M | 1.1M | **5.9M** | $2.13 |
| **deepseek/deepseek-r1-0528** | 10 | 218.5K | 17.5K | 4 | 0 | **236.0K** | $0.00 |
| **x-ai/grok-4.1-fast** | 60 | 0 | 0 | 0 | 0 | **0** | $0.00 |
| **delivery-mirror** | 43 | 0 | 0 | 0 | 0 | **0** | $0.00 |
| **qwen/qwen3.5-122b-a10b:free** | 11 | 0 | 0 | 0 | 0 | **0** | $0.00 |
| **gateway-injected** | 5 | 0 | 0 | 0 | 0 | **0** | $0.00 |
| **qwen2.5-coder:14b** | 5 | 0 | 0 | 0 | 0 | **0** | $0.00 |
| **qwen/qwen3-coder:free** | 4 | 0 | 0 | 0 | 0 | **0** | $0.00 |
| **deepseek-coder-v2:16b** | 1 | 0 | 0 | 0 | 0 | **0** | $0.00 |
| **x-ai/grok-4-fast** | 8,942 | 0 | 0 | 0 | 0 | **0** | $0.00 |
| **openrouter/nemo-super** | 1 | 0 | 0 | 0 | 0 | **0** | $0.00 |
| **TOTAL** | **34,399** | **63.5M** | **7.8M** | **1914.0M** | **273.0M** | **2258.3M** | **$2179.70** |

---

## Hermes Usage by Model (ESTIMATED - Character-Based Counts)

⚠️ **Note:** These are estimated token counts from Hermes database (character-based approximations).
OpenClaw tracks actual API usage, Hermes estimates. Both contribute to your total bill.

| Model | Requests | Input | Output | Cache Read | Cache Write | Total Tokens | Est. Cost |
|-------|----------|-------|--------|------------|-------------|--------------|----------|
| **anthropic-sonnet** | 50 | 20.4K | 1.4M | 191.4M | 17.3M | **210.2M** | $0.00 |
| **nvidia/nemotron-3-super-120b-a12b:free** | 2 | 195.8K | 1.2K | 0 | 0 | **197.0K** | $0.00 |
| **TOTAL** | **52** | **216.1K** | **1.4M** | **191.4M** | **17.3M** | **210.4M** | **$0.00** |

---

## Combined Totals (OpenClaw + Hermes)

- **Total Requests:** 34,451
- **Total Tokens:** 2468.7M (2,468,704,829)
- **Estimated Cost:** $2179.70
- **Cost per Day:** $72.66
- **Projected Monthly:** $2179.70

### Cache Efficiency
- **Cache Read Tokens:** 2105.4M
- **Cache Hit Rate:** 85.3%

---

## Current Subscription

**Claude Max 20x:** $200/month

### Analysis
- **Actual Usage:** $2179.70/month (projected)
- **Subscription Value:** ✅ Good deal
- **Cache Savings:** Estimated $6316.31 saved via prompt caching

---

## Alternative Provider Options

### OpenRouter
- **Pros:** Access to multiple models, pay-per-use, no subscription
- **Cons:** No prompt caching on most models
- **Estimated Cost:** $2179.70 for this 30-day period (without caching benefits)

### Direct Anthropic API
- **Pros:** Full caching support, usage-based pricing
- **Cons:** Higher per-token cost than subscription if usage is heavy
- **Estimated Cost:** $2179.70 for this 30-day period

### Keep Claude Max 20x If:
1. Cache hit rate stays above 80% (currently 85.3%)
2. Projected monthly > $200 (currently $2179.70)
3. Need higher rate limits for bursts

### Switch to Pay-Per-Use If:
1. Usage drops significantly
2. Cache hit rate falls below 50%
3. Projected monthly consistently < $150

---

**Next Steps:**
1. Monitor usage for another 30 days
2. Compare cache efficiency trends
3. Test OpenRouter for non-cached workloads
4. Evaluate if Haiku can replace Sonnet for some tasks

