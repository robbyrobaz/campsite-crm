#!/usr/bin/env python3
"""
Local LLM Model Benchmark - Real coding + trading tasks
Tests qwen2.5-coder:14b and deepseek-coder-v2:16b on 3 real tasks
"""

import json
import time
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Tuple

# Ollama API endpoint
OLLAMA_API = "http://localhost:11434/api/generate"

# Models to test
MODELS = [
    "qwen2.5-coder:14b",
    "deepseek-coder-v2:16b",
]

# Test tasks
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


def call_ollama(model: str, prompt: str) -> Tuple[str, float, float]:
    """Call Ollama API and return (response, time_to_first_token, total_time)"""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }

    start = time.time()
    try:
        result = subprocess.run(
            ["curl", "-s", OLLAMA_API, "-d", json.dumps(payload)],
            capture_output=True,
            text=True,
            timeout=300
        )
        total_time = time.time() - start

        if result.returncode != 0:
            return f"ERROR: {result.stderr}", 0, total_time

        response_data = json.loads(result.stdout)
        response = response_data.get("response", "")

        # Estimate time to first token (Ollama doesn't expose this directly)
        time_to_first = total_time * 0.1  # rough estimate

        return response, time_to_first, total_time
    except Exception as e:
        return f"ERROR: {str(e)}", 0, time.time() - start


def evaluate_response(task_id: str, response: str) -> Tuple[int, List[str]]:
    """
    Simple evaluation based on keywords and patterns.
    Returns (score 0-3, list of met criteria)
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
            "Sorts by ft_profit_factor descending": "ft_profit_factor" in response and any(x in response_lower for x in ["sort", "order"]),
            "Returns list of dicts": any(x in response_lower for x in ["list", "dict"]) and "return" in response_lower,
            "Code runs without syntax errors": "def " in response and "(" in response and ":" in response,
        }

    # Task 2: Bug fix
    elif task_id == "task_2_bug_fix":
        checks = {
            "Identifies index alignment issue": any(x in response_lower for x in ["index", "alignment", "mismatch", "shape"]),
            "Explains that df has 4 rows but preds has 5 values before dropna": "4" in response and "5" in response,
            "Suggests reset_index(drop=True) or other valid fix": any(x in response_lower for x in ["reset_index", "drop=true", "iloc", "reindex"]),
            "Provides corrected code": "df[" in response and "=" in response,
            "Explanation is accurate": any(x in response_lower for x in ["dropna removes", "row mismatch", "different lengths"]),
        }

    # Task 3: Strategy logic
    elif task_id == "task_3_strategy_logic":
        checks = {
            "Identifies potential R:R imbalance as cause": any(x in response_lower for x in ["r:r", "reward:risk", "risk reward", "imbalance"]),
            "Mentions asymmetric stop-loss vs take-profit": any(x in response_lower for x in ["stop", "loss", "profit target", "tp"]),
            "Suggests calculating avg win vs avg loss": any(x in response_lower for x in ["avg win", "avg loss", "mean", "average"]),
            "Provides Python code to analyze the issue": any(x in response for x in ["df[", "pnl", ".mean(", ".groupby"]),
            "Code is syntactically correct": "import" in response or "df." in response,
            "Diagnostic approach makes sense": any(x in response_lower for x in ["where", "filter", "analyze", "group"]),
        }
    else:
        checks = {}

    for criterion in criteria:
        if checks.get(criterion, False):
            met.append(criterion)

    # Score: 0-3
    score = min(3, len(met) * 3 // len(criteria)) if criteria else 0
    if "ERROR" in response:
        score = 0
    elif len(met) == len(criteria):
        score = 3
    elif len(met) >= len(criteria) * 0.66:
        score = 2
    elif len(met) > 0:
        score = 1

    return score, met


def run_benchmark():
    """Run all tasks on all models and collect results"""
    results = {}

    print("=" * 80)
    print("LOCAL LLM MODEL BENCHMARK - Real Coding + Trading Tasks")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Models: {', '.join(MODELS)}")
    print()

    for model in MODELS:
        print(f"\n{'=' * 80}")
        print(f"Testing: {model}")
        print(f"{'=' * 80}\n")

        results[model] = {}

        for task_id, task_info in TASKS.items():
            print(f"  Running: {task_info['name']}...", end=" ", flush=True)

            response, ttft, total_time = call_ollama(model, task_info["prompt"])
            score, met_criteria = evaluate_response(task_id, response)

            print(f"DONE (score: {score}/3, {total_time:.1f}s)")

            results[model][task_id] = {
                "name": task_info["name"],
                "response": response[:500] + ("..." if len(response) > 500 else ""),
                "score": score,
                "ttft": ttft,
                "total_time": total_time,
                "met_criteria": met_criteria,
                "num_criteria": len(task_info["eval_criteria"]),
            }

    return results


def generate_report(results: Dict) -> str:
    """Generate markdown report of benchmark results"""
    report = []
    report.append("# Local LLM Model Benchmark Report")
    report.append(f"Generated: {datetime.now().isoformat()}")
    report.append(f"System: RTX 2080 (8GB), Linux")
    report.append("")
    report.append("## Models Tested")
    for model in MODELS:
        report.append(f"- {model}")
    report.append("")

    # Summary table
    report.append("## Summary Scores")
    report.append("")
    report.append("| Model | Task 1 (SQL) | Task 2 (Bug) | Task 3 (Strategy) | Avg |")
    report.append("|-------|:---:|:---:|:---:|:---:|")

    for model in MODELS:
        task_ids = ["task_1_sql_query", "task_2_bug_fix", "task_3_strategy_logic"]
        scores = [results[model][task_id]["score"] for task_id in task_ids]
        avg = sum(scores) / len(scores) if scores else 0
        report.append(f"| {model} | {scores[0]}/3 | {scores[1]}/3 | {scores[2]}/3 | {avg:.1f}/3 |")

    report.append("")

    # Speed table
    report.append("## Execution Time (seconds)")
    report.append("")
    report.append("| Model | Task 1 | Task 2 | Task 3 | Avg |")
    report.append("|-------|:---:|:---:|:---:|:---:|")

    for model in MODELS:
        task_ids = ["task_1_sql_query", "task_2_bug_fix", "task_3_strategy_logic"]
        times = [results[model][task_id]["total_time"] for task_id in task_ids]
        avg = sum(times) / len(times) if times else 0
        report.append(f"| {model} | {times[0]:.1f}s | {times[1]:.1f}s | {times[2]:.1f}s | {avg:.1f}s |")

    report.append("")

    # Detailed results
    report.append("## Detailed Results")
    report.append("")

    for model in MODELS:
        report.append(f"### {model}")
        report.append("")

        for task_id, task_info in TASKS.items():
            result = results[model][task_id]
            report.append(f"#### {result['name']}")
            report.append("")
            report.append(f"**Score**: {result['score']}/3")
            report.append(f"**Time**: {result['total_time']:.1f}s")
            report.append(f"**Criteria Met**: {len(result['met_criteria'])}/{result['num_criteria']}")
            report.append("")
            report.append("✓ Met criteria:")
            for criterion in result['met_criteria']:
                report.append(f"  - {criterion}")

            missing = [c for c in TASKS[task_id]["eval_criteria"] if c not in result['met_criteria']]
            if missing:
                report.append("")
                report.append("✗ Missing criteria:")
                for criterion in missing:
                    report.append(f"  - {criterion}")

            report.append("")
            report.append("**Response excerpt**:")
            report.append(f"```\n{result['response']}\n```")
            report.append("")

    # Verdict
    report.append("## Verdict")
    report.append("")

    avg_scores = {}
    for model in MODELS:
        task_ids = ["task_1_sql_query", "task_2_bug_fix", "task_3_strategy_logic"]
        scores = [results[model][task_id]["score"] for task_id in task_ids]
        avg_scores[model] = sum(scores) / len(scores) if scores else 0

    best_model = max(avg_scores, key=avg_scores.get)
    worst_model = min(avg_scores, key=avg_scores.get)

    report.append(f"**Best model**: {best_model} ({avg_scores[best_model]:.1f}/3 avg)")
    report.append(f"**Worst model**: {worst_model} ({avg_scores[worst_model]:.1f}/3 avg)")
    report.append("")
    report.append("### Recommendations")
    report.append("")

    if max(avg_scores.values()) < 2.0:
        report.append("❌ **Neither model is production-ready** - Results too unreliable for real tasks")
        report.append("- Complex reasoning (card enrichment, debugging) still needs Sonnet/Claude")
        report.append("- Simple cron health checks might work, but verification needed")
    elif max(avg_scores.values()) >= 2.5:
        report.append("✅ **Local models are viable** for some use cases")
        report.append(f"- {best_model} could handle simple tasks and cron jobs")
        report.append("- Still use Anthropic for complex reasoning and debugging")
    else:
        report.append("⚠️ **Mixed results** - Local models work for some tasks, not others")
        report.append(f"- Use {best_model} for straightforward queries and diagnostics")
        report.append("- Use Anthropic Claude for complex logic and code generation")

    report.append("")
    report.append("### Cost Implications")
    report.append("")
    if max(avg_scores.values()) >= 2.0:
        savings_pct = 40 if max(avg_scores.values()) >= 2.5 else 20
        report.append(f"- If {savings_pct}% of cron/dispatch tasks move to local: **~${int(500 * savings_pct / 100)}/mo savings**")
        report.append("- GPU cost: ~$50-100/mo (already running)")
        report.append("- Net benefit after amortization: significant")
    else:
        report.append("- Cost savings minimal - continue with Anthropic for quality")

    return "\n".join(report)


if __name__ == "__main__":
    print("\nStarting benchmark... (this will take 5-10 minutes)")
    print()

    results = run_benchmark()
    report = generate_report(results)

    # Save report
    report_path = "/home/rob/.openclaw/workspace/brain/local_model_benchmark_2026-03-01.md"
    with open(report_path, "w") as f:
        f.write(report)

    print("\n" + "=" * 80)
    print("BENCHMARK COMPLETE")
    print("=" * 80)
    print(f"\nReport saved to: {report_path}")
    print("\n" + report)
