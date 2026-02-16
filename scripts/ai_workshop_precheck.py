#!/usr/bin/env python3
"""AI Workshop precheck: detect actionable GitHub issues without using LLM.

Exit codes:
  0 = work found (invoke LLM)
  1 = no work (skip LLM, NO_REPLY)
  2 = error

Outputs JSON to stdout ONLY when exit code is 0.

Triggers:
  - Any open issue with the "ai-task" label (new or updated since last check)
"""
import json
import os
import subprocess
import sys
import time

STATE_FILE = os.path.expanduser("~/.openclaw/state/ai-workshop-lastseen.json")
REPO = "robbyrobaz/ai-workshop"
LOCK_FILE = "/tmp/openclaw-ai-workshop.lock"
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


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"issues": {}, "last_check_ts": 0}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_latest_comment_at(comments):
    if not comments or not isinstance(comments, list):
        return ""
    latest = ""
    for c in comments:
        if isinstance(c, dict):
            ts = c.get("updatedAt", c.get("createdAt", ""))
            if ts > latest:
                latest = ts
    return latest


def main():
    if not check_lock():
        sys.exit(1)

    acquire_lock()
    try:
        state = load_state()
        known = state.get("issues", {})

        result = subprocess.run(
            [
                "gh", "issue", "list", "--repo", REPO,
                "--label", "ai-task", "--state", "open",
                "--json", "number,title,updatedAt,labels,comments",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"gh error: {result.stderr}", file=sys.stderr)
            sys.exit(2)

        try:
            issues = json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"JSON parse error: {result.stdout[:200]}", file=sys.stderr)
            sys.exit(2)

        actionable = []
        new_known = {}

        for issue in issues:
            num = str(issue.get("number", ""))
            if not num:
                continue

            updated_at = issue.get("updatedAt", "")
            comments = issue.get("comments", [])
            if not isinstance(comments, list):
                comments = []
            latest_comment_at = get_latest_comment_at(comments)

            # Check if this issue has in-progress label (already being worked on)
            labels = issue.get("labels", [])
            label_names = [l.get("name", "") if isinstance(l, dict) else str(l) for l in labels]
            is_in_progress = "in-progress" in label_names

            new_known[num] = {
                "updated_at": updated_at,
                "latest_comment_at": latest_comment_at,
                "comment_count": len(comments),
            }

            # Skip issues already in-progress (agent is already working on it)
            if is_in_progress:
                continue

            prev = known.get(num)

            if prev is None:
                # New issue
                actionable.append({
                    "number": int(num),
                    "title": issue.get("title", ""),
                    "reason": "new",
                })
            else:
                # Check for updates
                changed = (
                    prev.get("updated_at") != updated_at
                    or prev.get("latest_comment_at", "") != latest_comment_at
                )
                if changed:
                    actionable.append({
                        "number": int(num),
                        "title": issue.get("title", ""),
                        "reason": "updated",
                    })

        # Update state
        state["issues"] = new_known
        state["last_check_ts"] = int(time.time())
        save_state(state)

        # Always exit 0 — cron reads JSON to determine next action
        output = {"actionable_issues": actionable}
        print(json.dumps(output, indent=2))
        sys.exit(0)

    finally:
        release_lock()


if __name__ == "__main__":
    main()
