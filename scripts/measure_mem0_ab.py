#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4


ROOT = Path("/home/rob/.openclaw/workspace")
CONFIG_PATH = Path("/home/rob/.openclaw/openclaw.json")
STORE_PATH = Path("/home/rob/.mem0-local/memories.json")
REPORTS_DIR = ROOT / "research" / "mem0_ab"
MODEL = "openai-codex/gpt-5.4"
AGENT = "nq"
LOG_CMD = r"rg -n 'openclaw-mem0: (auto-captured|injecting [0-9]+ memories into context)' /tmp/openclaw/openclaw-$(date +%F).log | tail -n 40"


def run(cmd, check=True, capture=True):
    result = subprocess.run(
        cmd,
        shell=True,
        text=True,
        capture_output=capture,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {cmd}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def gateway_call(method, params, expect_final=False, timeout=120000):
    params_json = json.dumps(params, separators=(",", ":"))
    cmd = f"openclaw gateway call {method} --json --timeout {timeout} --params '{params_json}'"
    if expect_final:
        cmd = f"openclaw gateway call {method} --expect-final --json --timeout {timeout} --params '{params_json}'"
    result = run(cmd)
    text = result.stdout.strip()
    if text.startswith("Config warnings:"):
        idx = text.find("{")
        if idx == -1:
            raise RuntimeError(f"unexpected gateway output:\n{text}")
        text = text[idx:]
    return json.loads(text)


def load_config():
    return json.loads(CONFIG_PATH.read_text())


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


def set_memory_mode(enabled):
    cfg = load_config()
    mem_cfg = cfg["plugins"]["entries"]["openclaw-mem0"]["config"]
    mem_cfg["autoCapture"] = enabled
    mem_cfg["autoRecall"] = enabled
    save_config(cfg)


def restart_gateway():
    run("systemctl --user restart openclaw-gateway.service")
    deadline = time.time() + 60
    while time.time() < deadline:
        status = run("systemctl --user is-active openclaw-gateway.service", check=False)
        if status.stdout.strip() == "active":
            health = run("openclaw health", check=False)
            if health.returncode == 0:
                return
        time.sleep(1)
    raise RuntimeError("gateway did not come back healthy in time")


def ensure_store():
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        STORE_PATH.write_text("[]\n")


def clear_store():
    ensure_store()
    STORE_PATH.write_text("[]\n")


def count_store_records():
    ensure_store()
    return len(json.loads(STORE_PATH.read_text()))


def store_records_for_user(user_id):
    ensure_store()
    data = json.loads(STORE_PATH.read_text())
    return [row for row in data if row.get("user_id") == user_id]


def patch_session(key, model=MODEL):
    return gateway_call("sessions.patch", {"key": key, "model": model})


def send_message(key, message):
    idem = str(uuid4())
    return gateway_call(
        "chat.send",
        {"sessionKey": key, "message": message, "idempotencyKey": idem},
        expect_final=False,
        timeout=30000,
    )


def get_session_entry(key):
    payload = gateway_call("sessions.list", {"limit": 500}, timeout=10000)
    for entry in payload.get("sessions", []):
        if entry.get("key") == key:
            return entry
    return None


def wait_for_done(key, timeout_s=180):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        entry = get_session_entry(key)
        if entry and entry.get("status") == "done":
            return entry
        time.sleep(1)
    raise RuntimeError(f"session did not finish: {key}")


def get_history(key, limit=20):
    return gateway_call("chat.history", {"sessionKey": key, "limit": limit}, timeout=10000)


def extract_assistant_text(history):
    parts = []
    for msg in history.get("messages", []):
        if msg.get("role") != "assistant":
            continue
        for part in msg.get("content", []):
            if part.get("type") == "text":
                parts.append(part.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def injected_memory_text(history):
    for msg in history.get("messages", []):
        if msg.get("role") != "user":
            continue
        for part in msg.get("content", []):
            text = part.get("text", "")
            if text.startswith("<relevant-memories>"):
                return text
    return ""


def wait_for_store_growth(before_count, timeout_s=60):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        count = count_store_records()
        if count > before_count:
            return count
        time.sleep(1)
    raise RuntimeError("memory store did not grow in time")


def latest_mem_log():
    return run(LOG_CMD, check=False).stdout.strip()


def build_fixture():
    marker = f"MEM0-AB-{uuid4().hex[:8].upper()}"
    facts = [
        f"benchmark marker: {marker}",
        "codename: Quartz Falcon",
        "risk budget: 1.75%",
        "preferred broker: IBKR paper",
        "exit model: dynamic trail 7.5 initial and 0.75 floor",
        "deployment window: 14:35 MST",
    ]
    full_context = (
        "Store this benchmark fixture exactly for a later follow-up.\n"
        + "\n".join(f"- {fact}" for fact in facts)
        + "\nReply with exactly: STORED"
    )
    follow_question = (
        f"For benchmark marker {marker}, list the six stored facts as six bullets and nothing else."
    )
    repeated_context_question = (
        "Use this benchmark fixture to answer the question.\n"
        + "\n".join(f"- {fact}" for fact in facts)
        + f"\nQuestion: For benchmark marker {marker}, list the six stored facts as six bullets and nothing else."
    )
    return {
        "marker": marker,
        "facts": facts,
        "seed_prompt": full_context,
        "follow_with_memory": follow_question,
        "follow_without_memory": repeated_context_question,
    }


def run_arm(name, memory_enabled, fixture):
    set_memory_mode(memory_enabled)
    clear_store()
    restart_gateway()

    seed_key = f"agent:{AGENT}:ab-{name}:seed:{int(time.time())}"
    follow_key = f"agent:{AGENT}:ab-{name}:follow:{int(time.time())}"

    patch_session(seed_key)
    before_seed_store = count_store_records()
    send_message(seed_key, fixture["seed_prompt"])
    seed_entry = wait_for_done(seed_key)
    seed_history = get_history(seed_key)
    seed_answer = extract_assistant_text(seed_history)

    if memory_enabled:
        wait_for_store_growth(before_seed_store)

    patch_session(follow_key)
    follow_prompt = fixture["follow_with_memory"] if memory_enabled else fixture["follow_without_memory"]
    send_message(follow_key, follow_prompt)
    follow_entry = wait_for_done(follow_key)
    follow_history = get_history(follow_key)
    follow_answer = extract_assistant_text(follow_history)
    injected = injected_memory_text(follow_history)

    return {
        "memory_enabled": memory_enabled,
        "seed_key": seed_key,
        "follow_key": follow_key,
        "seed_usage": {
            "inputTokens": seed_entry.get("inputTokens"),
            "outputTokens": seed_entry.get("outputTokens"),
            "totalTokens": seed_entry.get("totalTokens"),
            "estimatedCostUsd": seed_entry.get("estimatedCostUsd"),
            "model": seed_entry.get("model"),
            "modelProvider": seed_entry.get("modelProvider"),
        },
        "follow_usage": {
            "inputTokens": follow_entry.get("inputTokens"),
            "outputTokens": follow_entry.get("outputTokens"),
            "totalTokens": follow_entry.get("totalTokens"),
            "estimatedCostUsd": follow_entry.get("estimatedCostUsd"),
            "model": follow_entry.get("model"),
            "modelProvider": follow_entry.get("modelProvider"),
        },
        "seed_answer": seed_answer,
        "follow_answer": follow_answer,
        "follow_prompt_chars": len(follow_prompt),
        "injected_memory_chars": len(injected),
        "store_records_for_nq": len(store_records_for_user("jarvis-main:agent:nq")),
        "mem_log_tail": latest_mem_log(),
    }


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = REPORTS_DIR / f"mem0_ab_report_{timestamp}.json"

    original_cfg = CONFIG_PATH.read_text()
    original_store = STORE_PATH.read_text() if STORE_PATH.exists() else None

    fixture = build_fixture()
    report = {
        "createdAt": datetime.now().isoformat(),
        "agent": AGENT,
        "model": MODEL,
        "fixture": fixture,
    }
    try:
        baseline = run_arm("nomem", memory_enabled=False, fixture=fixture)
        memory = run_arm("withmem", memory_enabled=True, fixture=fixture)
        report["baseline"] = baseline
        report["with_memory"] = memory
        report["comparison"] = {
            "follow_input_token_delta": (memory["follow_usage"]["inputTokens"] or 0) - (baseline["follow_usage"]["inputTokens"] or 0),
            "workflow_total_token_delta": ((memory["seed_usage"]["totalTokens"] or 0) + (memory["follow_usage"]["totalTokens"] or 0)) - ((baseline["seed_usage"]["totalTokens"] or 0) + (baseline["follow_usage"]["totalTokens"] or 0)),
            "workflow_cost_delta_usd": round(((memory["seed_usage"]["estimatedCostUsd"] or 0) + (memory["follow_usage"]["estimatedCostUsd"] or 0)) - ((baseline["seed_usage"]["estimatedCostUsd"] or 0) + (baseline["follow_usage"]["estimatedCostUsd"] or 0)), 6),
        }
    finally:
        CONFIG_PATH.write_text(original_cfg)
        if original_store is None:
            if STORE_PATH.exists():
                STORE_PATH.unlink()
        else:
            STORE_PATH.write_text(original_store)
        restart_gateway()

    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"\nWrote report to {report_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
