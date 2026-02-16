#!/usr/bin/env python3
"""AI Workshop precheck: detect new actionable GitHub issues without using LLM.

Exit codes:
  0 = work found (invoke LLM)
  1 = no work (skip LLM, NO_REPLY)
  2 = error

Outputs JSON to stdout ONLY when exit code is 0.

Triggers:
  - Any open issue with the "feedback" label (top priority, always triggers)
  - New ai-task issues not seen before
  - ai-task issues with updated comments since last check
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
            # PID dead → clear immediately; TTL only fallback for alive PID
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


def gh_issue_list(label):
    """Fetch open issues with a given label."""
    result = subprocess.run(
        [
            "gh", "issue", "list", "--repo", REPO,
            "--label", label, "--state", "open",
            "--json", "number,title,updatedAt,labels,comments",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def get_latest_comment_at(comments):
    """Extract the most recent comment timestamp from a comments list."""
    if not comments or not isinstance(comments, list):
        return ""
    latest = ""
    for c in comments:
        ts = ""
        if isinstance(c, dict):
            ts = c.get("updatedAt", c.get("createdAt", ""))
        if ts > latest:
            latest = ts
    return latest


def get_label_names(issue):
    """Extract label names from an issue."""
    labels = issue.get("labels", [])
    if not isinstance(labels, list):
        return []
    return [l.get("name", "") if isinstance(l, dict) else str(l) for l in labels]


def main():
    if not check_lock():
        sys.exit(1)

    acquire_lock()
    try:
        state = load_state()
        known_issues = state.get("issues", {})

        # Fetch ai-task issues (main work queue)
        ai_task_issues = gh_issue_list("ai-task")
        if ai_task_issues is None:
            print("gh CLI failed for ai-task", file=sys.stderr)
            sys.exit(2)

        # Fetch feedback-labeled issues (top priority — always triggers)
        feedback_issues_raw = gh_issue_list("feedback")
        if feedback_issues_raw is None:
            feedback_issues_raw = []

        # Build set of feedback issue numbers for fast lookup
        feedback_numbers = {str(i.get("number", "")) for i in feedback_issues_raw}

        changes = {
            "feedback_issues": [],
            "new_issues": [],
            "updated_issues": [],
        }

        # Any issue with "feedback" label is immediate work — no state comparison needed
        for issue in feedback_issues_raw:
            num = str(issue.get("number", ""))
            if num:
                changes["feedback_issues"].append({
                    "number": int(num),
                    "title": issue.get("title", ""),
                })

        # Check ai-task issues for new/updated (skip those already in feedback)
        new_known = {}
        for issue in ai_task_issues:
            num = str(issue.get("number", ""))
            if not num:
                continue

            updated_at = issue.get("updatedAt", "")
            comments = issue.get("comments", [])
            if not isinstance(comments, list):
                comments = []

            latest_comment_at = get_latest_comment_at(comments)

            new_known[num] = {
                "updated_at": updated_at,
                "latest_comment_at": latest_comment_at,
                "comment_count": len(comments),
            }

            # Skip if already captured as feedback
            if num in feedback_numbers:
                continue

            prev = known_issues.get(num)

            if prev is None:
                changes["new_issues"].append({
                    "number": int(num),
                    "title": issue.get("title", ""),
                })
            else:
                issue_changed = (
                    prev.get("updated_at") != updated_at
                    or prev.get("latest_comment_at", "") != latest_comment_at
                )
                if issue_changed:
                    changes["updated_issues"].append({
                        "number": int(num),
                        "title": issue.get("title", ""),
                    })

        has_work = (
            len(changes["feedback_issues"]) > 0
            or len(changes["new_issues"]) > 0
            or len(changes["updated_issues"]) > 0
        )

        # Update state
        state["issues"] = new_known
        state["last_check_ts"] = int(time.time())
        save_state(state)

        # Always output JSON and exit 0
        result = {"has_work": has_work}
        if has_work:
            result.update(changes)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    finally:
        release_lock()


if __name__ == "__main__":
    main()
