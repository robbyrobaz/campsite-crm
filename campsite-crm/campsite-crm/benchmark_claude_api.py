#!/usr/bin/env python3
"""
Claude API Benchmark - Real coding + trading tasks
Tests Anthropic Claude models for comparison with local models
"""

import anthropic
import time
import json
from datetime import datetime
from typing import Dict, Tuple

# Test tasks (same as for local models)
TASKS = {
    "task_1_sql_query": {
        "name": "Python data query (Blofin style)",
        "prompt": """Write a Python function that queries SQLite table `strategy_coin_performance` and returns the top 10 rows by `ft_profit_factor` where `ft_trades >= 20` and `ft_max_dd < 25`. Return a list of dicts.

Only provide the function code, no explanation.""",
        "eval_criteria": [
            "Uses sqlite3 or similar",
            "Filters ft_trades >= 20",
            "Filters ft_max_dd < 25",
            "Sorts by ft_profit_factor descending",
            "Returns list of dicts",
            "Code runs without syntax errors",
        ]
    },
    "task_2_bug_fix": {
        "name": "Bug fix (pandas/numpy alignment)",
        "prompt": """I have this code that fails sometimes:

```python
import pandas as pd
import numpy as np
df = pd.DataFrame({"a": [1,2,None,4,5]})
df = df.dropna()
preds = np.array([0.1, 0.2, 0.3, 0.4])
df["pred"] = preds  # this fails sometimes — why and how to fix?
```

Identify the bug, explain why it happens, and provide the fix with corrected code. Be concise.""",
        "eval_criteria": [
            "Identifies index alignment issue",
            "Explains that df has 4 rows but preds has 5 values before dropna",
            "Suggests reset_index(drop=True) or other valid fix",
            "Provides corrected code",
            "Explanation is accurate",
        ]
    },
    "task_3_strategy_logic": {
        "name": "Strategy logic (trading diagnosis)",
        "prompt": """I have a crypto trading strategy with these stats:
- Win rate: 67%
- Net PnL: -$230 (negative!)
- DataFrame columns: entry_price, exit_price, side, pnl_pct, sl_pct, tp_pct

What are the possible causes and how would you diagnose this in Python? Suggest diagnostic code.

Be concise but actionable.""",
        "eval_criteria": [
            "Identifies potential R:R imbalance as cause",
            "Mentions asymmetric stop-loss vs take-profit",
            "Suggests calculating avg win vs avg loss",
            "Provides Python code to analyze the issue",
            "Code is syntactically correct",
            "Diagnostic approach makes sense",
        ]
    },
}

def call_claude(model: str, prompt: str) -> Tuple[str, float]:
    """Call Claude API and return (response, time_taken)"""
    client = anthropic.Anthropic()
    start = time.time()

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        elapsed = time.time() - start
        return response.content[0].text, elapsed
    except Exception as e:
        return f"ERROR: {str(e)}", time.time() - start

def evaluate_response(task_id: str, response: str) -> Tuple[int, list]:
    """
    Evaluate response based on criteria
    """
    task = TASKS[task_id]
    criteria = task["eval_criteria"]
    met = []

    response_lower = response.lower()

    # Task 1: SQL query
    if task_id == "task_1_sql_query":
        checks = {
            "Uses sqlite3 or similar": any(x in response_lower for x in ["sqlite3", "sql", "cursor", "execute"]),
            "Filters ft_trades >= 20": "ft_trades" in response and ">=" in response,
            "Filters ft_max_dd < 25": "ft_max_dd" in response and "<" in response,
            "Sorts by ft_profit_factor descending": "ft_profit_factor" in response,
            "Returns list of dicts": "return" in response_lower and ("dict" in response_lower or "[{" in response),
            "Code runs without syntax errors": "def " in response and "(" in response,
        }

    # Task 2: Bug fix
    elif task_id == "task_2_bug_fix":
        checks = {
            "Identifies index alignment issue": any(x in response_lower for x in ["index", "alignment", "mismatch", "shape"]),
            "Explains that df has 4 rows but preds has 5 values before dropna": "4" in response and "5" in response,
            "Suggests reset_index(drop=True) or other valid fix": any(x in response_lower for x in ["reset_index", "drop=true", "iloc", "reindex"]),
            "Provides corrected code": "df[" in response and "=" in response,
            "Explanation is accurate": any(x in response_lower for x in ["dropna", "row mismatch", "length"]),
        }

    # Task 3: Strategy logic
    elif task_id == "task_3_strategy_logic":
        checks = {
            "Identifies potential R:R imbalance as cause": any(x in response_lower for x in ["r:r", "reward:risk", "risk reward", "imbalance"]),
            "Mentions asymmetric stop-loss vs take-profit": any(x in response_lower for x in ["stop loss", "profit target", "tp", "sl"]),
            "Suggests calculating avg win vs avg loss": any(x in response_lower for x in ["avg", "average", "mean"]),
            "Provides Python code to analyze the issue": any(x in response for x in ["df[", "pnl", ".mean(", ".groupby"]),
            "Code is syntactically correct": "import" in response or "df." in response,
            "Diagnostic approach makes sense": "analyze" in response_lower or "where" in response_lower,
        }
    else:
        checks = {}

    for criterion in criteria:
        if checks.get(criterion, False):
            met.append(criterion)

    # Score
    if "ERROR" in response:
        score = 0
    elif len(met) == len(criteria):
        score = 3
    elif len(met) >= len(criteria) * 0.66:
        score = 2
    elif len(met) > 0:
        score = 1
    else:
        score = 0

    return score, met

def run_benchmark():
    """Run benchmark on Claude models"""
    results = {}

    models = [
        ("claude-opus-4-6", "Opus 4.6 (best)"),
        ("claude-sonnet-4-6", "Sonnet 4.6 (balanced)"),
        ("claude-haiku-4-5-20251001", "Haiku 4.5 (fast)"),
    ]

    print("=" * 80)
    print("CLAUDE API BENCHMARK - Real Coding + Trading Tasks")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    for model_id, model_name in models:
        print(f"\nTesting: {model_name}...")
        results[model_name] = {}

        for task_id, task_info in TASKS.items():
            print(f"  {task_info['name']}...", end=" ", flush=True)

            response, elapsed = call_claude(model_id, task_info["prompt"])
            score, met_criteria = evaluate_response(task_id, response)

            print(f"✓ {score}/3 ({elapsed:.1f}s)")

            results[model_name][task_id] = {
                "name": task_info["name"],
                "response": response[:300],
                "score": score,
                "time": elapsed,
                "met": len(met_criteria),
                "total": len(task_info["eval_criteria"]),
            }

    return results

def generate_report(results: Dict) -> str:
    """Generate markdown report"""
    lines = []
    lines.append("# Claude API Benchmark Results")
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("")
    lines.append("## Summary Scores")
    lines.append("")
    lines.append("| Model | Task 1 | Task 2 | Task 3 | Avg |")
    lines.append("|-------|:---:|:---:|:---:|:---:|")

    for model in results:
        task_ids = ["task_1_sql_query", "task_2_bug_fix", "task_3_strategy_logic"]
        scores = [results[model][tid]["score"] for tid in task_ids]
        avg = sum(scores) / len(scores)
        lines.append(f"| {model} | {scores[0]}/3 | {scores[1]}/3 | {scores[2]}/3 | {avg:.1f}/3 |")

    lines.append("")
    lines.append("## Performance (time in seconds)")
    lines.append("")
    lines.append("| Model | Task 1 | Task 2 | Task 3 | Avg |")
    lines.append("|-------|:---:|:---:|:---:|:---:|")

    for model in results:
        task_ids = ["task_1_sql_query", "task_2_bug_fix", "task_3_strategy_logic"]
        times = [results[model][tid]["time"] for tid in task_ids]
        avg = sum(times) / len(times)
        lines.append(f"| {model} | {times[0]:.1f}s | {times[1]:.1f}s | {times[2]:.1f}s | {avg:.1f}s |")

    lines.append("")
    lines.append("## Key Findings")
    lines.append("")

    # Find best model
    avg_scores = {}
    for model in results:
        task_ids = ["task_1_sql_query", "task_2_bug_fix", "task_3_strategy_logic"]
        scores = [results[model][tid]["score"] for tid in task_ids]
        avg_scores[model] = sum(scores) / len(scores)

    best = max(avg_scores, key=avg_scores.get)
    fastest = min(results, key=lambda m: sum([results[m][t]["time"] for t in ["task_1_sql_query", "task_2_bug_fix", "task_3_strategy_logic"]]))

    lines.append(f"✓ **Best overall**: {best} ({avg_scores[best]:.2f}/3)")
    lines.append(f"⚡ **Fastest**: {fastest}")
    lines.append("")
    lines.append("Use Opus 4.6 for complex reasoning and debugging.")
    lines.append("Use Sonnet 4.6 for good balance of speed and quality.")
    lines.append("Use Haiku 4.5 for simple tasks and cron jobs.")

    return "\n".join(lines)

if __name__ == "__main__":
    print("\nRunning benchmark (testing 3 models × 3 tasks)...")
    results = run_benchmark()
    report = generate_report(results)

    # Save
    with open("/home/rob/.openclaw/workspace/brain/claude_benchmark_2026-03-01.md", "w") as f:
        f.write(report)

    print("\n" + "=" * 80)
    print("BENCHMARK COMPLETE")
    print("=" * 80)
    print(f"\nReport saved to: /home/rob/.openclaw/workspace/brain/claude_benchmark_2026-03-01.md\n")
    print(report)
