# Credentials & Hardware Reference

## Home Energy Dashboard Credentials (jarvis-home-energy/config.py)
- Wyze: KEY_ID=ec0dd323-1db4-4e81-8cd4-a4feab256bae, API_KEY=Fn1phBRix8ifLx0t5f3ktIyVfz2uRBSWdipswwjAiEJ0Z8SIAmVnaCNZLoOL
- Nest SDM project_id=edc12ede-0076-42d4-86d8-c87f49aec4b4, refresh_token saved in config.py
- 3 Wyze cameras: Front Side (D03F275A9799), Upstairs (2CAA8E813AE9), Downstairs (2CAA8E813B36)
- 2 Nest thermostats: Downstairs + Loft upstairs (both COOLING)
- wyze-sdk 2.2.0 has NO snapshot method — cameras show status only, no live feed
- Ring invite: jarvis.is.my.coo@gmail.com — 14-day window (received Feb 23 9:50 PM)

## Camera Setup (Feb 25, 2026)
- **Upstairs Cam** (2CAA8E813AE9, 192.168.68.51): direct RTSP `rtsp://Camera:Feed@192.168.68.51/live`
- **Downstairs Cam** (2CAA8E813B36, 192.168.68.82): direct RTSP `rtsp://Camera:Feed@192.168.68.82/live`
- **Front Side Cam** (D03F275A9799, 192.168.68.76): newer firmware blocks RTSP → uses **docker-wyze-bridge**
  - wyze-bridge RTSP: `rtsp://127.0.0.1:8554/front-side-cam`
  - docker-wyze-bridge v2.10.3, host network mode, compose at `workspace/wyze-bridge/docker-compose.yml`
  - Creds in `wyze-bridge/.env` (single-quoted password for $ and # chars)
- **Frame serving**: background ffmpeg threads per camera → cache latest JPEG → `/api/camera/<id>/frame` responds in ~11ms
- **JS polling**: 500ms refresh per camera via `_camRefreshTimers`; `_getRtspId()` maps cam name → stream id
- **Blofin dashboard moved** to port 8892 (was 8888) to free port 8888 for wyze-bridge mediamtx

## Tesla Fleet API Token Refresh (Feb 25, 2026)
- Cache file: `jarvis-home-energy/tesla_cache.json` — tokens under `["rob.hartwig@gmail.com"]["sso"]`
- teslapy's own `.refresh_token()` returns 404 — do NOT use it
- **Working refresh**: `POST https://auth.tesla.com/oauth2/v3/token` with `{grant_type, client_id:"ownerapi", refresh_token, scope}`
- Token expires every 8 hours — `_get_tesla_fleet_token()` in app.py auto-refreshes 5 min before expiry
- Fleet API base: `https://owner-api.teslamotors.com/api/1/energy_sites/2252397277512276/`
- Key endpoint: `/live_status` → solar_power, battery_power, grid_power, load_power, grid_status
