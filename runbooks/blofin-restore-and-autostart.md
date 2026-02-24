# Runbook: Blofin research restore + autostart

## What this restores
- WebSocket market stream monitor
- Pattern event detection (price jump/drop over rolling window)
- Auto-start at login via systemd user service

## Files
- `blofin-research/ws_monitor.py`
- `blofin-research/.env(.example)`
- `blofin-research/systemd/blofin-research.service`
- `scripts/install-blofin-research-service.sh`

## Restore/setup
```bash
cd /home/rob/.openclaw/workspace
chmod +x scripts/install-blofin-research-service.sh
./scripts/install-blofin-research-service.sh
```

## Validate
```bash
systemctl --user status blofin-research.service --no-pager
journalctl --user -u blofin-research.service -f
ls -la /home/rob/.openclaw/workspace/blofin-research/data
```

## Boot auto-start behavior
- Service is enabled with `WantedBy=default.target`.
- It auto-starts when your user session starts after reboot/login.
- If you need start-before-login behavior, enable lingering for user `rob`:
```bash
sudo loginctl enable-linger rob
```

## Tuning
Edit `/home/rob/.openclaw/workspace/blofin-research/.env`:
- `BLOFIN_SYMBOLS`
- `WINDOW_SECONDS`
- `PRICE_JUMP_PCT` / `PRICE_DROP_PCT`

## Notes
- This is a recovery baseline monitor so you can resume operations quickly.
- If you want private-auth channels/order hooks restored too, add API creds and auth flow in a follow-up patch.
