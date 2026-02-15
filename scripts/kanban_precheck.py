#!/usr/bin/env python3
"""Kanban autocoder precheck: detect actionable tasks without using LLM.

Exit codes:
  0 = work found (invoke LLM)
  1 = no work (skip LLM, NO_REPLY)
  2 = error

Outputs JSON to stdout with task details when exit code is 0.
"""
import json
import os
import sqlite3
import sys
import time

DB_PATH = os.path.expanduser("~/.openclaw/workspace/blofin-stack/data/blofin_monitor.db")
LOCK_FILE = "/tmp/openclaw-kanban.lock"
LOCK_TTL = 900  # 15 minutes


def check_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                data = json.load(f)
            pid = data.get("pid", 0)
            ts = data.get("ts", 0)
            if pid and os.path.exists(f"/proc/{pid}"):
                if time.time() - ts < LOCK_TTL:
                    return False
            os.unlink(LOCK_FILE)
        except (json.JSONDecodeError, OSError):
            try:
                os.unlink(LOCK_FILE)
            except OSError:
                pass
    return True


def acquire_lock():
    with open(LOCK_FILE, "w") as f:
        json.dump({"pid": os.getpid(), "ts": time.time()}, f)


def release_lock():
    try:
        os.unlink(LOCK_FILE)
    except OSError:
        pass


def main():
    if not check_lock():
        print("LOCKED", file=sys.stderr)
        sys.exit(1)

    acquire_lock()
    try:
        if not os.path.exists(DB_PATH):
            print(f"DB not found: {DB_PATH}", file=sys.stderr)
            sys.exit(2)

        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row

        # Check for in_progress tasks
        cur = con.execute(
            "SELECT id, title, priority, status FROM kanban_tasks WHERE status = 'in_progress' ORDER BY priority DESC LIMIT 1"
        )
        in_progress = cur.fetchone()

        # Check for inbox tasks that could be promoted
        cur = con.execute(
            "SELECT id, title, priority, status FROM kanban_tasks WHERE status = 'inbox' ORDER BY priority DESC LIMIT 1"
        )
        inbox = cur.fetchone()

        con.close()

        if in_progress:
            result = {
                "action": "continue",
                "task": {
                    "id": in_progress["id"],
                    "title": in_progress["title"],
                    "priority": in_progress["priority"],
                    "status": in_progress["status"],
                },
            }
            print(json.dumps(result, indent=2))
            sys.exit(0)
        elif inbox:
            result = {
                "action": "promote",
                "task": {
                    "id": inbox["id"],
                    "title": inbox["title"],
                    "priority": inbox["priority"],
                    "status": inbox["status"],
                },
            }
            print(json.dumps(result, indent=2))
            sys.exit(0)
        else:
            sys.exit(1)

    finally:
        release_lock()


if __name__ == "__main__":
    main()
