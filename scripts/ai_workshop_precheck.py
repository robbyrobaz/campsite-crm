#!/usr/bin/env python3
"""AI Workshop precheck: detect new actionable GitHub issues without using LLM.

Exit codes:
  0 = work found (invoke LLM)
  1 = no work (skip LLM, NO_REPLY)
  2 = error

Outputs JSON to stdout ONLY when exit code is 0.
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


def fetch_issues():
    """Fetch open ai-task issues with updatedAt and comments list."""
    result = subprocess.run(
        [
            "gh", "issue", "list", "--repo", REPO,
            "--label", "ai-task", "--state", "open",
            "--json", "number,title,updatedAt,comments",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"gh error: {result.stderr}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"JSON parse error: {result.stdout[:200]}", file=sys.stderr)
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


def has_feedback_comments(comments):
    """Check if any comment body has lines starting with //."""
    if not comments or not isinstance(comments, list):
        return False
    for c in comments:
        if isinstance(c, dict):
            body = c.get("body", "")
            if any(line.strip().startswith("//") for line in body.split("\n")):
                return True
    return False


def main():
    if not check_lock():
        sys.exit(1)

    acquire_lock()
    try:
        state = load_state()
        known_issues = state.get("issues", {})

        issues = fetch_issues()
        if issues is None:
            print("gh CLI failed", file=sys.stderr)
            sys.exit(2)

        changes = {
            "new_issues": [],
            "updated_issues": [],
            "feedback_issues": [],
        }

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
            has_feedback = has_feedback_comments(comments)

            new_known[num] = {
                "updated_at": updated_at,
                "latest_comment_at": latest_comment_at,
                "comment_count": len(comments),
            }

            prev = known_issues.get(num)

            if prev is None:
                # New issue
                changes["new_issues"].append({
                    "number": int(num),
                    "title": issue.get("title", ""),
                })
                if has_feedback:
                    changes["feedback_issues"].append({
                        "number": int(num),
                        "feedback_found": True,
                    })
            else:
                # Existing issue — check for updates
                issue_changed = (
                    prev.get("updated_at") != updated_at
                    or prev.get("latest_comment_at", "") != latest_comment_at
                )
                if issue_changed:
                    changes["updated_issues"].append({
                        "number": int(num),
                        "title": issue.get("title", ""),
                    })
                    if has_feedback:
                        changes["feedback_issues"].append({
                            "number": int(num),
                            "feedback_found": True,
                        })

        has_work = (
            len(changes["new_issues"]) > 0
            or len(changes["updated_issues"]) > 0
            or len(changes["feedback_issues"]) > 0
        )

        # Update state
        state["issues"] = new_known
        state["last_check_ts"] = int(time.time())
        save_state(state)

        if has_work:
            print(json.dumps(changes, indent=2))
            sys.exit(0)
        else:
            sys.exit(1)

    finally:
        release_lock()


if __name__ == "__main__":
    main()
