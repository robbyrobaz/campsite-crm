# HEARTBEAT.md - Proactive Health Checks

> **Runtime:** This runs as an **isolated Haiku cron job** (every 2h). It does NOT wake the main Jarvis (Sonnet) session. Update status.json silently when all OK. Only alert via ntfy if something needs attention.

## Server Health (every heartbeat)

- Check CPU temp: `sensors | grep 'Package id 0'` — alert if >85°C
- Check disk usage: `df -h /` — alert if >80%
- Check failed services: `systemctl --user list-units --all --state=failed`
- Check gateway: `systemctl --user is-active openclaw-gateway.service`

## Service Status (every 2nd heartbeat)

- Blofin ingestor: `systemctl --user is-active blofin-stack-ingestor.service`
- Blofin dashboard: `systemctl --user is-active blofin-dashboard.service` (**port 8892** — moved from 8888 Feb 25)
- Blofin paper trading: `systemctl --user is-active blofin-stack-paper.service`
- **Do NOT check** `blofin-stack-api.service` — intentionally removed Feb 18
- **NQ SMB watcher**: `systemctl --user is-active nq-smb-watcher.service`
  - Expected: `active` — this is the live NQ data feed (NinjaTrader SMB bridge → NQ_continuous_1min.csv)
  - If inactive: `systemctl --user start nq-smb-watcher.service` and alert Rob
  - Data staleness during overnight Globex hours (11 PM – 6 AM MST) is NORMAL — NinjaTrader may pause writing
  - Only flag stale data during RTH (6:30 AM – 1 PM MST) or active Globex (6 PM – 11 PM MST)
- **docker-wyze-bridge**: `sudo docker inspect --format='{{.State.Status}}' wyze-bridge 2>/dev/null`
  - Expected: `running`
  - If not running: `cd ~/workspace/wyze-bridge && sudo docker compose up -d` then alert Rob
  - Verify RTSP stream live: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8793/api/camera/front-side-cam/frame` — expect 200
  - If 204 (no frame cached): wyze-bridge lost camera connection — restart container

## Critical Alert Check (EVERY HEARTBEAT)
- Run `/blofin-stack/critical_alert_monitor.py`
- If exit code 1 (alerts found): **ALERT ROB IMMEDIATELY via message**
- Do not wait for next heartbeat — send alert proactively
- Alert must include specific issues found

## Numerai Submission Readiness (EVERY HEARTBEAT)
- Check all 3 model directories exist:
  - `ls -d numerai-tournament/models_elite` (robbyrobml)
  - `ls -d numerai-tournament/models_elite_robbyrob2` (robbyrob2)
  - `ls -d numerai-tournament/models_robbyrob3` (robbyrob3)
- If ANY model dir is missing: **FLAG IMMEDIATELY** — "Numerai model dir missing, daily submission will fail"
- Check `systemctl --user status numerai-daily-bot.service` — if failed, read the journal to find WHY (don't just say "failed, will retry")
- If journal shows FileNotFoundError or model errors: **FIX IT** — train the missing models, don't wait
- After any Numerai retrain card completes: verify ALL 3 model dirs exist and run `multi_model_daily_bot.py --test` dry run

## GCP BTC Dip Trader Check (once daily, morning)

- Run: `PATH="$HOME/google-cloud-sdk/bin:$PATH" gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=btc-dip-trader-job" --limit=5 --format="table(timestamp,textPayload)" --project=ml-trading-431520`
- Verify last run was within 24 hours
- Verify exit code was 0 (look for "Container called exit(0)")
- If last run >24h ago or exit non-zero: **ALERT ROB**

## Periodic Tasks (rotate through, 2-4x daily)

- Check GitHub issues on ai-workshop: any `ai-task` labels queued?
- Check backup timer ran: `systemctl --user status openclaw-full-restore-backup.timer`
- Review recent incident log for unresolved items
- **Git backup hygiene (NON-OPTIONAL) — AUTO-COMMIT ALL DIRTY REPOS:**
  - For ALL active repos, run `git -C <repo> status --short`. If any files are uncommitted:
    - `git -C <repo> add -A && git -C <repo> commit -m "chore: auto-commit $(date +%Y-%m-%d-%H%M)" && git -C <repo> push`
  - Repos to sweep: `blofin-stack`, `blofin-moonshot`, `NQ-Trading-PIPELINE`, `master-dashboard`, `kanban-dashboard`, `numerai-tournament`, `ai-workshop`, `/home/rob/infrastructure/ibkr`
  - Do NOT just flag — actually commit and push. Rob lost a full session of work because auto-commit wasn't wired to project repos.
  - Flag repos with no remote or wrong remote.
  - Ensure lifecycle routing is followed:
    - early/experimental iterations can live in `ai-workshop`
    - mature projects must have their own dedicated repo remote and be pushed there

## Token Usage Check (EVERY HEARTBEAT)
- Read `brain/status/token_usage.md` — report the 5h totals (tokens, requests, top model)
- If 5h output tokens exceed 500K, flag as heavy usage
- This file is updated every 15 min by systemd timer (zero AI cost)

## "Done" Audit (EVERY HEARTBEAT)
- Query `curl -s http://127.0.0.1:8787/api/cards?status=Done` — count total Done cards
- Report the count
- For the 3 most recently completed cards (by updated_at): spot-check that the work was ACTUALLY applied
  - If it's a code change: verify the file exists and has the expected change
  - If it's a DB change: run a quick query to confirm
  - If it's a service change: check `systemctl --user is-active`
- Flag any card where "Done" doesn't match reality

## NQ Pipeline Agent Team Check (EVERY HEARTBEAT while running)
- Check if the Agent Team process is still alive: `ps aux | grep claude | grep -v grep | wc -l`
- If process count drops to 0 or 1 (lead only, no teammates): check if work completed or died
- Check for new files in `/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/pipeline/` and `strategies/`
- If team finished: report what was built, run a quick validation (e.g., `python3 -c "from pipeline import db; print('ok')"`)
- If team died: FLAG immediately

## Active Task Tracking (EVERY HEARTBEAT)

- Read `brain/status/status.json` → check `activeTasks` array
- For each active task, report: id, title, status, how long it's been active
- If any task has been "in-progress" for >30 minutes with no update: **FLAG IT**
- If a subagent sessionKey is listed: check if the session still exists (sessions_list)
- If a subagent session is gone but task still marked active: **FLAG as possibly failed**
- This is NON-OPTIONAL — Rob's #1 complaint is tasks being forgotten

## Kanban Board Check (EVERY HEARTBEAT)
- Query `curl -s http://127.0.0.1:8787/api/cards?status=In%20Progress` — list all In Progress cards
- For each In Progress card: is there a live builder/process working on it? If not, **FLAG IT**
- Query `curl -s http://127.0.0.1:8787/api/cards?status=Planned` — any cards waiting to be picked up?
- If Planned cards exist and no active work is blocking, **FLAG as "work available"**
- Query `curl -s http://127.0.0.1:8787/api/cards?status=Review%2FTest` — any cards waiting for QA?
- If Review/Test cards exist, **FLAG as "QA needed"**

## IBKR Options Pipeline Check (EVERY HEARTBEAT)
- Check service: `systemctl --user is-active ibkr-options.service`
  - Expected: `active` (may show `inactive` before creds added — check if .env has real password)
  - If inactive and .env has real password: restart and alert Rob
- Check IB Gateway container: `sudo docker inspect --format='{{.State.Status}}' ibkr-options-ib-gateway-1 2>/dev/null || echo "not running"`
  - Expected: `running` during market hours setup
  - If not running: `cd ~/infrastructure/ibkr/docker && sudo docker compose up -d`
- Check skew signals (when live): `tail -5 /home/rob/.openclaw/infrastructure/ibkr/data/skew_signals.csv 2>/dev/null || echo "no signals yet"`
- Paper account: mkhhjz078 / DUH860616 — API port 4002
- Weekend/closed market: service will log "market closed" — this is NORMAL, do not alert

## Rules

- If a service is down, restart it and log to incidents.md
- If temp >85°C, check for runaway processes (`top -bn1 | head -15`)
- If disk >80%, check for large files and alert Rob
- Late night (23:00-08:00 MST): only alert Rob for critical issues. Work dispatch continues 24/7 — there is NO quiet mode.
- If nothing needs attention: reply HEARTBEAT_OK
