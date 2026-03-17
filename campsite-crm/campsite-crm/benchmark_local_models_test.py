#!/usr/bin/env python3
"""
Benchmark local LLM models on coding and trading tasks.
Tests: data query, bug fix, strategy diagnosis.
Metrics: correctness (0-3), speed, usability.
"""

import requests
import time
import json
from datetime import datetime
import sys

OLLAMA_URL = "http://localhost:11434/api/generate"

TASKS = {
    "task_1_data_query": {
        "name": "Data Query (SQLite)",
        "prompt": """Write a Python function that queries a SQLite table `strategy_coin_performance` and returns the top 10 rows by `ft_profit_factor` where `ft_trades >= 20` and `ft_max_dd < 25`. Return a list of dicts.

Requirements:
- Function should connect to SQLite
- Query the table and filter by conditions
- Sort by profit_factor descending
- Return results as list of dicts""",
    },
    "task_2_bug_fix": {
        "name": "Bug Fix (Pandas Alignment)",
        "prompt": """Fix this Python code and explain the issue:

```python
import pandas as pd
import numpy as np
df = pd.DataFrame({"a": [1,2,None,4,5]})
df = df.dropna()
preds = np.array([0.1, 0.2, 0.3, 0.4])
df["pred"] = preds  # this fails sometimes — why and how to fix?
```

Explain why the assignment fails, what the index issue is, and provide the corrected code.""",
    },
    "task_3_strategy_diagnosis": {
        "name": "Strategy Diagnosis (Trading)",
        "prompt": """I have a crypto trading strategy. Win rate is 67% but net PnL is negative (-$230). What are the possible causes and how would you diagnose it in Python?

Given a DataFrame of trades with columns: entry_price, exit_price, side, pnl_pct, sl_pct, tp_pct

Provide:
1. List of 3-5 possible root causes (focus on risk:reward issues)
2. Python code to diagnose each cause given the DataFrame
3. How to visualize or summarize findings""",
    },
}


def run_model_task(model_name, task_key, task_data):
    """Run a model on a single task. Return results with timing."""
    print(f"  Testing {model_name} on {task_key}...", flush=True)

    payload = {
        "model": model_name,
        "prompt": task_data["prompt"],
        "stream": False,
        "options": {
            "num_predict": 2048,
            "temperature": 0.3,
        }
    }

    start = time.time()
    first_token_time = None

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=180)
        first_token_time = time.time() - start

        if response.status_code != 200:
            return {
                "model": model_name,
                "task": task_key,
                "status": "error",
                "error": f"HTTP {response.status_code}",
                "total_time": time.time() - start,
                "first_token_time": None,
            }

        data = response.json()
        total_time = time.time() - start

        return {
            "model": model_name,
            "task": task_key,
            "status": "success",
            "response": data.get("response", ""),
            "total_time": total_time,
            "first_token_time": first_token_time,
            "eval_tokens": data.get("eval_count", 0),
            "prompt_tokens": data.get("prompt_eval_count", 0),
        }
    except requests.exceptions.Timeout:
        return {
            "model": model_name,
            "task": task_key,
            "status": "timeout",
            "total_time": time.time() - start,
            "first_token_time": first_token_time,
        }
    except Exception as e:
        return {
            "model": model_name,
            "task": task_key,
            "status": "error",
            "error": str(e),
            "total_time": time.time() - start,
            "first_token_time": first_token_time,
        }


def check_models_ready(models):
    """Check which models are available and ready."""
    print("Checking available models...")
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            available = [m["name"] for m in response.json().get("models", [])]
            print(f"  Available models: {available}")
            return [m for m in models if m in available]
    except Exception as e:
        print(f"  Error checking models: {e}")
    return []


def main():
    # Models to test (in order of preference)
    models_to_test = [
        "qwen2.5-coder:7b",
        "deepseek-coder-v2:16b",
        "llama2:7b",
        "llama2:13b",
    ]

    print("=" * 80)
    print("LOCAL LLM BENCHMARK - March 1, 2026")
    print("=" * 80)
    print(f"Start time: {datetime.now().isoformat()}")
    print(f"Hardware: RTX 2080 8GB, 31GB RAM")
    print()

    # Wait for models to be ready
    ready_models = []
    max_attempts = 10
    for attempt in range(max_attempts):
        ready_models = check_models_ready(models_to_test)
        if ready_models:
            break
        if attempt < max_attempts - 1:
            print(f"  Attempt {attempt + 1}: Waiting for models (next check in 10s)...")
            time.sleep(10)

    if not ready_models:
        print("\nERROR: No models available after waiting.")
        print("You can manually pull models with:")
        print("  ollama pull qwen2.5-coder:7b")
        print("  ollama pull deepseek-coder-v2:16b")
        return

    print(f"\n✓ Ready to test: {', '.join(ready_models)}\n")

    # Run benchmarks
    results = []

    for model in ready_models:
        print(f"Testing model: {model}")
        print("-" * 60)

        for task_key, task_data in TASKS.items():
            result = run_model_task(model, task_key, task_data)
            results.append(result)

            # Print quick result
            status = result["status"]
            if status == "success":
                response_len = len(result["response"])
                time_taken = result["total_time"]
                print(f"    ✓ {task_data['name']}: {time_taken:.1f}s ({response_len} chars)")
            else:
                print(f"    ✗ {task_data['name']}: {status}")

        print()

    # Save results
    output_file = "/home/rob/.openclaw/workspace/brain/local_model_benchmark_2026-03-01.json"
    print(f"Saving results to: {output_file}")

    with open(output_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "hardware": "RTX 2080 8GB, 31GB RAM",
            "models_tested": ready_models,
            "tasks": {k: {"name": v["name"], "prompt": v["prompt"]} for k, v in TASKS.items()},
            "results": results,
        }, f, indent=2, default=str)

    print("✓ Benchmark complete!")


if __name__ == "__main__":
    main()
