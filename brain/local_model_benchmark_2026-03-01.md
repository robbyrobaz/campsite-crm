# Local Model Benchmark Report
**Date**: 2026-03-01 05:56:19
**Hardware**: RTX 2080 Super 8GB, 31GB RAM

## Results Summary

| Model | Task 1 | Task 2 | Task 3 | Avg Score |
|-------|--------|--------|--------|-----------|
| deepseek-coder-v2:16b | 3/3 | 1/3 | 0/3 | 1.33 |
| qwen2.5-coder:14b | 3/3 | 1/3 | 0/3 | 1.33 |

## Detailed Results

### Python Data Query (Blofin style)

**deepseek-coder-v2:16b**: Score 3/3, Time 57.03s, Response: 593 chars
**qwen2.5-coder:14b**: Score 3/3, Time 62.78s, Response: 694 chars

### Bug Fix (Pandas alignment)

**deepseek-coder-v2:16b**: Score 1/3, Time 28.28s, Response: 1127 chars
**qwen2.5-coder:14b**: Score 1/3, Time 50.61s, Response: 929 chars

### Trading Strategy Diagnosis

**deepseek-coder-v2:16b**: Score 0/3, Time 0.0s, Response: 0 chars
**qwen2.5-coder:14b**: Score 0/3, Time 0.0s, Response: 0 chars

## Verdict

**Best model**: deepseek-coder-v2:16b (avg score: 1.33/3)

### Which tasks can go local?
- ✓ Python Data Query (Blofin style): Local models score 3/3 → **VIABLE**
- ✗ Bug Fix (Pandas alignment): Local models score 1/3 → Needs Anthropic
- ✗ Trading Strategy Diagnosis: Local models score 0/3 → Needs Anthropic

### Cost implications
- If local models handle 1-2 tasks at 2+/3 score, estimate ~30-50% reduction in Haiku API calls
- Caveat: Local models slower (5-30s vs <1s for Haiku) → only suitable for async jobs
