#!/usr/bin/env python3
"""
Benchmark local LLM models on real Jarvis/trading tasks.
Tests 3 coding/trading tasks against available models and scores them.
"""

import json
import time
import requests
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# Configuration
OLLAMA_API = "http://localhost:11434/api/generate"
RESULTS_FILE = Path("/home/rob/.openclaw/workspace/brain/local_model_benchmark_2026-03-01.md")
RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)

# Test tasks
TASKS = {
    "task1_data_query": {
        "name": "Python Data Query (Blofin style)",
        "prompt": """Write a Python function that queries SQLite table `strategy_coin_performance` and returns the top 10 rows by `ft_profit_factor` where `ft_trades >= 20` and `ft_max_dd < 25`. Return a list of dicts.

Only show the function code, no explanation.""",
        "eval_key": "task1"
    },
    "task2_bug_fix": {
        "name": "Bug Fix (Pandas alignment)",
        "prompt": """I have this broken Python code with a pandas/numpy alignment bug:

```python
import pandas as pd
import numpy as np
df = pd.DataFrame({"a": [1,2,None,4,5]})
df = df.dropna()
preds = np.array([0.1, 0.2, 0.3, 0.4])
df["pred"] = preds  # this fails sometimes — why and how to fix?
```

Identify the bug, explain why it happens, and provide the fix. Keep it concise.""",
        "eval_key": "task2"
    },
    "task3_strategy_diagnosis": {
        "name": "Trading Strategy Diagnosis",
        "prompt": """I have a crypto trading strategy. Win rate is 67% but net PnL is negative (-$230). What are the possible causes and how would you diagnose it in Python?

Given a DataFrame of trades with columns: entry_price, exit_price, side, pnl_pct, sl_pct, tp_pct.

Provide:
1. Top 3 possible causes (be specific)
2. Python code snippet (5-10 lines) to diagnose the issue

Be concise.""",
        "eval_key": "task3"
    }
}

class ModelBenchmark:
    def __init__(self):
        self.results: Dict[str, Dict] = {}

    def get_available_models(self) -> List[str]:
        """Get list of available models from Ollama."""
        try:
            resp = requests.get("http://localhost:11434/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                return [m["name"] for m in models]
            return []
        except Exception as e:
            print(f"Error getting models: {e}")
            return []

    def wait_for_models(self, required_models: List[str], timeout: int = 600):
        """Wait for required models to be available."""
        start = time.time()
        checked = set()

        while time.time() - start < timeout:
            available = self.get_available_models()
            available_names = {m.split(":")[0] for m in available}
            required_names = {m.split(":")[0] for m in required_models}

            new_models = required_names - checked
            if new_models:
                for m in new_models:
                    print(f"✓ {m} is ready")
                    checked.add(m)

            if required_names.issubset(available_names):
                print(f"✓ All models ready in {time.time() - start:.1f}s")
                return True

            time.sleep(5)

        print(f"✗ Timeout waiting for models after {timeout}s")
        return False

    def query_model(self, model: str, prompt: str, timeout: int = 60) -> Tuple[str, float, float]:
        """
        Query a model and return (response, time_to_first_token, total_time).
        Returns None if error.
        """
        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "temperature": 0.1,  # Lower temp for consistency
            }

            start = time.time()
            resp = requests.post(OLLAMA_API, json=payload, timeout=timeout)
            total_time = time.time() - start

            if resp.status_code == 200:
                data = resp.json()
                # For non-streaming, time_to_first_token ≈ total_time
                return data.get("response", ""), 0.0, total_time
            else:
                return None, 0.0, 0.0

        except requests.Timeout:
            print(f"  ✗ Timeout ({timeout}s)")
            return None, 0.0, float(timeout)
        except Exception as e:
            print(f"  ✗ Error: {e}")
            return None, 0.0, 0.0

    def score_task1(self, response: str) -> int:
        """Score Task 1: Data Query. Look for correct SQL/SQLite usage, proper filtering."""
        if not response or response is None:
            return 0

        response_lower = response.lower()

        # Check for critical elements
        has_sqlite = "sqlite" in response_lower or "sql" in response_lower or "select" in response_lower
        has_filter_trades = "trades" in response_lower and ("20" in response or "ft_trades" in response_lower)
        has_filter_dd = "dd" in response_lower or "drawdown" in response_lower or "25" in response
        has_function = "def " in response or "function" in response_lower
        has_list_return = "list" in response_lower or "return" in response_lower

        # Count features
        score = 0
        if has_function:
            score += 1
        if has_sqlite and (has_filter_trades or has_filter_dd):
            score += 1
        if has_list_return:
            score += 1
        if "profit_factor" in response_lower:
            score += 1

        # Cap at 3
        return min(3, score)

    def score_task2(self, response: str) -> int:
        """Score Task 2: Bug Fix. Check for index alignment identification and reset_index."""
        if not response or response is None:
            return 0

        response_lower = response.lower()

        # Check for understanding
        has_index_issue = ("index" in response_lower and "align" in response_lower) or "length mismatch" in response_lower or "shape mismatch" in response_lower
        has_reset = "reset_index" in response or "iloc" in response or "df.values" in response_lower
        has_explanation = "why" in response_lower or "because" in response_lower or "causes" in response_lower

        score = 0
        if has_explanation:
            score += 1
        if has_index_issue:
            score += 1
        if has_reset:
            score += 1

        return min(3, score)

    def score_task3(self, response: str) -> int:
        """Score Task 3: Strategy diagnosis. Check for R:R analysis and diagnostic code."""
        if not response or response is None:
            return 0

        response_lower = response.lower()

        # Check for trading concepts
        has_rr = ("r:" in response_lower or "reward:risk" in response_lower or "ratio" in response_lower) and "profit" in response_lower
        has_win_rate_analysis = ("win rate" in response_lower or "winrate" in response_lower) and "negative" in response_lower
        has_causes = ("loss" in response_lower or "slippage" in response_lower or "spread" in response_lower or "volatility" in response_lower)
        has_code = "pnl" in response_lower and ("groupby" in response_lower or "apply" in response_lower or "sum" in response_lower)

        score = 0
        if has_causes:
            score += 1
        if has_rr or has_win_rate_analysis:
            score += 1
        if has_code:
            score += 1

        return min(3, score)

    def run_benchmark(self, models: List[str]):
        """Run benchmark on all tasks for all models."""
        print(f"\n🚀 Starting benchmark with {len(models)} models on {len(TASKS)} tasks...")

        # Initialize results
        for model in models:
            self.results[model] = {}

        # Run each task
        for task_id, task_info in TASKS.items():
            print(f"\n📋 {task_info['name']}")
            print("=" * 60)

            for model in models:
                print(f"  Testing {model}...", end=" ", flush=True)

                # Query model
                response, ttft, total_time = self.query_model(model, task_info['prompt'], timeout=120)

                # Score response
                if response is None:
                    score = 0
                    print(f"✗ Error (timeout or connection)")
                elif len(response) < 20:
                    score = 0
                    print(f"✗ No response")
                else:
                    # Score based on task type
                    if task_id == "task1_data_query":
                        score = self.score_task1(response)
                    elif task_id == "task2_bug_fix":
                        score = self.score_task2(response)
                    else:  # task3
                        score = self.score_task3(response)

                    print(f"✓ Score: {score}/3 ({total_time:.1f}s)")

                # Store result
                self.results[model][task_id] = {
                    "score": score,
                    "time": round(total_time, 2),
                    "response_len": len(response) if response else 0,
                }

    def write_report(self):
        """Write benchmark results to markdown file."""
        lines = []
        lines.append("# Local Model Benchmark Report")
        lines.append(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Hardware**: RTX 2080 Super 8GB, 31GB RAM")
        lines.append("")

        # Summary table
        lines.append("## Results Summary")
        lines.append("")
        lines.append("| Model | Task 1 | Task 2 | Task 3 | Avg Score |")
        lines.append("|-------|--------|--------|--------|-----------|")

        for model, tasks in self.results.items():
            scores = []
            for task_id in TASKS.keys():
                if task_id in tasks:
                    scores.append(tasks[task_id]["score"])

            task1_score = tasks.get("task1_data_query", {}).get("score", 0)
            task2_score = tasks.get("task2_bug_fix", {}).get("score", 0)
            task3_score = tasks.get("task3_strategy_diagnosis", {}).get("score", 0)
            avg = sum(scores) / len(scores) if scores else 0

            lines.append(f"| {model} | {task1_score}/3 | {task2_score}/3 | {task3_score}/3 | {avg:.2f} |")

        lines.append("")

        # Detailed results
        lines.append("## Detailed Results")
        lines.append("")

        for task_id, task_info in TASKS.items():
            lines.append(f"### {task_info['name']}")
            lines.append("")

            for model, tasks in self.results.items():
                if task_id in tasks:
                    result = tasks[task_id]
                    lines.append(f"**{model}**: Score {result['score']}/3, Time {result['time']}s, Response: {result['response_len']} chars")

            lines.append("")

        # Verdict
        lines.append("## Verdict")
        lines.append("")

        avg_scores = {}
        for model, tasks in self.results.items():
            scores = [tasks[task_id]["score"] for task_id in TASKS.keys() if task_id in tasks]
            avg_scores[model] = sum(scores) / len(scores) if scores else 0

        best_model = max(avg_scores, key=avg_scores.get) if avg_scores else None
        best_score = avg_scores.get(best_model, 0) if best_model else 0

        lines.append(f"**Best model**: {best_model} (avg score: {best_score:.2f}/3)")
        lines.append("")
        lines.append("### Which tasks can go local?")

        for task_id, task_info in TASKS.items():
            scores = [self.results[m][task_id]["score"] for m in self.results if task_id in self.results[m]]
            max_score = max(scores) if scores else 0

            if max_score >= 2:
                lines.append(f"- ✓ {task_info['name']}: Local models score {max_score}/3 → **VIABLE**")
            else:
                lines.append(f"- ✗ {task_info['name']}: Local models score {max_score}/3 → Needs Anthropic")

        lines.append("")
        lines.append("### Cost implications")
        lines.append("- If local models handle 1-2 tasks at 2+/3 score, estimate ~30-50% reduction in Haiku API calls")
        lines.append("- Caveat: Local models slower (5-30s vs <1s for Haiku) → only suitable for async jobs")
        lines.append("")

        # Write file
        with open(RESULTS_FILE, "w") as f:
            f.write("\n".join(lines))

        print(f"\n✅ Report written to {RESULTS_FILE}")


def main():
    benchmark = ModelBenchmark()

    # Wait for models
    print("⏳ Waiting for models to download...")
    models_to_test = ["deepseek-coder-v2:16b", "qwen2.5-coder:14b"]

    if not benchmark.wait_for_models(models_to_test):
        # Try with whatever is available
        available = benchmark.get_available_models()
        if not available:
            print("❌ No models available. Run 'ollama pull deepseek-coder-v2:16b' first.")
            return

        print(f"⚠️ Using available models: {available}")
        models_to_test = available

    # Run benchmark
    benchmark.run_benchmark(models_to_test)

    # Write report
    benchmark.write_report()


if __name__ == "__main__":
    main()
