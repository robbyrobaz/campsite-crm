# AI Usage Analysis Skill

**Purpose:** Analyze token usage across OpenClaw and Hermes systems for cost tracking and provider comparison

**Tool:** `~/.openclaw/workspace/ai-usage-analyzer.py`

## Usage

```bash
cd ~/.openclaw/workspace
python3 ai-usage-analyzer.py
```

**Output:** `~/.openclaw/workspace/brain/reports/ai-usage-30day-report.md`

## What It Does

1. **Parses OpenClaw sessions:** All agents (main, crypto, nq, sp, church) from `~/.openclaw/agents/*/sessions/*.jsonl`
2. **Parses Hermes sessions:** Main + profiles from `~/.hermes/sessions/*.jsonl` and `~/.hermes/profiles/*/sessions/*.jsonl`
3. **Aggregates by model:** Groups usage by model type (anthropic-sonnet, opus, haiku, openai-gpt5, etc.)
4. **Calculates costs:** Token costs including cache read/write savings
5. **Generates report:** Comprehensive markdown with recommendations

## Key Metrics

- Total tokens by model
- Cache hit rate (critical for subscription value)
- Actual cost vs subscription cost
- Provider recommendations

## When To Run

- Monthly (to evaluate subscription value)
- Before considering provider changes
- When usage patterns change significantly
- For budget planning

## Interpretation

**Keep $200/mo Claude Max 20x if:**
- Cache hit rate > 80%
- Projected monthly cost > $200
- Need burst capacity

**Consider switching if:**
- Cache hit rate < 50%
- Projected cost < $150/mo consistently
- Usage becomes sporadic

