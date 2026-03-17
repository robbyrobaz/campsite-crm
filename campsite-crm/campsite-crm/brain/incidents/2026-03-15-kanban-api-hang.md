# Incident: Kanban Dashboard API Unresponsive
**Date:** 2026-03-15 10:35 MST  
**Severity:** Critical  
**Status:** Open  

## Summary
Kanban dashboard API (port 8787) is hanging on all requests. Process is running but not responding.

## Details
- Process PID 27699 running manually (no systemd service)
- All curl requests to http://127.0.0.1:8787/api/* timeout
- Tried: /api/cards?status=Failed, Done, In Progress, Planned — all hang
- Health endpoint also unresponsive

## Impact
- Cannot audit Failed cards for auto-retry
- Cannot verify Done card deployments
- Cannot check Planned work queue
- Dispatcher (Jarvis Pulse) likely blocked
- Heartbeat checks incomplete

## Next Steps
1. Rob to kill PID 27699 and restart
2. Consider creating systemd service for kanban-dashboard
3. Add health check endpoint timeout to future heartbeats

## Resolution
(pending)
