#!/usr/bin/env python3
"""Blofin strategy review precheck: detect strategies needing changes without LLM.

Exit codes:
  0 = changes needed (invoke LLM)
  1 = no changes (skip LLM, write no-change report)
  2 = error

Outputs JSON to stdout ONLY when exit code is 0.
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

DB_PATH = os.path.expanduser("~/.openclaw/workspace/blofin-stack/data/blofin_monitor.db")
REVIEW_DIR = os.path.expanduser("~/.openclaw/workspace/blofin-stack/data/ai_reviews")
STATE_FILE = os.path.expanduser("~/.openclaw/state/blofin-review-lastseen.json")
LOCK_FILE = "/tmp/openclaw-blofin-review.lock"
LOCK_TTL = 600  # 10 minutes

# Thresholds
MIN_TRADES = 10
DISABLE_SCORE_THRESHOLD = 15
DISABLE_TRADES_THRESHOLD = 20
POOR_WIN_RATE = 0.35
TUNE_CANDIDATE_SCORE_LOW = 15
TUNE_CANDIDATE_SCORE_HIGH = 40

# Hysteresis: don't re-trigger same strategy within this window
COOLDOWN_SECONDS = 12 * 3600  # 12 hours
# Re-trigger despite cooldown if score dropped by this much or trades increased by this much
SCORE_WORSEN_THRESHOLD = 3.0
TRADES_INCREASE_THRESHOLD = 50


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
        return {"strategies": {}}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def should_skip_cooldown(strategy_name, score, trades, state):
    """Check if this strategy was recently reviewed and hasn't worsened materially."""
    prev = state.get("strategies", {}).get(strategy_name)
    if not prev:
        return False  # never reviewed, don't skip

    elapsed = time.time() - prev.get("reviewed_ts", 0)
    if elapsed >= COOLDOWN_SECONDS:
        return False  # cooldown expired, don't skip

    # Within cooldown window — only re-trigger if materially worse
    prev_score = prev.get("score", 999)
    prev_trades = prev.get("trades", 0)

    score_worsened = (prev_score - score) >= SCORE_WORSEN_THRESHOLD
    trades_increased = (trades - prev_trades) >= TRADES_INCREASE_THRESHOLD

    if score_worsened or trades_increased:
        return False  # got worse, don't skip

    return True  # within cooldown, no material change — skip


def mark_reviewed(state, strategy_name, score, trades, action):
    """Record that this strategy was reviewed."""
    if "strategies" not in state:
        state["strategies"] = {}
    state["strategies"][strategy_name] = {
        "reviewed_ts": time.time(),
        "score": score,
        "trades": trades,
        "action": action,
    }


def main():
    if not check_lock():
        print("LOCKED", file=sys.stderr)
        sys.exit(1)

    acquire_lock()
    try:
        if not os.path.exists(DB_PATH):
            print(f"DB not found: {DB_PATH}", file=sys.stderr)
            sys.exit(2)

        state = load_state()
        con = sqlite3.connect(DB_PATH)

        # Get aggregate stats per strategy from the latest scoring run
        cur = con.execute("""
            SELECT s.strategy,
                   MAX(s.enabled) as enabled,
                   AVG(s.score) as avg_score,
                   CAST(SUM(s.wins) AS REAL) / MAX(SUM(s.trades), 1) as overall_win_rate,
                   AVG(s.avg_pnl_pct) as avg_pnl_pct,
                   SUM(s.trades) as total_trades,
                   SUM(s.wins) as total_wins,
                   SUM(s.losses) as total_losses,
                   AVG(s.total_pnl_pct) as avg_total_pnl_pct,
                   AVG(s.sharpe_ratio) as avg_sharpe
            FROM strategy_scores s
            INNER JOIN (
                SELECT strategy, MAX(ts_ms) as max_ts
                FROM strategy_scores
                GROUP BY strategy
            ) latest ON s.strategy = latest.strategy AND s.ts_ms = latest.max_ts
            GROUP BY s.strategy
        """)

        strategies = []
        for row in cur.fetchall():
            strategies.append({
                "strategy": row[0],
                "enabled": bool(row[1]),
                "score": row[2] or 0,
                "win_rate": row[3] or 0,
                "avg_pnl_pct": row[4] or 0,
                "trades": row[5] or 0,
                "wins": row[6] or 0,
                "losses": row[7] or 0,
                "total_pnl_pct": row[8] or 0,
                "sharpe_ratio": row[9] or 0,
            })

        con.close()

        # Determine change candidates with hysteresis
        disable_candidates = []
        tune_candidates = []

        for s in strategies:
            if not s["enabled"]:
                continue

            candidate = None
            action = None

            if s["trades"] >= DISABLE_TRADES_THRESHOLD and s["score"] < DISABLE_SCORE_THRESHOLD:
                candidate = {
                    "strategy": s["strategy"],
                    "reason": f"score={s['score']:.1f}, trades={s['trades']}, win_rate={s['win_rate']:.2f}",
                    "action": "disable",
                }
                action = "disable"
            elif s["trades"] >= MIN_TRADES and s["win_rate"] < POOR_WIN_RATE:
                candidate = {
                    "strategy": s["strategy"],
                    "reason": f"win_rate={s['win_rate']:.2f} < {POOR_WIN_RATE}, trades={s['trades']}",
                    "action": "disable",
                }
                action = "disable"
            elif (s["trades"] >= MIN_TRADES
                  and TUNE_CANDIDATE_SCORE_LOW <= s["score"] < TUNE_CANDIDATE_SCORE_HIGH):
                candidate = {
                    "strategy": s["strategy"],
                    "reason": f"score={s['score']:.1f} (borderline), win_rate={s['win_rate']:.2f}",
                    "action": "tune",
                }
                action = "tune"

            if candidate is None:
                continue

            # Apply hysteresis: skip if recently reviewed and not materially worse
            if should_skip_cooldown(s["strategy"], s["score"], s["trades"], state):
                continue

            if action == "disable":
                disable_candidates.append(candidate)
            else:
                tune_candidates.append(candidate)

        has_changes = len(disable_candidates) > 0 or len(tune_candidates) > 0

        os.makedirs(REVIEW_DIR, exist_ok=True)
        now = datetime.now()
        report_file = os.path.join(REVIEW_DIR, f"precheck-{now.strftime('%Y-%m-%d-%H%M')}.json")

        if has_changes:
            # Mark all triggered candidates as reviewed
            for c in disable_candidates + tune_candidates:
                strat = next((s for s in strategies if s["strategy"] == c["strategy"]), None)
                if strat:
                    mark_reviewed(state, c["strategy"], strat["score"], strat["trades"], c["action"])
            save_state(state)

            result = {
                "timestamp": now.isoformat(),
                "strategies_checked": len(strategies),
                "disable_candidates": disable_candidates,
                "tune_candidates": tune_candidates,
            }
            print(json.dumps(result, indent=2))
            with open(report_file, "w") as f:
                json.dump({**result, "no_changes": False}, f, indent=2)
            sys.exit(0)
        else:
            report = {
                "timestamp": now.isoformat(),
                "no_changes": True,
                "strategies_checked": len(strategies),
                "summary": "All strategies within thresholds or recently reviewed (cooldown)",
            }
            with open(report_file, "w") as f:
                json.dump(report, f, indent=2)
            save_state(state)
            sys.exit(1)

    finally:
        release_lock()


if __name__ == "__main__":
    main()
