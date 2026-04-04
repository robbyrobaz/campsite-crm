#!/usr/bin/env python3
"""
Jarvis Home Energy OS — Unified Home Energy Dashboard
Covers: SPAN Panel · Enphase Solar · Pentair Pool · Tesla Energy Gateway 3V · Tesla Wall Connector Gen 3
"""

import json
import os
import logging
import socket
import ssl
import threading
import time
import uuid
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path
import requests as _requests
import teslapy
from flask import Flask, Response, jsonify, render_template_string, request, stream_with_context, make_response
from energy_analytics import (
    init_db, log_telemetry, compute_hourly_aggregates, compute_daily_aggregates,
    get_usage_patterns, calculate_powerwall_roi, get_recent_daily_trends
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("jarvis")

# ── Config ────────────────────────────────────────────────────────────────────
try:
    from config import (
        SPAN_HOST, SPAN_TOKEN,
        ENPHASE_HOST, ENPHASE_SERIAL, ENPHASE_TOKEN, ENPHASE_EMAIL, ENPHASE_PASSWORD,
        PENTAIR_HOST, PENTAIR_PORT,
        TESLA_WC_HOST,
        TESLA_HOST, TESLA_EMAIL, TESLA_PASSWORD,
        DASHBOARD_PORT, POLL_INTERVAL_SECONDS,
        TESLA_ENERGY_SITE_ID,
    )
except ImportError:
    SPAN_HOST = "192.168.68.93"; SPAN_TOKEN = ""
    ENPHASE_HOST = "192.168.68.63"; ENPHASE_SERIAL = "202324023651"
    ENPHASE_TOKEN = ""; ENPHASE_EMAIL = ""; ENPHASE_PASSWORD = ""
    PENTAIR_HOST = "192.168.68.89"; PENTAIR_PORT = 6681
    TESLA_WC_HOST = "192.168.68.87"
    TESLA_HOST = ""; TESLA_EMAIL = ""; TESLA_PASSWORD = ""
    DASHBOARD_PORT = 8793; POLL_INTERVAL_SECONDS = 5
    TESLA_ENERGY_SITE_ID = 2252397277512276

# New smart-home integrations — graceful fallback if not yet in config
try:
    from config import WYZE_EMAIL, WYZE_PASSWORD, WYZE_API_KEY, WYZE_KEY_ID
except ImportError:
    WYZE_EMAIL = ""; WYZE_PASSWORD = ""; WYZE_API_KEY = ""; WYZE_KEY_ID = ""
try:
    from config import RING_EMAIL, RING_PASSWORD
except ImportError:
    RING_EMAIL = ""; RING_PASSWORD = ""
try:
    from config import NEST_CLIENT_ID, NEST_CLIENT_SECRET, NEST_REFRESH_TOKEN, NEST_PROJECT_ID
    NEST_ACCESS_TOKEN = ""  # refreshed at runtime
except ImportError:
    NEST_CLIENT_ID = ""; NEST_CLIENT_SECRET = ""; NEST_REFRESH_TOKEN = ""; NEST_PROJECT_ID = ""
    NEST_ACCESS_TOKEN = ""

# Cached SDM access token (expires in 1h — auto-refreshed)
_nest_access_token = ""
_nest_token_expiry = 0.0
_nest_token_lock = threading.Lock()

def _get_nest_access_token():
    """Return a valid SDM access token, refreshing if expired."""
    global _nest_access_token, _nest_token_expiry
    if not NEST_REFRESH_TOKEN:
        return None
    with _nest_token_lock:
        if _nest_access_token and time.time() < _nest_token_expiry - 60:
            return _nest_access_token
        try:
            import urllib.request, urllib.parse
            data = urllib.parse.urlencode({
                "client_id": NEST_CLIENT_ID,
                "client_secret": NEST_CLIENT_SECRET,
                "refresh_token": NEST_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            }).encode()
            req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
            _nest_access_token = resp["access_token"]
            _nest_token_expiry = time.time() + resp.get("expires_in", 3600)
            log.info("Nest SDM token refreshed OK")
            return _nest_access_token
        except Exception as e:
            log.warning("Nest token refresh error: %s", e)
            return None
try:
    from config import BHYVE_EMAIL, BHYVE_PASSWORD
except ImportError:
    BHYVE_EMAIL = ""; BHYVE_PASSWORD = ""
try:
    from config import GE_CLIENT_ID, GE_CLIENT_SECRET, GE_REFRESH_TOKEN
except ImportError:
    GE_CLIENT_ID = ""; GE_CLIENT_SECRET = ""; GE_REFRESH_TOKEN = ""
try:
    from config import MYQ_EMAIL, MYQ_PASSWORD
except ImportError:
    MYQ_EMAIL = ""; MYQ_PASSWORD = ""

app = Flask(__name__, static_folder='static', static_url_path='/static')

# ── Shared State ──────────────────────────────────────────────────────────────
_state_lock = threading.Lock()
_state = {
    "ts": 0,
    "span": {"status": "unconfigured", "door": "?", "uptime": 0, "grid_power": 0, "circuits": [], "last_seen": 0},
    "enphase": {"status": "unconfigured", "production_w": 0, "consumption_w": 0, "net_w": 0, "firmware": "D8.3.5167", "last_seen": 0},
    "pentair": {"status": "offline", "pool": {}, "spa": {}, "pump": {}, "heater": {}, "circuits": [], "last_seen": 0},
    "tesla": {"status": "unconfigured", "soe": 0, "solar_w": 0, "battery_w": 0, "grid_w": 0, "load_w": 0, "last_seen": 0},
    "wall_connector": {"status": "unconfigured", "vehicle_connected": False, "charging_w": 0, "session_energy_wh": 0, "grid_v": 0, "pcba_temp_c": 0, "last_seen": 0},
    "summary": {"solar_w": 0, "load_w": 0, "battery_w": 0, "grid_w": 0, "net_savings_today": 0},
    "cameras": [],  # list of {name, mac, type, status, last_seen, last_motion, snapshot_path}
    "nest": {"status": "unconfigured", "temp_f": 0, "setpoint_f": 0, "mode": "off", "hvac_state": "idle", "humidity": 0, "last_seen": 0},
    "bhyve": {"status": "unconfigured", "devices": [], "zones": [], "last_seen": 0},
    "ge_appliances": {"status": "unconfigured", "appliances": [], "last_seen": 0},
    "myq": {"status": "unconfigured", "doors": [], "last_seen": 0},
    "roku": [],
}
_sse_subscribers = []
_sse_lock = threading.Lock()

# Wyze — single cached client (login once, reuse across polls + snapshots)
_wyze_client = None
_wyze_client_lock = threading.Lock()
_wyze_next_retry = 0   # epoch seconds — don't retry auth before this time
_camera_poll_counter = 0  # throttle: refresh camera list every 60s (every 12 ticks at 5s)
_ge_poll_counter = 0      # throttle: poll GE appliances every 30s
_telemetry_log_counter = 0  # throttle: log telemetry every 60s (every 12 ticks at 5s)
_daily_agg_counter = 0    # throttle: compute daily aggregates every 24h (every 17280 ticks at 5s)

# Ring — cached token data (persisted across calls to avoid repeated re-auth)
# ring_doorbell 0.9.x is fully async; we wrap with a fresh event loop
_RING_TOKEN_FILE = os.path.join(os.path.dirname(__file__), "ring_token.json")
def _ring_load_token():
    try:
        with open(_RING_TOKEN_FILE) as f:
            return json.load(f)
    except Exception:
        return {}
_ring_token_data = _ring_load_token()
_ring_next_retry = 0
_ring_lock = threading.Lock()


def _ring_token_updater(token_data):
    global _ring_token_data
    _ring_token_data = token_data
    try:
        with open(_RING_TOKEN_FILE, "w") as f:
            json.dump(token_data, f)
    except Exception:
        pass


def _run_async(coro):
    """Run an async coroutine synchronously in a fresh event loop (thread-safe)."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _ring_build(update=True):
    """Authenticate with Ring and optionally fetch device data.
    NOTE: Ring's /clients_api/session endpoint returns 406 ext_authz_denied for
    programmatic clients; we bypass it by injecting a dummy session so that
    async_update_devices() and the history/health endpoints still work.
    Snapshots (which need a valid session) are attempted but may not work.
    """
    from ring_doorbell import Ring, Auth
    auth = Auth("JarvisHomeEnergy/1.0", _ring_token_data or None, _ring_token_updater)
    if not _ring_token_data:
        await auth.async_fetch_token(RING_EMAIL, RING_PASSWORD)
    ring = Ring(auth)
    # Bypass async_create_session() — Ring blocks this endpoint for third-party clients.
    # Other endpoints (devices, history, health) still work with just the OAuth token.
    ring.session = {"profile": {"id": 0}}
    if update:
        await ring.async_update_devices()
    return ring


async def _ring_poll_cameras_async():
    """Async: return list of camera dicts from Ring."""
    ring = await _ring_build(update=True)
    cameras = []
    for device in ring.video_devices():
        last_motion = ""
        try:
            hist = device.last_history
            if hist:
                last_motion = str(hist[0].get("created_at", ""))
        except Exception:
            pass
        cameras.append({
            "name": device.name or "Ring Doorbell",
            "mac": str(getattr(device, 'id', 'ring')),
            "type": "ring",
            "status": "online" if getattr(device, 'subscribed', False) else "offline",
            "last_motion": last_motion,
            "snapshot_path": f"/api/camera/ring_{getattr(device, 'id', '0')}/snapshot",
            "thumbnail_url": "",
        })
    return cameras


async def _ring_get_snapshot_async(device_id):
    """Async: return raw JPEG bytes for a Ring doorbell, or None."""
    ring = await _ring_build(update=True)
    for device in ring.video_devices():
        if str(getattr(device, 'id', '')) == device_id:
            return await device.async_get_snapshot()
    return None


# ── Ring snapshot & event background state ────────────────────────────────────
_ring_snap_bytes: bytes = b''
_ring_snap_lock  = threading.Lock()
_ring_snap_age: float = 0.0

_ring_evts: list = []          # [{ts, type, device}] — most recent events
_ring_evts_lock  = threading.Lock()
_ring_last_ding_at   = None    # datetime of last seen ding
_ring_last_motion_at = None    # datetime of last seen motion

# Ring device status cache (updated by event poller)
_ring_status = {
    "connected": False,
    "device_name": "Front Door",
    "battery": 100,
    "rssi": 0,
    "rssi_label": "Unknown",
    "ac_power": False,
    "firmware": "",
    "uptime_hours": 0,
    "wifi_name": "",
    "packet_loss": 0.0,
    "subscribed": False,
    "last_updated": None,
}
_ring_status_lock = threading.Lock()
_ring_history_cache = []  # [{id, kind, created_at, answered, duration, ...}]
_ring_history_lock = threading.Lock()
_ring_history_last_update = 0
# Global device ref exposed for live stream endpoint (set by _ring_event_poller)
_ring_live_device = [None]
_ring_live_loop   = [None]


def _ring_snapshot_poller():
    """Background thread: fetch Ring doorbell snapshot every 30s → _ring_snap_bytes.
    Ring's session API is blocked for programmatic clients; snapshots may not work,
    but we try periodically and serve the last successful image.
    """
    global _ring_snap_bytes, _ring_snap_age
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ring_ref   = [None]
    device_ref = [None]

    async def _init_ring():
        r = await _ring_build(update=True)
        devs = list(r.video_devices())
        return r, (devs[0] if devs else None)

    while True:
        try:
            if ring_ref[0] is None:
                r, d = loop.run_until_complete(_init_ring())
                ring_ref[0], device_ref[0] = r, d
                if d:
                    log.info("Ring snapshot poller: device=%s (id=%s)",
                             getattr(d, 'name', d), getattr(d, 'id', '?'))
            if device_ref[0] is not None:
                img = loop.run_until_complete(device_ref[0].async_get_snapshot())
                if img:
                    with _ring_snap_lock:
                        _ring_snap_bytes = img
                        _ring_snap_age   = time.time()
                    log.info("Ring snapshot: %d bytes", len(img))
        except Exception as exc:
            log.debug("Ring snapshot error: %s", exc)
            # Close the aiohttp session before discarding the ring object
            try:
                if ring_ref[0] is not None:
                    loop.run_until_complete(ring_ref[0].auth.async_close())
            except Exception:
                pass
            ring_ref[0] = device_ref[0] = None
        time.sleep(30)  # 30s between snapshot attempts (Ring cloud API throttle)


def _ring_event_poller():
    """Background thread: detect Ring ding/motion via history (every 15s) and active dings (every 5s).
    - Polls /clients_api/doorbots/{id}/history for ding/motion/on_demand events
    - Polls /clients_api/dings/active for real-time ringing detection
    - Caches device health, history, and emits SSE events for new activity
    """
    import asyncio
    from datetime import datetime, timezone
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ring_ref    = [None]
    device_id   = [None]
    device_ref  = [None]
    last_evt_id = [None]  # most recently seen event ID (str)
    active_ding_ids = set()  # track current active ding IDs to avoid duplicate events

    HISTORY_KINDS = {'ding', 'motion', 'on_demand'}

    async def _init_ring():
        r = await _ring_build(update=True)
        devs = list(r.video_devices())
        dev_id = str(devs[0].id) if devs else None
        dev = devs[0] if devs else None
        return r, dev_id, dev

    async def _poll_history(ring, dev_id):
        resp = await ring._async_query(f'/clients_api/doorbots/{dev_id}/history')
        return resp.json()

    async def _poll_active_dings(ring):
        """Poll for currently active dings."""
        try:
            resp = await ring._async_query('/clients_api/dings/active')
            return resp.json() if resp else []
        except Exception:
            return []

    def _update_device_status(dev):
        """Cache device health info to _ring_status."""
        global _ring_status
        try:
            attrs = getattr(dev, '_attrs', {})
            health = attrs.get('health', {})
            battery = health.get('battery_percentage', 100)
            rssi = health.get('rssi', 0)
            ac = health.get('ac_power', 0)
            fw = health.get('firmware_version', '')
            uptime_sec = health.get('uptime_sec', 0)
            wifi = health.get('wifi_name', '')
            pkt_loss = health.get('packet_loss', 0.0)
            connected = health.get('connected', True)

            # Map rssi to label
            if rssi >= -30:
                label = "Excellent"
            elif rssi >= -67:
                label = "Good"
            elif rssi >= -70:
                label = "Fair"
            else:
                label = "Poor"

            with _ring_status_lock:
                _ring_status.update({
                    "connected": connected,
                    "device_name": getattr(dev, 'name', 'Front Door'),
                    "battery": battery,
                    "rssi": rssi,
                    "rssi_label": label,
                    "ac_power": bool(ac),
                    "firmware": fw,
                    "uptime_hours": uptime_sec / 3600,
                    "wifi_name": wifi,
                    "packet_loss": pkt_loss,
                    "subscribed": True,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                })
        except Exception as e:
            log.debug("Ring device status update error: %s", e)

    def _history_loop():
        nonlocal last_evt_id
        import asyncio as _aio
        hloop = _aio.new_event_loop()
        h_ring_ref = [None]

        async def _hloop_poll(dev_id):
            if h_ring_ref[0] is None:
                h_ring_ref[0] = await _ring_build(update=True)
            try:
                resp = await h_ring_ref[0]._async_query(f'/clients_api/doorbots/{dev_id}/history')
                return resp.json()
            except Exception:
                h_ring_ref[0] = None
                return []

        while True:
            try:
                if device_id[0]:
                    hist = hloop.run_until_complete(_hloop_poll(device_id[0]))

                    # Cache history
                    with _ring_history_lock:
                        _ring_history_cache[:] = hist[:30]  # Keep last 30 events

                    # Emit new events
                    for evt in hist:
                        evt_id = str(evt.get('id', ''))
                        if evt_id == last_evt_id[0]:
                            break
                        kind = evt.get('kind', '')
                        if kind in HISTORY_KINDS and kind != 'ding':  # Dings handled by active poller
                            created = evt.get('created_at', '')
                            try:
                                dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                                ts = dt.timestamp()
                            except Exception:
                                ts = time.time()
                            evt_type = 'motion' if kind == 'motion' else 'on_demand'
                            dev_name = (evt.get('doorbot') or {}).get('description') or 'Front Door'
                            with _ring_evts_lock:
                                _ring_evts.append({"ts": ts, "type": evt_type, "device": dev_name})
                                if len(_ring_evts) > 50:
                                    _ring_evts.pop(0)
                            log.info("Ring %s detected: %s at %s", evt_type, dev_name, created)
                    if hist:
                        last_evt_id[0] = str(hist[0].get('id', ''))

                    # Update device status periodically
                    if device_ref[0]:
                        _update_device_status(device_ref[0])
            except Exception as exc:
                log.debug("Ring history poll error: %s", exc)
            time.sleep(15)

    history_thread = threading.Thread(target=_history_loop, daemon=True, name="ring-history")
    history_thread.start()

    while True:
        try:
            if ring_ref[0] is None:
                r, dev_id, dev = loop.run_until_complete(_init_ring())
                ring_ref[0], device_id[0], device_ref[0] = r, dev_id, dev
                _ring_live_device[0] = dev
                _ring_live_loop[0]   = loop
                log.info("Ring event poller: device_id=%s, device=%s", dev_id, dev.name if dev else None)
                if dev:
                    _update_device_status(dev)
                # Seed last_evt_id with the current latest event
                if dev_id:
                    hist = loop.run_until_complete(_poll_history(r, dev_id))
                    if hist:
                        last_evt_id[0] = str(hist[0].get('id', ''))
                        log.info("Ring event poller: seeded last_evt_id=%s", last_evt_id[0])

            # Poll active dings every 5s (real-time detection)
            if ring_ref[0] and device_id[0]:
                active_dings = loop.run_until_complete(_poll_active_dings(ring_ref[0]))
                new_active_ids = set()
                for ding in active_dings:
                    ding_id = str(ding.get('id', ''))
                    ding_kind = ding.get('kind', '')
                    new_active_ids.add(ding_id)
                    # Only emit for real doorbell presses (kind=='ding')
                    # Ignore on_demand (live view opened), motion, etc.
                    if ding_id not in active_ding_ids and ding_kind == 'ding':
                        ts = time.time()
                        dev_name = device_ref[0].name if device_ref[0] else 'Front Door'
                        with _ring_evts_lock:
                            _ring_evts.append({"ts": ts, "type": "ding", "device": dev_name})
                            if len(_ring_evts) > 50:
                                _ring_evts.pop(0)
                        log.info("Ring ACTIVE DING detected (kind=%s): %s", ding_kind, ding_id)
                active_ding_ids = new_active_ids

        except Exception as exc:
            log.debug("Ring event poller error: %s", exc)
            try:
                if ring_ref[0] is not None:
                    loop.run_until_complete(ring_ref[0].auth.async_close())
            except Exception:
                pass
            ring_ref[0] = None
        time.sleep(5)  # poll active dings every 5s

    # History poll (every 15s — run in a separate slower loop to avoid blocking)
    # This is integrated into the main 5s loop but only executes every 3 iterations
    history_counter = [0]

def _get_wyze_client(force_refresh=False):
    """Return a cached Wyze Client, creating/refreshing only when needed.
    Implements backoff: after a failed auth, wait 5 min before retrying."""
    global _wyze_client, _wyze_next_retry
    if not (WYZE_API_KEY and WYZE_KEY_ID and WYZE_EMAIL and WYZE_PASSWORD):
        return None
    with _wyze_client_lock:
        if _wyze_client is not None and not force_refresh:
            return _wyze_client
        # Respect backoff window
        if time.time() < _wyze_next_retry:
            return None
        try:
            from wyze_sdk import Client
            _wyze_client = Client(
                email=WYZE_EMAIL, password=WYZE_PASSWORD,
                api_key=WYZE_API_KEY, key_id=WYZE_KEY_ID
            )
            _wyze_next_retry = 0
            log.info("Wyze client authenticated OK")
        except Exception as e:
            log.warning("Wyze auth error: %s — backing off 5 min", e)
            _wyze_client = None
            _wyze_next_retry = time.time() + 300  # retry in 5 min
        return _wyze_client


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DEVICE ADAPTERS                                                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── SPAN Panel Adapter ────────────────────────────────────────────────────────

def _span_get(path):
    url = f"http://{SPAN_HOST}{path}"
    headers = {}
    if SPAN_TOKEN:
        headers["Authorization"] = f"Bearer {SPAN_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.loads(r.read())
    except Exception as e:
        raise RuntimeError(f"SPAN GET {path}: {e}")


def span_register():
    """One-time token registration — call manually after pressing door button 3x."""
    url = f"http://{SPAN_HOST}/api/v1/auth/register"
    data = json.dumps({"name": "jarvis-dashboard", "description": "Jarvis Home Energy OS"}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read())
    token = resp.get("accessToken", "")
    print(f"SPAN Token: {token}")
    print("Add this to config.py as SPAN_TOKEN")
    return token


def poll_span():
    try:
        status = _span_get("/api/v1/status")
        door = status.get("system", {}).get("doorState", "?")
        uptime = status.get("system", {}).get("uptime", 0)

        circuits_raw = []
        grid_power = 0
        enphase_w  = 0.0   # branches 29+31 (Enphase IQ8PLUS)
        solaredge_w = 0.0  # branches 30+32 (SolarEdge SE5000H)
        if SPAN_TOKEN:
            panel = _span_get("/api/v1/panel")
            grid_power = panel.get("instantGridPowerW", 0)
            # Parse solar branch data — positive instantPowerW = power flowing into panel
            branches = panel.get("branches", [])
            branch_map = {b.get("id"): b.get("instantPowerW", 0) for b in branches}
            enphase_w   = max(0.0, branch_map.get(29, 0)) + max(0.0, branch_map.get(31, 0))
            solaredge_w = max(0.0, branch_map.get(30, 0)) + max(0.0, branch_map.get(32, 0))
            if enphase_w > 10 or solaredge_w > 10:
                log.info("SPAN solar branches — Enphase(29+31): %.0fW  SolarEdge(30+32): %.0fW",
                         enphase_w, solaredge_w)
            circuits_raw = _span_get("/api/v1/circuits")
            # API returns {"circuits": {"uuid": {...}, ...}} — extract the inner dict values
            if isinstance(circuits_raw, dict):
                inner = circuits_raw.get("circuits", circuits_raw)
                circuits_raw = list(inner.values()) if isinstance(inner, dict) else (inner or [])

        circuits = []
        for c in circuits_raw:
            pwr = c.get("instantPowerW", 0)
            circuits.append({
                "id": c.get("id", ""),
                "name": c.get("name", "?"),
                "power_w": round(pwr, 0),
                "relay": c.get("relayState", "?"),
                "priority": c.get("priority", "?"),
                "sheddable": c.get("is_sheddable", False),
                "color": "green" if abs(pwr) < 200 else ("yellow" if abs(pwr) < 1500 else "red"),
            })

        with _state_lock:
            _state["span"] = {
                "status": "online" if SPAN_TOKEN else "no_token",
                "door": door,
                "uptime": uptime,
                "grid_power": grid_power,
                "enphase_w": round(enphase_w, 1),    # branches 29+31 — Enphase IQ8PLUS
                "solaredge_w": round(solaredge_w, 1), # branches 30+32 — SolarEdge SE5000H
                "circuits": circuits,
                "last_seen": time.time(),
            }
        return True
    except Exception as e:
        log.warning("SPAN poll error: %s", e)
        with _state_lock:
            _state["span"]["status"] = "error"
        return False


# ── Enphase IQ Gateway Adapter ────────────────────────────────────────────────

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _enphase_get(path, token=None):
    url = f"https://{ENPHASE_HOST}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=5, context=_ssl_ctx) as r:
        ct = r.headers.get("Content-Type", "")
        raw = r.read()
        if "json" in ct or raw.startswith(b"[") or raw.startswith(b"{"):
            return json.loads(raw)
        return raw.decode()


def enphase_get_token(email=None, password=None, serial=None):
    """Fetch a 1-year JWT from Enphase cloud. Store in config.py as ENPHASE_TOKEN."""
    email = email or ENPHASE_EMAIL
    password = password or ENPHASE_PASSWORD
    serial = serial or ENPHASE_SERIAL

    # Step 1 — session_id
    login_data = urllib.parse.urlencode({"user[email]": email, "user[password]": password}).encode()
    req = urllib.request.Request(
        "https://enlighten.enphaseenergy.com/login/login.json",
        data=login_data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        session_id = json.loads(r.read())["session_id"]

    # Step 2 — JWT
    token_data = json.dumps({"session_id": session_id, "serial_num": serial, "username": email}).encode()
    req2 = urllib.request.Request(
        "https://entrez.enphaseenergy.com/tokens",
        data=token_data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req2, timeout=10) as r:
        token = r.read().decode().strip()

    print(f"Enphase JWT: {token}")
    print("Add to config.py as ENPHASE_TOKEN")
    return token


def poll_enphase():
    try:
        # Try reading meters (needs token on D8.x firmware)
        token = ENPHASE_TOKEN or None

        if token:
            readings = _enphase_get("/ivp/meters/readings", token=token)
            prod_w = cons_w = 0
            for meter in (readings if isinstance(readings, list) else []):
                ap = meter.get("activePower", 0)
                # Determine if production or consumption by eid range
                eid = meter.get("eid", 0)
                if eid & 0x1000000:  # production meter
                    prod_w += ap
                else:
                    cons_w += ap
            status = "online"
        else:
            # D8.x firmware requires token — use production.json which is partly open
            try:
                prod_data = _enphase_get("/api/v1/production")
                prod_w = prod_data.get("wattsNow", 0)
                cons_w = 0
                status = "partial"
            except Exception:
                prod_w = 0; cons_w = 0
                status = "no_token"

        with _state_lock:
            existing_inverters = _state["enphase"].get("inverters", [])
            _state["enphase"] = {
                "status": status,
                "production_w": round(prod_w, 0),
                "consumption_w": round(cons_w, 0),
                "net_w": round(prod_w - cons_w, 0),
                "firmware": "D8.3.5167",
                "serial": ENPHASE_SERIAL,
                "inverters": existing_inverters,
                "last_seen": time.time(),
            }

        # Per-inverter data (IQ8PLUS microinverters) — only when token available
        if token:
            try:
                inv_url = f"https://{ENPHASE_HOST}/api/v1/production/inverters"
                req_inv = urllib.request.Request(inv_url, headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req_inv, timeout=10, context=_ssl_ctx) as r:
                    inverters_raw = json.loads(r.read())
                inverters = [
                    {
                        "serial": i["serialNumber"],
                        "reportDate": i["lastReportDate"],
                        "watts": i["lastReportWatts"],
                        "maxWatts": i["maxReportWatts"],
                    }
                    for i in inverters_raw
                ]
                with _state_lock:
                    _state["enphase"]["inverters"] = inverters
                log.debug("Enphase inverters: %d units", len(inverters))
            except Exception as inv_e:
                log.warning("Enphase inverter fetch error: %s", inv_e)
                # Keep existing inverters list — don't wipe it on error

        return True
    except Exception as e:
        log.warning("Enphase poll error: %s", e)
        with _state_lock:
            _state["enphase"]["status"] = "error"
        return False


# ── Pentair IntelliCenter Adapter ─────────────────────────────────────────────

_pentair_lock = threading.Lock()
_pentair_sock = None


def _pentair_connect():
    global _pentair_sock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((PENTAIR_HOST, PENTAIR_PORT))
    _pentair_sock = s
    return s


def _pentair_cmd(cmd_dict, sock=None):
    close_after = sock is None
    if sock is None:
        sock = _pentair_connect()
    msg = json.dumps(cmd_dict).encode()
    sock.sendall(msg)
    time.sleep(0.5)
    chunks = []
    sock.settimeout(3)
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    except socket.timeout:
        pass
    if close_after:
        sock.close()
    raw = b"".join(chunks).decode()
    # Handle multiple concatenated JSON objects
    results = []
    for line in raw.split("}{"):
        line = line.strip()
        if not line:
            continue
        if not line.startswith("{"):
            line = "{" + line
        if not line.endswith("}"):
            line = line + "}"
        try:
            results.append(json.loads(line))
        except Exception:
            pass
    return results[0] if len(results) == 1 else results


def _pentair_query(objnam, keys, sock=None):
    cmd = {
        "command": "GetParamList",
        "messageID": str(uuid.uuid4())[:8],
        "objectList": [{"objnam": objnam, "keys": keys}],
    }
    resp = _pentair_cmd(cmd, sock)
    if isinstance(resp, list):
        resp = resp[0] if resp else {}
    objs = resp.get("objectList", [])
    return objs[0].get("params", {}) if objs else {}


def poll_pentair():
    try:
        with _pentair_lock:
            s = _pentair_connect()
            try:
                # Body state
                pool = _pentair_query("B1101", ["STATUS", "TEMP", "LOTMP", "HITMP", "HTSRC"], s)
                spa = _pentair_query("B1202", ["STATUS", "TEMP", "LOTMP", "HITMP", "HTSRC"], s)
                pump = _pentair_query("PMP01", ["STATUS", "RPM", "GPM", "PWR"], s)
                heater = _pentair_query("H0001", ["STATUS", "SNAME"], s)

                # Key circuits
                circuit_map = {
                    "C0001": "Spa",
                    "C0003": "Deep Light",
                    "C0004": "Spa Light",
                    "C0002": "Shallow Lights",
                    "C0006": "Pool",
                    "C0008": "Tree Lights",
                    "C0009": "Air Blower",
                    "FTR01": "Cleaner",
                    # H0001 (Gas Heater) excluded — controlled via dedicated heater card, not circuit tiles
                }
                circuits = []
                for objnam, label in circuit_map.items():
                    p = _pentair_query(objnam, ["STATUS"], s)
                    circuits.append({"id": objnam, "name": label, "status": p.get("STATUS", "?")})
            finally:
                s.close()

        def safe_int(v, default=0):
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        with _state_lock:
            _state["pentair"] = {
                "status": "online",
                "pool": {
                    "status": pool.get("STATUS", "?"),
                    "temp": safe_int(pool.get("TEMP")),
                    "setpoint_lo": safe_int(pool.get("LOTMP")),
                    "setpoint_hi": safe_int(pool.get("HITMP")),
                    "heat_source": pool.get("HTSRC", "?"),
                },
                "spa": {
                    "status": spa.get("STATUS", "?"),
                    "temp": safe_int(spa.get("TEMP")),
                    "setpoint_lo": safe_int(spa.get("LOTMP")),
                    "setpoint_hi": safe_int(spa.get("HITMP")),
                    "heat_source": spa.get("HTSRC", "?"),
                },
                "pump": {
                    "status": pump.get("STATUS", "?"),
                    "rpm": safe_int(pump.get("RPM")),
                    "gpm": safe_int(pump.get("GPM")),
                    "power_w": safe_int(pump.get("PWR")),
                },
                "heater": {
                    "status": heater.get("STATUS", "?"),
                },
                "circuits": circuits,
                "last_seen": time.time(),
            }
        return True
    except Exception as e:
        log.warning("Pentair poll error: %s", e)
        with _state_lock:
            _state["pentair"]["status"] = "error"
        return False


def pentair_set(objnam, params):
    """Send a SetParamList command to IntelliCenter."""
    cmd = {
        "command": "SetParamList",
        "messageID": str(uuid.uuid4())[:8],
        "objectList": [{"objnam": objnam, "params": params}],
    }
    with _pentair_lock:
        resp = _pentair_cmd(cmd)
    return resp


# ── Tesla Wall Connector Gen 3 Adapter ────────────────────────────────────────

def poll_wall_connector():
    """Poll Tesla Wall Connector Gen 3 local API (no auth required)."""
    if not TESLA_WC_HOST:
        with _state_lock:
            _state["wall_connector"]["status"] = "unconfigured"
        return False
    try:
        url = f"http://{TESLA_WC_HOST}/api/1/vitals"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as r:
            v = json.loads(r.read())

        grid_v = v.get("grid_v", 0)
        # Use vehicle_current_a — the actual current the car is drawing.
        # currentA_a / currentB_a are per-phase sensor reads and can be 0 on one leg.
        current_a = v.get("vehicle_current_a", 0) or v.get("currentB_a", 0) or v.get("currentA_a", 0)
        charging_w = round(grid_v * current_a, 0)

        # evse_state map (expanded — state 11 = charging on newer firmware)
        evse_state = v.get("evse_state", 0)
        contactor = v.get("contactor_closed", False)
        state_map = {
            0: "booting", 1: "auth_required", 4: "charging", 5: "complete",
            6: "fault", 7: "disconnected", 8: "wait_car", 9: "standby",
            11: "charging",   # newer firmware: contactor closed, actively charging
            12: "charging",   # seen on some units during active charge
        }
        # If contactor is closed and current flowing, always show as charging regardless of state code
        if contactor and current_a > 0.5:
            charge_status = "charging"
        else:
            charge_status = state_map.get(evse_state, f"state_{evse_state}")

        with _state_lock:
            _state["wall_connector"] = {
                "status": "online",
                "charge_status": charge_status,
                "vehicle_connected": v.get("vehicle_connected", False),
                "charging_w": charging_w,
                "session_energy_wh": round(v.get("session_energy_wh", 0), 1),
                "session_s": v.get("session_s", 0),
                "grid_v": round(grid_v, 1),
                "current_a": round(current_a, 1),
                "pcba_temp_c": round(v.get("pcba_temp_c", 0), 1),
                "handle_temp_c": round(v.get("handle_temp_c", 0), 1),
                "uptime_s": v.get("uptime_s", 0),
                "alerts": v.get("current_alerts", []),
                "last_seen": time.time(),
            }
        return True
    except Exception as e:
        log.warning("Wall Connector poll error: %s", e)
        with _state_lock:
            _state["wall_connector"]["status"] = "error"
        return False


# ── Tesla Fleet API Adapter — Energy Gateway 3V ───────────────────────────────
# Auth: OAuth via teslapy browser flow → approve callback URL → token in cache under 'sso' key.
# Refresh: auth.tesla.com directly (teslapy's own .refresh_token() returns 404 — do NOT use it).
# Re-auth if needed: run teslapy interactively, open the browser URL it prints, approve, done.
# Cache: /home/rob/.openclaw/workspace/jarvis-home-energy/tesla_cache.json

_TESLA_CACHE_FILE = "/home/rob/.openclaw/workspace/jarvis-home-energy/tesla_cache.json"
_TESLA_FLEET_BASE = "https://owner-api.teslamotors.com/api/1"
_TESLA_AUTH_URL   = "https://auth.tesla.com/oauth2/v3/token"
_tesla_fleet_lock = threading.Lock()


def _get_tesla_fleet_token():
    """Return a valid Fleet API access_token, auto-refreshing via auth.tesla.com if expired."""
    with _tesla_fleet_lock:
        cache = json.load(open(_TESLA_CACHE_FILE))
        sso   = cache.get("rob.hartwig@gmail.com", {}).get("sso", {})
        access_token  = sso.get("access_token", "")
        refresh_token = sso.get("refresh_token", "")
        expires_at    = sso.get("expires_at", 0)

        if not refresh_token:
            raise RuntimeError("Tesla OAuth not authorized — run browser auth flow first")

        # Refresh if expired or within 5 min of expiry
        if time.time() >= expires_at - 300:
            log.info("Tesla token expired/near-expiry — refreshing via auth.tesla.com")
            r = _requests.post(_TESLA_AUTH_URL, json={
                "grant_type":    "refresh_token",
                "client_id":     "ownerapi",
                "refresh_token": refresh_token,
                "scope":         "openid email offline_access",
            }, timeout=15)
            r.raise_for_status()
            new_tok = r.json()
            new_tok["expires_at"] = time.time() + new_tok.get("expires_in", 28800)
            sso.update(new_tok)
            cache["rob.hartwig@gmail.com"]["sso"] = sso
            json.dump(cache, open(_TESLA_CACHE_FILE, "w"))
            access_token = new_tok["access_token"]
            log.info("Tesla token refreshed — valid for %.0f hours",
                     new_tok.get("expires_in", 0) / 3600)

        return access_token


def poll_tesla():
    try:
        token = _get_tesla_fleet_token()
        headers = {"Authorization": f"Bearer {token}"}
        base = f"{_TESLA_FLEET_BASE}/energy_sites/{TESLA_ENERGY_SITE_ID}"

        # Live status — primary energy flow data
        r_live = _requests.get(f"{base}/live_status", headers=headers, timeout=10)
        r_live.raise_for_status()
        live = r_live.json().get("response", r_live.json())

        solar_w = live.get("solar_power", 0)
        battery_w = live.get("battery_power", 0)
        grid_w = live.get("grid_power", 0)
        load_w = live.get("load_power", 0)
        soe = live.get("percentage_charged", 0)
        grid_state = live.get("grid_status", "Unknown")
        island_status = live.get("island_status", "on_grid")
        islanded = island_status != "on_grid"
        storm_mode_active = live.get("storm_mode_active", False)

        # Site info — backup reserve percent and site name (best-effort)
        backup_reserve = 0
        site_name = ""
        try:
            r_info = _requests.get(f"{base}/site_info", headers=headers, timeout=10)
            r_info.raise_for_status()
            info = r_info.json().get("response", r_info.json())
            backup_reserve = (
                info.get("user_settings", {}).get("backup_reserve_percent", 0)
                or info.get("backup_reserve_percent", 0)
            )
            site_name = info.get("site_name", "")
        except Exception as e_info:
            log.debug("Tesla site_info fetch error (non-fatal): %s", e_info)

        with _state_lock:
            _state["tesla"] = {
                "status": "online",
                "soe": round(soe, 1),
                "solar_w": round(solar_w, 0),
                "battery_w": round(battery_w, 0),
                "grid_w": round(grid_w, 0),
                "load_w": round(load_w, 0),
                "grid_state": grid_state,
                "islanded": islanded,
                "backup_reserve_percent": round(backup_reserve, 1),
                "site_name": site_name,
                "storm_mode_active": storm_mode_active,
                "last_seen": time.time(),
            }
        log.info("Tesla Fleet API poll OK — solar=%.0fW battery=%.0fW grid=%.0fW soe=%.1f%%",
                 solar_w, battery_w, grid_w, soe)
        return True
    except Exception as e:
        log.warning("Tesla Fleet API poll error: %s", e)
        with _state_lock:
            _state["tesla"]["status"] = "error"
        return False


# ── Summary Computation ───────────────────────────────────────────────────────

def _update_summary():
    with _state_lock:
        t = _state["tesla"]
        e = _state["enphase"]
        p = _state["pentair"]
        s = _state["span"]

        tesla_online = t.get("status") == "online"

        # Prefer Tesla for energy flows (most complete source)
        # Fallback: SPAN grid_power is the real import/export; Enphase has solar production
        if tesla_online:
            solar = t["solar_w"]
            battery = t["battery_w"]
            grid = t["grid_w"]   # True SRP total (SPAN + CT) — used for SRP Grid node
            span_grid = s.get("grid_power", 0)  # SPAN-only home circuits — used for Home Panel node
            load = span_grid  # Home Panel shows SPAN load, not Tesla total
        else:
            solar = e.get("production_w", 0)
            # SPAN grid_power: positive = importing, negative = exporting
            span_grid = s.get("grid_power", 0)
            grid = span_grid
            battery = 0
            # Home load = solar production + grid import (or - grid export)
            load = solar + span_grid

        pool_w = p.get("pump", {}).get("power_w", 0)

        # Solar from SPAN branch data (ground truth — branches 29/31 = Enphase, 30/32 = SolarEdge)
        # Solar circuits do NOT appear in the named circuits list; only in /api/v1/panel branches.
        enphase_solar_w  = s.get("enphase_w", 0)    # branches 29+31
        solaredge_solar_w = s.get("solaredge_w", 0) # branches 30+32
        span_solar_w = enphase_solar_w + solaredge_solar_w  # combined (for reference)
        total_solar_w = enphase_solar_w + solaredge_solar_w

        # SPAN home consumption: abs sum of consuming circuits (power_w < -10W)
        span_circuits = s.get('circuits', [])
        span_home_w = abs(sum(c.get('power_w', 0) for c in span_circuits if (c.get('power_w', 0) or 0) < -10))

        wc = _state["wall_connector"]
        # V2H: CT is feeding power to home (source, not sink)
        ct_v2h = wc.get('charge_status', '') in ('powersharing', 'vehicle_powersharing') or \
                 (wc.get('charging_w', 0) or 0) < -100
        ct_w = wc.get("charging_w", 0) if wc.get("status") == "online" and not ct_v2h else 0
        ct_v2h_w = abs(wc.get("charging_w", 0)) if ct_v2h else 0

        # True SRP grid draw = SPAN grid + CyberTruck charging (CT is on a dedicated circuit
        # bypassing SPAN; Tesla GW sees both when online, must be summed manually when offline)
        srp_grid_w = grid if tesla_online else span_grid + ct_w

        _state["summary"] = {
            "solar_w": round(total_solar_w, 0),            # total: Enphase + SolarEdge (for path animations)
            "enphase_solar_w": round(enphase_solar_w, 0),  # Solar 1 — Enphase IQ8 (from Enphase API)
            "solaredge_solar_w": round(solaredge_solar_w, 0),  # Solar 2 — SolarEdge SE5000H (SPAN minus Enphase)
            "span_solar_w": round(span_solar_w, 0),        # SPAN total positive circuits (both systems raw)
            "load_w": round(span_home_w, 0),               # pure SPAN circuit consumption (negative circuits)
            "battery_w": battery,
            "grid_w": round(srp_grid_w, 0),      # true total SRP draw (includes CT when offline)
            "span_grid_w": round(span_grid, 0),  # SPAN-only grid power (for Home Panel node)
            "srp_grid_w": round(srp_grid_w, 0),  # explicit alias for SRP Grid node
            "pool_w": pool_w,
            "ct_charging_w": ct_w,
            "ct_v2h": ct_v2h,
            "ct_v2h_w": round(ct_v2h_w, 0),
            "total_load_w": round(span_home_w + ct_w, 0),   # SPAN consumption + CT charging = true home consumption
            "self_powered_pct": round(min(100, total_solar_w / max(span_home_w + ct_w, 1) * 100), 1) if (span_home_w + ct_w) > 0 else 0,
        }
        _state["ts"] = time.time()


# ── Wyze + Ring Camera Adapter ────────────────────────────────────────────────

def poll_cameras():
    cameras = []

    # Wyze — uses cached client (login once, reuse)
    client = _get_wyze_client()
    if client:
        try:
            devices = client.cameras.list()
            for cam in devices:
                # cameras.list() returns abbreviated data; call info() for event files
                thumb_url = ""
                last_motion = ""
                try:
                    detail = client.cameras.info(device_mac=cam.mac)
                    for ev in (detail.latest_events or []):
                        # timestamp (milliseconds epoch)
                        ts = getattr(ev, 'time', None)
                        if ts and not last_motion:
                            last_motion = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
                        # image file URL
                        if not thumb_url:
                            for f in (getattr(ev, 'files', []) or []):
                                url = getattr(f, 'url', None)
                                if url:
                                    thumb_url = str(url)
                                    break
                        if thumb_url and last_motion:
                            break
                except Exception as e_info:
                    log.debug("Wyze info error for %s: %s", cam.mac, e_info)
                cameras.append({
                    "name": cam.nickname or cam.mac,
                    "mac": cam.mac,
                    "type": "wyze",
                    "status": "online" if cam.is_online else "offline",
                    "last_seen": str(cam.last_seen) if hasattr(cam, 'last_seen') else "",
                    "last_motion": last_motion,
                    "snapshot_path": f"/api/camera/{cam.mac}/snapshot",
                    "thumbnail_url": thumb_url,
                })
        except Exception as e:
            log.warning("Wyze poll error: %s — forcing client refresh next cycle", e)
            global _wyze_client
            _wyze_client = None  # force re-auth next cycle

    # RING DISABLED — do not poll. triggers 2FA SMS on every auth attempt. No token cached.
    pass  # Ring removed from poll loop

    with _state_lock:
        _state["cameras"] = cameras
    return True


# ── Roku ECP Integration ──────────────────────────────────────────────────────

ROKU_IPS = []  # auto-discovered at startup

def _discover_roku_devices():
    """Discover Roku devices via SSDP multicast (official Roku method)."""
    import socket as _sock
    SSDP_ADDR = "239.255.255.250"
    SSDP_PORT = 1900
    MSG = b"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 3\r\nST: roku:ecp\r\n\r\n"
    found = []
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM, _sock.IPPROTO_UDP)
        s.settimeout(4)
        s.sendto(MSG, (SSDP_ADDR, SSDP_PORT))
        seen = set()
        try:
            while True:
                data, addr = s.recvfrom(1024)
                ip = addr[0]
                if ip not in seen:
                    seen.add(ip)
                    found.append(ip)
        except _sock.timeout:
            pass
        finally:
            s.close()
    except Exception as e:
        log.warning(f"[Roku] SSDP discovery failed: {e}")
    # fallback: also try known IPs from last successful discovery
    return found or ROKU_IPS

def _roku_rediscover_loop():
    global ROKU_IPS
    while True:
        time.sleep(60)
        found = _discover_roku_devices()
        if found:
            ROKU_IPS = found
            log.info("[Roku] Re-discovery: %d device(s): %s", len(found), found)

_roku_cache = {'data': [], 'ts': 0.0}
_ROKU_TTL = 15.0

def _roku_get(ip, path):
    import requests as _req
    try:
        r = _req.get(f"http://{ip}:8060{path}", timeout=1.5)
        return r.content if r.status_code == 200 else b''
    except Exception:
        return b''

def _roku_post(ip, path):
    import requests as _req
    try:
        r = _req.post(f"http://{ip}:8060{path}", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False

def _parse_xml_tag(content, tag):
    import re
    m = re.search(rb'<' + tag.encode() + rb'[^>]*>(.*?)</' + tag.encode() + rb'>', content, re.DOTALL)
    return m.group(1).decode('utf-8', errors='replace').strip() if m else ''

def poll_roku():
    global ROKU_IPS
    now = time.monotonic()
    if _roku_cache['data'] and now - _roku_cache['ts'] < _ROKU_TTL:
        return _roku_cache['data']
    if not ROKU_IPS:
        ROKU_IPS = _discover_roku_devices()
    devices = []
    for ip in ROKU_IPS:
        info  = _roku_get(ip, '/query/device-info')
        app   = _roku_get(ip, '/query/active-app')
        media = _roku_get(ip, '/query/media-player')
        name       = _parse_xml_tag(info, 'friendly-device-name') or _parse_xml_tag(info, 'user-device-name') or ip
        model      = _parse_xml_tag(info, 'model-name')
        power      = _parse_xml_tag(info, 'power-mode')
        serial     = _parse_xml_tag(info, 'serial-number')
        active_app = _parse_xml_tag(app, 'name') or 'Unknown'
        active_id  = _parse_xml_tag(app, 'id')
        play_state  = _parse_xml_tag(media, 'state') or _parse_xml_tag(media, 'State') or 'none'
        position_ms = _parse_xml_tag(media, 'position') or ''
        duration_ms = _parse_xml_tag(media, 'duration') or ''
        devices.append({
            'ip': ip, 'name': name, 'model': model,
            'power': power, 'active_app': active_app, 'active_id': active_id,
            'serial': serial, 'online': bool(info),
            'is_on': power == 'PowerOn',
            'play_state': play_state,
            'position_ms': position_ms,
            'duration_ms': duration_ms,
        })
    _roku_cache['data'] = devices
    _roku_cache['ts'] = now
    with _state_lock:
        _state['roku'] = devices
    return devices


# ── Nest Thermostat Adapter ───────────────────────────────────────────────────

def _c_to_f(c):
    return round(c * 9 / 5 + 32, 1)

def poll_nest():
    if not NEST_PROJECT_ID or not NEST_REFRESH_TOKEN:
        with _state_lock:
            _state["nest"]["status"] = "unconfigured"
        return False
    token = _get_nest_access_token()
    if not token:
        with _state_lock:
            _state["nest"]["status"] = "error"
        return False
    try:
        import urllib.request
        url = f"https://smartdevicemanagement.googleapis.com/v1/enterprises/{NEST_PROJECT_ID}/devices"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        devices = data.get("devices", [])
        thermostats = []
        for d in devices:
            if d.get("type") != "sdm.devices.types.THERMOSTAT":
                continue
            tr = d.get("traits", {})
            room = (d.get("parentRelations") or [{}])[0].get("displayName", "Thermostat")
            connectivity = tr.get("sdm.devices.traits.Connectivity", {}).get("status", "OFFLINE")
            temp_c = tr.get("sdm.devices.traits.Temperature", {}).get("ambientTemperatureCelsius", 0)
            sp = tr.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {})
            mode = tr.get("sdm.devices.traits.ThermostatMode", {}).get("mode", "OFF")
            hvac = tr.get("sdm.devices.traits.ThermostatHvac", {}).get("status", "OFF")
            humidity = tr.get("sdm.devices.traits.Humidity", {}).get("ambientHumidityPercent", 0)
            thermostats.append({
                "id": d["name"].split("/")[-1],
                "device_name": d["name"],
                "name": room,
                "status": "online" if connectivity == "ONLINE" else "offline",
                "temp_f": _c_to_f(temp_c),
                "cool_setpoint_f": _c_to_f(sp.get("coolCelsius", 0)) if sp.get("coolCelsius") else None,
                "heat_setpoint_f": _c_to_f(sp.get("heatCelsius", 0)) if sp.get("heatCelsius") else None,
                "mode": mode,
                "hvac_state": hvac,
                "humidity": humidity,
            })
        primary = thermostats[0] if thermostats else {}
        with _state_lock:
            _state["nest"] = {
                "status": "online" if thermostats else "error",
                "thermostats": thermostats,
                # backward-compat fields from primary thermostat
                "name": primary.get("name", ""),
                "temp_f": primary.get("temp_f", 0),
                "setpoint_f": primary.get("cool_setpoint_f") or primary.get("heat_setpoint_f") or 0,
                "mode": primary.get("mode", "OFF"),
                "hvac_state": primary.get("hvac_state", "OFF"),
                "humidity": primary.get("humidity", 0),
                "last_seen": time.time(),
            }
        return True
    except Exception as e:
        log.warning("Nest poll error: %s", e)
        with _state_lock:
            _state["nest"]["status"] = "error"
        return False


# ── B-Hyve Sprinkler Adapter ─────────────────────────────────────────────────

BHYVE_API = "https://api.orbitbhyve.com"
_bhyve_token = None
_bhyve_token_lock = threading.Lock()
_bhyve_next_retry = 0  # epoch seconds — back off after auth failures

_BHYVE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Host": "api.orbitbhyve.com",
    "Content-Type": "application/json; charset=utf-8;",
    "Referer": "https://api.orbitbhyve.com",
    "Orbit-Session-Token": "",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36"
    ),
}


def _bhyve_login():
    """Login to B-Hyve cloud and return session token."""
    global _bhyve_token
    hdrs = dict(_BHYVE_HEADERS)
    resp = _requests.post(
        f"{BHYVE_API}/v1/session",
        json={"session": {"email": BHYVE_EMAIL, "password": BHYVE_PASSWORD}},
        headers=hdrs,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("orbit_session_token") or data.get("orbit_api_key") or data.get("session_token")
    if not token:
        raise RuntimeError(f"No token in login response: {data}")
    _bhyve_token = token
    log.info("B-Hyve login OK")
    return token


def _bhyve_get(path, token=None):
    """Make authenticated GET to B-Hyve REST API."""
    tok = token or _bhyve_token
    hdrs = dict(_BHYVE_HEADERS)
    hdrs["Orbit-Session-Token"] = tok or ""
    resp = _requests.get(f"{BHYVE_API}{path}", headers=hdrs, params={"t": str(time.time())}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _bhyve_ws_command(device_id, payload, token=None):
    """Send a command to B-Hyve via WebSocket.
    Protocol: connect → optional server hello → send app_connection handshake →
              send command → wait for ack echo.
    """
    import asyncio
    import json as _json
    tok = token or _bhyve_token

    async def _send():
        import websockets
        ws_url = "wss://api.orbitbhyve.com/v1/events"
        async with websockets.connect(
            ws_url,
            additional_headers={"Orbit-Session-Token": tok or ""},
            ping_interval=None,
            open_timeout=25,
        ) as ws:
            # Server may or may not send a hello — drain it if present
            try:
                hello = _json.loads(await asyncio.wait_for(ws.recv(), timeout=4))
                log.debug("B-Hyve WS hello: %s", hello)
            except (asyncio.TimeoutError, Exception):
                pass

            # Send app_connection handshake (server may silently ignore but needs it)
            await ws.send(_json.dumps({
                "event": "app_connection",
                "orbit_session_token": tok or "",
                "subscribe_device_id": device_id,
            }))
            try:
                await asyncio.wait_for(ws.recv(), timeout=4)
            except (asyncio.TimeoutError, Exception):
                pass

            # Send the actual command
            await ws.send(_json.dumps(payload))
            # Wait for ack echo from server
            try:
                ack = _json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                log.debug("B-Hyve WS ack: %s", ack)
            except asyncio.TimeoutError:
                log.debug("B-Hyve WS: no ack within 8s (command may still have been accepted)")

    asyncio.run(_send())


def poll_bhyve():
    global _bhyve_token, _bhyve_next_retry
    if not BHYVE_EMAIL or not BHYVE_PASSWORD:
        with _state_lock:
            _state["bhyve"]["status"] = "unconfigured"
        return False
    # Backoff: don't retry login within 5 min of a previous auth failure
    if not _bhyve_token and time.time() < _bhyve_next_retry:
        return False
    try:
        with _bhyve_token_lock:
            if not _bhyve_token:
                _bhyve_login()

        # Get devices
        devices_raw = _bhyve_get("/v1/devices")
        if not isinstance(devices_raw, list):
            devices_raw = []

        # Get timer programs for next-run info
        try:
            programs_raw = _bhyve_get("/v1/sprinkler_timer_programs")
            if not isinstance(programs_raw, list):
                programs_raw = []
        except Exception:
            programs_raw = []

        # Build next_run lookup: device_id → station → next_run string
        next_run_lookup = {}
        for prog in programs_raw:
            dev_id = prog.get("device_id", "")
            if dev_id not in next_run_lookup:
                next_run_lookup[dev_id] = {}
            for run_time in (prog.get("run_times") or []):
                station = run_time.get("station")
                # Look for enabled program start times
                if prog.get("enabled") and station:
                    start = None
                    for st in (prog.get("start_times") or []):
                        start = st
                        break
                    if start and station not in next_run_lookup[dev_id]:
                        next_run_lookup[dev_id][station] = start

        out_devices = []
        out_zones = []

        # Devices to hide (no longer in use)
        _BHYVE_HIDDEN_DEVICES = {"Smart Hose Tap Timer"}

        for dev in devices_raw:
            dev_id = dev.get("id", "")
            dev_name = dev.get("name", "Unknown Device")
            if dev_name in _BHYVE_HIDDEN_DEVICES:
                continue
            fw = dev.get("firmware_version", "")
            dev_type = dev.get("type", "")

            # Only process sprinkler timer devices
            if "sprinkler" not in dev_type.lower() and "timer" not in dev_type.lower() and dev.get("is_connected") is None:
                if not dev.get("zones") and not dev.get("num_stations"):
                    continue

            status_obj = dev.get("status") or {}
            ws = status_obj.get("watering_status") or {}
            current_station = ws.get("current_station")
            current_remaining = ws.get("current_station_remaining", 0)  # seconds

            out_devices.append({
                "id": dev_id,
                "name": dev_name,
                "firmware": fw,
                "type": dev_type,
                "connected": dev.get("is_connected", False),
                "run_mode": status_obj.get("run_mode", "auto"),
            })

            zones_raw = dev.get("zones") or []
            if not zones_raw and dev.get("num_stations"):
                # Synthesize zone list if device has no named zones
                zones_raw = [{"station": i + 1, "name": f"Zone {i + 1}"} for i in range(dev.get("num_stations", 0))]

            dev_next_runs = next_run_lookup.get(dev_id, {})

            for zone in zones_raw:
                station = zone.get("station", zone.get("zone_id", 0))
                name = zone.get("name") or f"Zone {station}"
                enabled = zone.get("enabled", True)
                is_running = (current_station == station)
                remaining_s = int(current_remaining) if is_running else 0
                next_run = dev_next_runs.get(station, "")

                out_zones.append({
                    "device_id": dev_id,
                    "device_name": dev_name,
                    "zone_id": station,
                    "name": name,
                    "enabled": enabled,
                    "is_running": is_running,
                    "remaining_s": remaining_s,
                    "next_run": next_run,
                })

        with _state_lock:
            _state["bhyve"] = {
                "status": "online",
                "devices": out_devices,
                "zones": out_zones,
                "ts": time.time(),
                "last_seen": time.time(),
            }
        return True

    except Exception as e:
        log.warning("B-Hyve poll error: %s", e)
        # Token may have expired — clear it for next poll
        with _bhyve_token_lock:
            _bhyve_token = None
        # Back off 5 minutes after auth failure to avoid account lockout
        _bhyve_next_retry = time.time() + 300
        with _state_lock:
            _state["bhyve"]["status"] = "error"
        return False


# ── GE SmartHQ Appliances Adapter ────────────────────────────────────────────

GE_AUTH_URL = "https://accounts.brillion.geappliances.com/oauth2/token"
GE_API_BASE = "https://client.mysmarthq.com"

_ge_access_token = ""
_ge_token_expiry = 0.0
_ge_token_lock = threading.Lock()
_ge_next_retry = 0.0

# Map numeric appliance state codes → human-readable labels
_GE_STATE_MAP = {
    "0": "disconnected", "1": "idle", "2": "running",
    "3": "delay start",  "4": "paused", "5": "end of cycle",
    "6": "downloading",  "7": "remote start", "8": "standby",
}

# Map common GE appliance type tokens → emoji
_GE_TYPE_ICON = {
    "Washer": "&#129783;", "Dryer": "&#9832;", "Dishwasher": "&#127869;",
    "Clothes Washer": "&#129783;", "Clothes Dryer": "&#9832;",
    "Refrigerator": "&#129398;", "Oven": "&#128293;", "Range": "&#128293;",
    "Microwave": "&#128241;", "Freezer": "&#129398;", "AirConditioner": "&#10052;",
    "WashDryer": "&#129783;", "Hood": "&#128168;",
}

# Typical wattage estimates by appliance type when actively running
_GE_WATT_ESTIMATE = {
    "Washer": 500, "Clothes Washer": 500,
    "Dryer": 5000, "Clothes Dryer": 5000, "WashDryer": 5000,
    "Dishwasher": 1800,
    "Refrigerator": 150, "Freezer": 100,
    "Oven": 4000, "Range": 3000,
    "Microwave": 1200,
    "AirConditioner": 1500,
    "Hood": 200,
}

# Track per-appliance state transitions {appliance_id: {state, changed_at}}
_ge_state_history: dict = {}


def _ge_fetch_detail(token: str, aid: str) -> dict:
    """Try to fetch per-appliance detail + attribute data from GE API.
    Silently ignores HTTP 404 — those endpoints may not be available on all accounts.
    Returns dict with optional 'detail' and 'attributes' keys."""
    result: dict = {}
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    # Per-appliance detail
    try:
        req = urllib.request.Request(f"{GE_API_BASE}/v1/appliance/{aid}", headers=hdr)
        with urllib.request.urlopen(req, timeout=8) as r:
            result["detail"] = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code not in (404, 405):
            log.debug("GE detail %s HTTP %d", aid, e.code)
    except Exception as e:
        log.debug("GE detail %s: %s", aid, e)
    # Attribute list
    try:
        req = urllib.request.Request(f"{GE_API_BASE}/v1/appliance/{aid}/attribute", headers=hdr)
        with urllib.request.urlopen(req, timeout=8) as r:
            result["attributes"] = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code not in (404, 405):
            log.debug("GE attr %s HTTP %d", aid, e.code)
    except Exception as e:
        log.debug("GE attr %s: %s", aid, e)
    return result


def _ge_get_token():
    """Return a valid GE SmartHQ access token, refreshing via refresh_token grant."""
    global _ge_access_token, _ge_token_expiry, GE_REFRESH_TOKEN
    with _ge_token_lock:
        if _ge_access_token and time.time() < _ge_token_expiry - 60:
            return _ge_access_token
        if not (GE_CLIENT_ID and GE_REFRESH_TOKEN):
            return None
        try:
            data = urllib.parse.urlencode({
                "grant_type": "refresh_token",
                "refresh_token": GE_REFRESH_TOKEN,
                "client_id": GE_CLIENT_ID,
                "client_secret": GE_CLIENT_SECRET,
            }).encode()
            req = urllib.request.Request(
                GE_AUTH_URL, data=data, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
            _ge_access_token = resp["access_token"]
            _ge_token_expiry = time.time() + resp.get("expires_in", 3600)
            # Persist rotated refresh token if server issued a new one
            new_rt = resp.get("refresh_token")
            if new_rt and new_rt != GE_REFRESH_TOKEN:
                GE_REFRESH_TOKEN = new_rt
                try:
                    import re as _re
                    config_path = Path(__file__).parent / "config.py"
                    text = config_path.read_text()
                    text = _re.sub(r'^GE_REFRESH_TOKEN\s*=\s*.*$',
                                   f'GE_REFRESH_TOKEN = "{new_rt}"',
                                   text, flags=_re.MULTILINE)
                    config_path.write_text(text)
                    log.info("GE SmartHQ refresh token rotated — config.py updated")
                except Exception as _e:
                    log.warning("GE refresh token rotate write error: %s", _e)
            log.info("GE SmartHQ token refreshed OK")
            return _ge_access_token
        except Exception as e:
            log.warning("GE SmartHQ auth error: %s", e)
            _ge_access_token = ""
            return None


_GE_SKIP_VALUES = {"disabled", "invalid", "na", "undefined", "none", "off", ""}

def _ge_label(val, prefix="cloud.smarthq.type."):
    """Strip smarthq prefix and prettify enum values."""
    if not val:
        return ""
    v = str(val).replace(prefix, "").replace("cloud.smarthq.domain.", "").replace("cloud.smarthq.type.", "")
    parts = v.split(".")
    # Keep only the last meaningful segment(s)
    label = parts[-1].replace("_", " ").title().strip()
    # Multi-word cycles: rinseandspin → Rinse And Spin etc.
    import re
    label = re.sub(r'([a-z])([A-Z])', r'\1 \2', label)
    return label


def _ge_prettify_cycle(name):
    """Convert smarthq cycle names like 'rinseandspin' → 'Rinse And Spin'."""
    import re
    # Insert space before uppercase letters (camelCase)
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    # Known compound words
    replacements = [
        ("rinseandspin","Rinse And Spin"),("quickwash","Quick Wash"),("quickdry","Quick Dry"),
        ("coldwash","Cold Wash"),("bulkybedding","Bulky Bedding"),("powerclean","Power Clean"),
        ("sanitizeandallergen","Sanitize & Allergen"),("ultrafreshvent","UltraFresh Vent"),
        ("selfclean","Self Clean"),("activewear","Activewear"),("whitesandstuds","Whites"),
        ("extrahigh","Extra High"),("extraheavy","Extra Heavy"),("extrarinseandspin","Extra Rinse And Spin"),
    ]
    low = name.lower().replace(" ","").replace("_","").replace("-","")
    for key, label in replacements:
        if low == key:
            return label
    return name.replace("_"," ").title()


def _ge_secs_to_str(secs):
    if not secs:
        return ""
    secs = int(secs)
    if secs <= 0:
        return ""
    h, m = divmod(secs // 60, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def _ge_parse_services(services, device_type):
    """Parse Digital Twin service list into rich telemetry."""
    is_fridge = "refrigerator" in device_type
    is_washer = "washer" in device_type
    is_dryer = "dryer" in device_type
    is_dish = "dishwasher" in device_type

    result = {"state": "idle", "cycle": "", "door": "", "temp": "", "attrs": [], "est_watts": 0}
    attrs = []

    # Index services by (serviceType_short, domainType_short, serviceDeviceType_short)
    def _s(v): return str(v).replace("cloud.smarthq.service.", "").replace("cloud.smarthq.domain.", "").replace("cloud.smarthq.device.", "").replace("cloud.smarthq.type.", "")

    for svc in services:
        st = _s(svc.get("serviceType", ""))
        dom = _s(svc.get("domainType", ""))
        sdev = _s(svc.get("serviceDeviceType", ""))
        state = svc.get("state", {})

        # ── DISHWASHER ──────────────────────────────────────────
        if is_dish:
            if st == "dishwasher.state.v1" and "dishwasher" in dom:
                run = _s(state.get("runStatus", ""))
                result["state"] = "running" if run.endswith((".active", ".run")) else ("paused" if "pause" in run else "idle")
                mode = _s(state.get("mode", "")).replace("dishwasher.", "").title()
                wtemp = _s(state.get("washTemp", "")).replace("dishwasher.washtemp.", "").title()
                hdry = _s(state.get("heatedDry", "")).replace("dishwasher.heateddry.", "").replace("addedheat", "Added Heat").title()
                zone = _s(state.get("washZone", "")).replace("dishwasher.washzone.", "").title()
                ci_raw = _s(state.get("cycleIndication", "")).replace("dishwasher.cycle.indication.", "").replace("cycle.", "")
                ci = ci_raw.replace(".", " ").replace("_", " ").title() if ci_raw.lower() not in ("inactive","") else ""
                result["cycle"] = mode
                if wtemp: attrs.append({"label": "Wash Temp", "value": wtemp, "unit": ""})
                if hdry: attrs.append({"label": "Heated Dry", "value": hdry, "unit": ""})
                if zone and zone != "Both": attrs.append({"label": "Wash Zone", "value": zone, "unit": ""})
                if ci and ci not in ("Inactive", ""): attrs.append({"label": "Phase", "value": ci, "unit": ""})
                if state.get("steam"): attrs.append({"label": "Steam", "value": "On", "unit": ""})
                if state.get("bottleWash"): attrs.append({"label": "Bottle Wash", "value": "On", "unit": ""})
            elif st == "cycletimer" and dom == "cycle":
                secs = state.get("secondsRemaining", 0)
                if secs:
                    attrs.append({"label": "Remaining", "value": _ge_secs_to_str(secs), "unit": ""})
                    result["seconds_remaining"] = int(secs)
            elif st == "toggle" and dom == "door" and "dishwasher" in sdev:
                result["door"] = "Open" if state.get("on") else "Closed"
            elif st == "integer" and "inventory" in dom and "pod" in sdev:
                pods = state.get("value", 0)
                attrs.append({"label": "Pod Inventory", "value": str(pods) if pods else "⚠️ Empty", "unit": ""})
            elif st == "meter" and dom == "energy":
                kwh = round(state.get("meterValue", 0) / 1000, 1)
                attrs.append({"label": "Energy Used", "value": str(kwh), "unit": "kWh"})
            elif st == "toggle" and dom == "controls.lock" and "dishwasher" in sdev:
                if state.get("on"): attrs.append({"label": "Controls", "value": "Locked", "unit": ""})
            elif st == "toggle" and "fan.fresh" in dom:
                attrs.append({"label": "Fresh Fan", "value": "On" if state.get("on") else "Off", "unit": ""})
            elif st == "cycletimer" and dom == "delay":
                secs = state.get("secondsRemaining", 0)
                if secs: attrs.append({"label": "Delay Start", "value": _ge_secs_to_str(secs), "unit": ""})

        # ── WASHER ───────────────────────────────────────────────
        elif is_washer:
            if st == "laundry.state.v1" and sdev == "washer":
                run = _s(state.get("runStatus", ""))
                result["state"] = "running" if run.endswith((".active", ".run")) else ("paused" if "pause" in run else "idle")
                def _lc(v, strip): return _s(v).replace(strip, "").replace(".", " ").replace("_", " ").title().strip()
                cycle = _lc(state.get("cycle",""), "laundry.cycle.")
                spin  = _lc(state.get("laundrySpin",""), "laundry.spin.")
                soil  = _lc(state.get("laundrySoil",""), "laundry.soil.")
                temp  = _lc(state.get("laundryTemperature",""), "laundry.temperature.")
                rinse = _lc(state.get("laundryRinse",""), "laundry.rinse.")
                subcycle = _lc(state.get("subCycle",""), "laundry.subcycle.")
                result["cycle"] = _ge_prettify_cycle(cycle) + (f" · {_ge_prettify_cycle(subcycle)}" if subcycle.lower() not in _GE_SKIP_VALUES | {"na"} else "")
                if temp.lower() not in _GE_SKIP_VALUES: attrs.append({"label": "Water Temp", "value": _ge_prettify_cycle(temp), "unit": ""})
                if spin.lower() not in _GE_SKIP_VALUES: attrs.append({"label": "Spin Speed", "value": _ge_prettify_cycle(spin), "unit": ""})
                if soil.lower() not in _GE_SKIP_VALUES: attrs.append({"label": "Soil Level", "value": _ge_prettify_cycle(soil), "unit": ""})
                if rinse.lower() not in _GE_SKIP_VALUES | {"off"}: attrs.append({"label": "Rinse", "value": _ge_prettify_cycle(rinse), "unit": ""})
            elif st == "cycletimer" and dom == "cycle":
                secs = state.get("secondsRemaining", 0)
                if secs:
                    attrs.append({"label": "Remaining", "value": _ge_secs_to_str(secs), "unit": ""})
                    result["seconds_remaining"] = int(secs)
            elif st == "smartdispense":
                level = _s(state.get("level", "")).replace("tanklevel.", "").title()
                remaining = state.get("cyclesRemaining", 0)
                attrs.append({"label": "Detergent Tank", "value": f"{level} ({remaining} cycles left)", "unit": ""})
            elif st == "toggle" and dom == "laundry.powersteam":
                if state.get("on"): attrs.append({"label": "Power Steam", "value": "On", "unit": ""})
            elif st == "toggle" and dom == "door":
                result["door"] = "Open" if state.get("on") else "Closed"
            elif st == "integer" and dom == "delay" and not state.get("disabled"):
                hrs = state.get("value", 0)
                if hrs: attrs.append({"label": "Delay Start", "value": f"{hrs}h", "unit": ""})

        # ── DRYER ────────────────────────────────────────────────
        elif is_dryer:
            if st == "laundry.state.v1" and sdev == "dryer":
                run = _s(state.get("runStatus", ""))
                result["state"] = "running" if run.endswith((".active", ".run")) else ("paused" if "pause" in run else "idle")
                def _ld(v, strip): return _s(v).replace(strip, "").replace(".", " ").replace("_", " ").title().strip()
                cycle   = _ld(state.get("cycle",""), "laundry.cycle.")
                temp    = _ld(state.get("laundryTemperature",""), "laundry.temperature.")
                dryness = _ld(state.get("laundryDrynessLevel",""), "laundry.dryness.level.")
                subcycle_d = _ld(state.get("subCycle",""), "laundry.subcycle.")
                result["cycle"] = _ge_prettify_cycle(cycle) + (f" · {_ge_prettify_cycle(subcycle_d)}" if subcycle_d.lower() not in _GE_SKIP_VALUES | {"na"} else "")
                if temp.lower() not in _GE_SKIP_VALUES: attrs.append({"label": "Heat Level", "value": _ge_prettify_cycle(temp), "unit": ""})
                if dryness.lower() not in _GE_SKIP_VALUES: attrs.append({"label": "Dryness", "value": _ge_prettify_cycle(dryness), "unit": ""})
            elif st == "cycletimer" and dom == "cycle":
                secs = state.get("secondsRemaining", 0)
                if secs:
                    attrs.append({"label": "Remaining", "value": _ge_secs_to_str(secs), "unit": ""})
                    result["seconds_remaining"] = int(secs)
            elif st == "toggle" and "extendedtumble" in dom:
                if state.get("on"): attrs.append({"label": "Extended Tumble", "value": "On", "unit": ""})
            elif st == "laundry.toggle.v2" and "washerlink" in dom:
                linked = state.get("on", False)
                if linked:
                    lc = _s(state.get("cycle", "")).replace("laundry.cycle.", "").title()
                    attrs.append({"label": "Washer Link", "value": lc or "Linked", "unit": ""})
            elif st == "integer" and "inventory" in dom and "sheet" in sdev and "consumed" not in dom:
                sheets = state.get("value", 0)
                attrs.append({"label": "Dryer Sheets", "value": str(sheets) if sheets else "⚠️ Empty", "unit": ""})
            elif st == "integer" and dom == "delay" and not state.get("disabled"):
                hrs = state.get("value", 0)
                if hrs: attrs.append({"label": "Delay Start", "value": f"{hrs}h", "unit": ""})

        # ── REFRIGERATOR ─────────────────────────────────────────
        elif is_fridge:
            if st == "temperature" and dom == "setpoint":
                f = state.get("fahrenheit")
                if f is not None and f < 90:  # ignore 100°F placeholder values
                    if "freshfood" in sdev:
                        result["temp_fresh"] = int(f)
                    elif "freezer" in sdev and "convertibledrawer" not in sdev:
                        result["temp_freezer"] = int(f)
                    elif "convertibledrawer" in sdev and "mode3" in sdev:
                        result["temp_drawer"] = int(f)
            elif st == "mode" and dom == "door":
                m = state.get("mode", "")
                result["door"] = "Open" if "open" in m.lower() else "Closed"
            elif st == "toggle" and dom == "power" and "icemaker" in sdev:
                attrs.append({"label": "Ice Maker", "value": "On" if state.get("on") else "Off", "unit": ""})
            elif st == "toggle" and dom == "full" and "icemaker" in sdev:
                attrs.append({"label": "Ice Bin", "value": "✅ Full" if state.get("on") else "Making ice…", "unit": ""})
            elif st == "integer" and "percent.usage.remaining" in dom:
                pct = state.get("value", 0)
                attrs.append({"label": "Water Filter", "value": f"{pct}% remaining" if pct > 0 else "⚠️ Replace filter", "unit": ""})
            elif st == "string" and dom == "model" and "waterfilter" in sdev:
                attrs.append({"label": "Filter Model", "value": state.get("stringValue", ""), "unit": ""})
            elif st == "toggle" and dom == "turbo" and "freshfood" in sdev:
                if state.get("on"): attrs.append({"label": "Turbo Cool", "value": "On", "unit": ""})
            elif st == "toggle" and dom == "turbo" and "freezer" in sdev:
                if state.get("on"): attrs.append({"label": "Turbo Freeze", "value": "On", "unit": ""})
            elif st == "toggle" and dom == "power" and "autofill.pitcher" in sdev:
                attrs.append({"label": "AutoFill Pitcher", "value": "On" if state.get("on") else "Off", "unit": ""})
            elif st == "toggle" and dom == "full" and "autofill.pitcher" in sdev:
                attrs.append({"label": "Pitcher", "value": "Full" if state.get("on") else "Not Full", "unit": ""})
            elif st == "integer" and dom == "water" and "meter" in sdev:
                oz = state.get("value", 0)
                gal = round(oz / 128, 1)
                attrs.append({"label": "Water Dispensed", "value": str(gal), "unit": "gal total"})
            elif st == "mode" and "mode.selection" in dom and "convertibledrawer" in sdev:
                # mode3=29°F (fresh), mode1=full freeze etc — already showing temp so skip
                pass
            elif st == "integer" and dom == "rssi":
                rssi = state.get("value", 0)
                attrs.append({"label": "WiFi Signal", "value": f"{rssi} dBm", "unit": ""})

    # Build temp display for fridge
    if is_fridge:
        parts = []
        if "temp_fresh" in result: parts.append(f"Fresh Food: {result.pop('temp_fresh')}°F")
        if "temp_freezer" in result: parts.append(f"Freezer: {result.pop('temp_freezer')}°F")
        if "temp_drawer" in result: parts.append(f"Flex Drawer: {result.pop('temp_drawer')}°F")
        result["temp"] = " | ".join(parts)
        if result["door"]:
            attrs.insert(0, {"label": "Door", "value": result["door"], "unit": ""})

    result["attrs"] = attrs[:12]
    return result


def poll_ge_appliances():
    global _ge_next_retry
    if not (GE_CLIENT_ID and GE_REFRESH_TOKEN):
        with _state_lock:
            _state["ge_appliances"]["status"] = "unconfigured"
        return False
    if time.time() < _ge_next_retry:
        return False
    try:
        token = _ge_get_token()
        if not token:
            raise RuntimeError("no token")

        hdr = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        # GET /v2/device — returns all devices with services embedded
        req = urllib.request.Request(f"{GE_API_BASE}/v2/device", headers=hdr)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        devices = data.get("devices", []) if isinstance(data, dict) else []

        now = time.time()

        # For each device, fetch full detail (includes all services with current state)
        import concurrent.futures as _cf
        def _fetch_device(dev):
            did = dev.get("deviceId", "")
            if not did:
                return dev, []
            result_dev = dev
            alerts = []
            try:
                r2 = urllib.request.Request(f"{GE_API_BASE}/v2/device/{did}", headers=hdr)
                with urllib.request.urlopen(r2, timeout=8) as resp:
                    result_dev = json.loads(resp.read())
            except Exception:
                pass
            try:
                # ?status=triggered → only currently-active alerts; cleared alerts are excluded.
                # This is the correct way per the Digital Twin API spec — no need for
                # lastAlertTime age filtering, the server only sends what's live right now.
                r3 = urllib.request.Request(f"{GE_API_BASE}/v2/device/{did}/alert?status=triggered", headers=hdr)
                with urllib.request.urlopen(r3, timeout=8) as resp:
                    alert_data = json.loads(resp.read())
                    alerts = alert_data.get("alerts", [])
            except Exception:
                pass
            return result_dev, alerts

        with _cf.ThreadPoolExecutor(max_workers=4) as ex:
            fetch_results = list(ex.map(_fetch_device, devices))
        full_devices = [(r[0], r[1]) for r in fetch_results]

        appliances = []
        for dev, dev_alerts in full_devices:
            did = dev.get("deviceId", "")
            dev_type = dev.get("deviceType", "").lower()
            nickname = dev.get("nickname") or dev.get("name") or "GE Appliance"
            model = dev.get("model", "")
            brand = dev.get("brand", "GE")
            presence = dev.get("presence", "OFFLINE").upper()
            services = dev.get("services", [])

            # Infer friendly type
            if "refrigerator" in dev_type:
                app_type = "Refrigerator"
            elif "dishwasher" in dev_type:
                app_type = "Dishwasher"
            elif "washer" in dev_type:
                app_type = "Clothes Washer"
            elif "dryer" in dev_type:
                app_type = "Clothes Dryer"
            elif "range" in dev_type or "oven" in dev_type:
                app_type = "Range"
            else:
                app_type = dev_type.split(".")[-1].replace("_", " ").title()

            icon = _GE_TYPE_ICON.get(app_type, "&#127968;")

            if presence != "ONLINE":
                telemetry = {"state": "disconnected", "cycle": "", "door": "", "temp": "",
                             "attrs": [], "est_watts": 0}
            else:
                telemetry = _ge_parse_services(services, dev_type)

            state_str = telemetry["state"]
            # For refrigerators, show door state instead of "idle"
            if "refrigerator" in dev_type and state_str == "idle":
                state_str = "Door Open" if telemetry.get("door") == "Open" else "Online"
            est_watts = _GE_WATT_ESTIMATE.get(app_type, 200) if state_str == "running" else 0
            telemetry["est_watts"] = est_watts

            # Track state transitions with cycle history
            prev = _ge_state_history.get(did, {})
            prev_state = prev.get("state")
            if did not in _ge_state_history:
                _ge_state_history[did] = {
                    "state": state_str, "changed_at": now,
                    "cycle_events": [], "cycle_started": 0.0,
                }
            hist = _ge_state_history[did]
            if prev_state != state_str:
                hist["changed_at"] = now
                hist["state"] = state_str
                # Record completed cycle when transitioning out of running
                if prev_state == "running" and state_str in ("idle", "end of cycle", "standby"):
                    cs = hist.get("cycle_started", 0.0)
                    if cs > 0:
                        hist.setdefault("cycle_events", []).append({"started": cs, "ended": now})
                        hist["cycle_events"] = hist["cycle_events"][-20:]
                # Record cycle start
                if state_str == "running":
                    hist["cycle_started"] = now
            changed_at = hist.get("changed_at", now)
            # Compute daily stats (UTC day boundary)
            today_start = now - (now % 86400)
            today_events = [e for e in hist.get("cycle_events", []) if e["started"] >= today_start]
            cycles_today = len(today_events)
            daily_runtime_mins = int(sum((e["ended"] - e["started"]) / 60 for e in today_events))
            all_ev = hist.get("cycle_events", [])
            last_cycle_end = max((e["ended"] for e in all_ev), default=0.0) if all_ev else 0.0

            # Parse active alerts
            _GE_ALERT_LABELS = {
                'door.open.freshfood': '🚪 Fresh Food Door Open',
                'door.open.freezer': '🚪 Freezer Door Open',
                'door.alarm.freshfood': '🔔 Fresh Food Door Alarm',
                'door.alarm.freezer': '🔔 Freezer Door Alarm',
                'door.alarm.convertiblecompartment': '🔔 Drawer Door Alarm',
                'filter.replace.XWFE': '⚠️ Replace Water Filter (XWFE)',
                'filter.order.XWFE': '🛒 Order Water Filter (XWFE)',
                'icemaker.full.freezer': '🧊 Ice Bin Full',
                'temperature.high.freezer': '🌡️ Freezer Temp High',
                'temperature.high.freshfood': '🌡️ Fresh Food Temp High',
                'leakdetected': '💧 Leak Detected',
                'leakdetected.pitcher': '💧 Pitcher Leak Detected',
            }
            import time as _time
            _now = _time.time()
            alert_attrs = []
            for al in dev_alerts:
                atype = al.get("alertType","").replace("cloud.smarthq.alert.","")

                # ── Suppress by age (24h) ──────────────────────────────────────
                # GE never auto-clears alerts — ?status=triggered just means "ever
                # fired and never explicitly DELETE'd". So we still need age gating.
                last_time_str = al.get("lastAlertTime", "")
                if last_time_str:
                    try:
                        import datetime as _dt
                        lt = _dt.datetime.fromisoformat(last_time_str.replace("Z", "+00:00")).timestamp()
                        if (_now - lt) > 86400:
                            continue  # alert is older than 24h — skip
                    except Exception:
                        pass

                # ── Suppress door.open if live telemetry says door is Closed ──
                # The fridge reports door state every poll; if it's Closed the
                # door.open alert is stale regardless of lastAlertTime.
                if "door.open" in atype and telemetry.get("door") == "Closed":
                    continue

                # ── Suppress always-normal conditions ─────────────────────────
                # Ice Bin Full is expected/good — not an alert.
                if "icemaker" in atype and "full" in atype:
                    continue

                # ── Suppress cycle-noise and idle-machine alerts ───────────────
                # These alert types are informational/completion events, not faults.
                # Also suppress ALL of them when the appliance is currently idle —
                # if the machine is empty, any cycle-related alert is from a past run.
                _cycle_noise = ["endofcycle", "otaupdate", "pausedcycle", "cyclefeedback",
                                "selfclean", "minutesleft", "minutesafter", "tankdetergent",
                                "damp"]  # "damp" = clothes still damp at end of cycle
                atype_key = atype.lower().replace(".", "").replace(" ", "")
                is_cycle_alert = any(s in atype_key for s in _cycle_noise)
                if is_cycle_alert:
                    continue
                # If appliance is idle, suppress any remaining cycle-related hints
                if state_str == "idle" and any(s in atype_key for s in [
                        "endof", "cycle", "damp", "remaining", "complete"]):
                    continue

                label = _GE_ALERT_LABELS.get(atype, None)
                if label is None:
                    label = "⚠️ " + atype.replace(".", " ").title()
                alert_attrs.append({"label": "🔔 Alert", "value": label, "unit": ""})

            all_attrs = alert_attrs + telemetry.get("attrs", [])

            appliances.append({
                "id": did,
                "name": nickname,
                "type": app_type,
                "icon": icon,
                "model": model,
                "brand": brand,
                "state": state_str,
                "cycle": telemetry.get("cycle", ""),
                "door": telemetry.get("door", ""),
                "temp": telemetry.get("temp", ""),
                "attrs": all_attrs[:12],
                "est_watts": est_watts,
                "state_changed_at": changed_at,
                "remote_enabled": False,
                "seconds_remaining": telemetry.get("seconds_remaining", 0),
                "cycle_started": hist.get("cycle_started", 0.0) if state_str == "running" else 0.0,
                "cycles_today": cycles_today,
                "last_cycle_end": last_cycle_end,
                "daily_runtime_mins": daily_runtime_mins,
            })

        with _state_lock:
            _state["ge_appliances"] = {
                "status": "online",
                "appliances": appliances,
                "last_seen": now,
            }
        log.info("GE SmartHQ polled OK — %d appliance(s)", len(appliances))
        return True

    except Exception as e:
        log.warning("GE SmartHQ poll error: %s", e)
        _ge_next_retry = time.time() + 120
        with _state_lock:
            _state["ge_appliances"]["status"] = "error"
        return False


# ─── MyQ Garage Door ──────────────────────────────────────────────────────────
_myq_next_retry = 0.0


async def _myq_fetch_doors():
    """Async: log in to MyQ and return list of cover (garage door) dicts."""
    import aiohttp
    import pymyq
    async with aiohttp.ClientSession() as session:
        api = await pymyq.login(MYQ_EMAIL, MYQ_PASSWORD, session)
        doors = []
        for serial, dev in api.covers.items():
            doors.append({
                "serial": serial,
                "name": dev.name or "Garage Door",
                "state": dev.state or "unknown",
                "online": dev.online,
            })
        return doors


def poll_myq():
    global _myq_next_retry
    if not MYQ_EMAIL or not MYQ_PASSWORD:
        with _state_lock:
            _state["myq"]["status"] = "unconfigured"
        return False
    if time.time() < _myq_next_retry:
        return False
    try:
        doors = _run_async(_myq_fetch_doors())
        with _state_lock:
            _state["myq"] = {
                "status": "online",
                "doors": doors,
                "last_seen": time.time(),
            }
        log.info("MyQ: %d door(s) polled", len(doors))
        return True
    except Exception as e:
        log.warning("MyQ poll error: %s", e)
        _myq_next_retry = time.time() + 120  # 2-min backoff
        with _state_lock:
            _state["myq"]["status"] = "error"
        return False


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  POLLING LOOP                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def _poll_loop():
    import concurrent.futures
    global _camera_poll_counter, _ge_poll_counter, _telemetry_log_counter, _daily_agg_counter
    log.info("Polling loop started (interval=%ds, parallel)", POLL_INTERVAL_SECONDS)
    _camera_poll_counter = 11  # trigger camera poll on first tick
    _ge_poll_counter = 11      # trigger GE appliance poll on first tick
    _nest_poll_counter = 11    # trigger Nest poll on first tick (every 60s — SDM API rate limit)
    _roku_poll_counter = 5     # trigger Roku poll every 30s (6 ticks × 5s)
    _telemetry_log_counter = 11   # trigger telemetry log every 60s (12 ticks × 5s)
    _daily_agg_counter = 0        # trigger daily aggregation every 24h

    # Pentair runs in its own background thread (takes ~45s) — never blocks fast polls
    _pentair_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pentair-slow")
    _pentair_future = [None]

    def _submit_pentair():
        if _pentair_future[0] is None or _pentair_future[0].done():
            _pentair_future[0] = _pentair_executor.submit(poll_pentair)

    _submit_pentair()  # kick off first pentair poll immediately

    while True:
        _camera_poll_counter += 1
        _ge_poll_counter += 1
        _nest_poll_counter += 1
        _roku_poll_counter += 1

        # Fast polls — these must all complete quickly (< 3s each)
        fast_fns = [poll_span, poll_enphase, poll_tesla, poll_wall_connector, poll_bhyve, poll_myq]
        if _nest_poll_counter >= 12:
            fast_fns.append(poll_nest)
            _nest_poll_counter = 0
        if _camera_poll_counter >= 12:
            fast_fns.append(poll_cameras)
            _camera_poll_counter = 0
        if _ge_poll_counter >= 6:
            fast_fns.append(poll_ge_appliances)
            _ge_poll_counter = 0
        if _roku_poll_counter >= 6:
            fast_fns.append(poll_roku)
            _roku_poll_counter = 0

        # Run fast polls concurrently with a tight timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(f) for f in fast_fns]
            concurrent.futures.wait(futs, timeout=8)

        # Broadcast SSE immediately after fast polls — don't wait for Pentair
        try:
            _update_summary()
        except Exception as _sum_err:
            log.error("_update_summary() crashed: %s", _sum_err, exc_info=True)
        _broadcast_sse()

        # Log telemetry for analytics (every 60s)
        _telemetry_log_counter += 1
        if _telemetry_log_counter >= 12:
            try:
                log_telemetry(_state)
                compute_hourly_aggregates()
            except Exception as _tel_err:
                log.debug("Telemetry logging error: %s", _tel_err)
            _telemetry_log_counter = 0

        # Compute daily aggregates (every 24h)
        _daily_agg_counter += 1
        if _daily_agg_counter >= 17280:  # 86400s / 5s = 17280 ticks
            try:
                compute_daily_aggregates()
            except Exception as _agg_err:
                log.debug("Daily aggregation error: %s", _agg_err)
            _daily_agg_counter = 0

        # Re-submit Pentair poll if previous one finished
        _submit_pentair()

        time.sleep(POLL_INTERVAL_SECONDS)


def _broadcast_sse():
    with _state_lock:
        payload = json.dumps(_state)
    event = f"data: {payload}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(event)
            except Exception:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  FLASK ROUTES                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@app.route("/")
def index():
    import time
    html = DASHBOARD_HTML.replace('<style>', f'<style>/* v{int(time.time())} */')
    resp = make_response(render_template_string(html))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@app.route("/api/state")
def api_state():
    with _state_lock:
        return jsonify(_state)


@app.route("/api/energy-state")
def api_energy_state():
    """Snapshot endpoint for tablet dashboard modes."""
    with _state_lock:
        return jsonify(_state)


@app.route("/api/stream")
def api_stream():
    import queue
    q = queue.Queue(maxsize=10)
    with _sse_lock:
        _sse_subscribers.append(q)

    def generate():
        try:
            # Send current state immediately
            with _state_lock:
                yield f"data: {json.dumps(_state)}\n\n"
            while True:
                try:
                    event = q.get(timeout=30)
                    yield event
                except Exception:
                    yield ": keepalive\n\n"
        finally:
            with _sse_lock:
                try:
                    _sse_subscribers.remove(q)
                except ValueError:
                    pass

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/pentair/set", methods=["POST"])
def api_pentair_set():
    body = request.get_json()
    objnam = body.get("objnam")
    params = body.get("params")
    if not objnam or not params:
        return jsonify({"error": "missing objnam or params"}), 400
    try:
        resp = pentair_set(objnam, params)
        # Optimistically update local state so UI reflects change immediately
        status = params.get("STATUS")
        if status:
            with _state_lock:
                for c in _state.get("pentair", {}).get("circuits", []):
                    if c.get("id") == objnam:
                        c["status"] = status
                        break
                # If turning off pool or cleaner, also update pump display
                if status == "OFF" and objnam in ("C0006", "FTR01"):
                    pump = _state.get("pentair", {}).get("pump", {})
                    # Will be corrected by next real poll; mark as stopping
                    pump["power_w"] = 0
                    pump["rpm"] = 0
        # Broadcast SSE immediately so UI updates without waiting for next Pentair poll
        try:
            _update_summary()
            _broadcast_sse()
        except Exception:
            pass
        return jsonify({"ok": True, "response": resp})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/span/circuit/<circuit_id>", methods=["POST"])
def api_span_circuit(circuit_id):
    if not SPAN_TOKEN:
        return jsonify({"error": "SPAN token not configured"}), 403
    body = request.get_json()
    relay_state = body.get("relayState")
    url = f"http://{SPAN_HOST}/api/v1/circuits/{circuit_id}"
    data = json.dumps({"relayStateIn": {"relayState": relay_state}}).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Authorization": f"Bearer {SPAN_TOKEN}",
                                           "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return jsonify({"ok": True, "response": json.loads(r.read())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config/device-ip", methods=["POST"])
def api_config_device_ip():
    """Update a device IP address at runtime and persist to config.py."""
    import re as _re
    body = request.get_json() or {}
    device = body.get("device", "").strip()
    new_ip  = body.get("ip", "").strip()
    if not _re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', new_ip):
        return jsonify({"error": "Invalid IP address"}), 400
    device_map = {
        "pentair": "PENTAIR_HOST",
        "span":    "SPAN_HOST",
    }
    if device not in device_map:
        return jsonify({"error": f"Unknown device: {device}"}), 400
    var_name = device_map[device]
    import sys as _sys
    _mod = _sys.modules[__name__]
    setattr(_mod, var_name, new_ip)
    globals()[var_name] = new_ip
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
    try:
        with open(config_path, "r") as f:
            content = f.read()
        new_content = _re.sub(
            rf'^({var_name}\s*=\s*")[^"]*(")',
            rf'\g<1>{new_ip}\g<2>',
            content,
            flags=_re.MULTILINE
        )
        with open(config_path, "w") as f:
            f.write(new_content)
        log.info(f"[Config] Updated {var_name} → {new_ip}")
        return jsonify({"ok": True, "device": device, "ip": new_ip})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/myq/door/<serial>/open", methods=["POST"])
def api_myq_open(serial):
    if not MYQ_EMAIL or not MYQ_PASSWORD:
        return jsonify({"error": "MyQ not configured"}), 403
    async def _do():
        import aiohttp
        import pymyq
        async with aiohttp.ClientSession() as session:
            api = await pymyq.login(MYQ_EMAIL, MYQ_PASSWORD, session)
            dev = api.covers.get(serial)
            if not dev:
                raise ValueError(f"Door serial {serial!r} not found")
            await dev.open(wait_for_state=False)
    try:
        _run_async(_do())
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/myq/door/<serial>/close", methods=["POST"])
def api_myq_close(serial):
    if not MYQ_EMAIL or not MYQ_PASSWORD:
        return jsonify({"error": "MyQ not configured"}), 403
    async def _do():
        import aiohttp
        import pymyq
        async with aiohttp.ClientSession() as session:
            api = await pymyq.login(MYQ_EMAIL, MYQ_PASSWORD, session)
            dev = api.covers.get(serial)
            if not dev:
                raise ValueError(f"Door serial {serial!r} not found")
            await dev.close(wait_for_state=False)
    try:
        _run_async(_do())
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/roku")
def api_roku():
    return jsonify(poll_roku())

@app.route("/api/roku/<ip>/keypress/<key>", methods=["POST"])
def api_roku_keypress(ip, key):
    ok = _roku_post(ip, f"/keypress/{key}")
    _roku_cache['ts'] = 0
    return jsonify({"ok": ok})

@app.route("/api/roku/<ip>/launch/<app_id>", methods=["POST"])
def api_roku_launch(ip, app_id):
    ok = _roku_post(ip, f"/launch/{app_id}")
    _roku_cache['ts'] = 0
    return jsonify({"ok": ok})


@app.route("/api/tesla/set_password", methods=["POST"])
def api_tesla_set_password():
    global TESLA_PASSWORD
    body = request.get_json()
    password = (body.get("password") or "").strip()
    if not password:
        return jsonify({"ok": False, "error": "password is required"}), 400

    # Write new password into config.py in-place
    config_path = Path(__file__).parent / "config.py"
    try:
        import re as _re
        text = config_path.read_text()
        new_text = _re.sub(
            r'^TESLA_PASSWORD\s*=\s*.*$',
            f'TESLA_PASSWORD = "{password}"',
            text,
            flags=_re.MULTILINE,
        )
        config_path.write_text(new_text)
        TESLA_PASSWORD = password
    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed to write config: {e}"}), 500

    # Attempt a fresh login with the new password
    try:
        _tesla_login()
        with _state_lock:
            status = _state["tesla"]["status"]
        return jsonify({"ok": True, "status": status})
    except Exception as e:
        with _state_lock:
            _state["tesla"]["status"] = "error"
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/camera/<cam_id>/snapshot")
def camera_snapshot(cam_id):
    try:
        if cam_id.startswith('ring_'):
            return '', 204  # legacy ring_ cam_id — use /api/ring/snapshot instead
        else:
            # Wyze — proxy thumbnail URL cached during last poll
            with _state_lock:
                cam_data = next((c for c in _state['cameras']
                                 if c.get('mac') == cam_id and c.get('type') == 'wyze'), None)
            if cam_data and cam_data.get('thumbnail_url'):
                # Wyze CDN may require auth; try with no-verify first then accept any 2xx
                try:
                    r = _requests.get(cam_data['thumbnail_url'], timeout=8,
                                      headers={"User-Agent": "WyzeAndroid/2.47.0"})
                    if r.status_code == 200 and r.content:
                        ct = r.headers.get('Content-Type', 'image/jpeg')
                        return Response(r.content, mimetype=ct if 'image' in ct else 'image/jpeg')
                except Exception:
                    pass
    except Exception as e:
        log.warning("Snapshot error for %s: %s", cam_id, e)
    return '', 204


@app.route("/api/ring/snapshot")
def ring_snapshot_route():
    """Return the latest cached Ring doorbell snapshot as JPEG."""
    with _ring_snap_lock:
        img = bytes(_ring_snap_bytes)
    if not img:
        return '', 204
    resp = Response(img, mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'no-cache, no-store'
    return resp


@app.route("/api/ring/events")
def ring_events_sse():
    """SSE stream: push Ring ding/motion events to the browser."""
    def generate():
        last_seen = time.time()
        ticker = 0
        while True:
            with _ring_evts_lock:
                new_evts = [e for e in _ring_evts if e["ts"] > last_seen]
            for evt in sorted(new_evts, key=lambda x: x["ts"]):
                yield f"data: {json.dumps(evt)}\n\n"
                last_seen = max(last_seen, evt["ts"])
            time.sleep(1)
            ticker += 1
            if ticker % 30 == 0:
                yield ": keepalive\n\n"
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/ring/status")
def ring_status_route():
    """Return Ring doorbell status (device health, connectivity, etc.)."""
    with _ring_status_lock:
        status = dict(_ring_status)
    return jsonify(status)


@app.route("/api/ring/history")
def ring_history_route():
    """Return recent Ring events (dings, motion, on_demand) up to 30 events."""
    with _ring_history_lock:
        history = list(_ring_history_cache)

    # Transform history to include duration and recording_ready flags
    events = []
    for evt in history:
        events.append({
            "id": evt.get("id"),
            "kind": evt.get("kind"),
            "created_at": evt.get("created_at"),
            "answered": evt.get("answered", False),
            "duration": evt.get("duration", 0),
            "recording_ready": (evt.get("recording", {}) or {}).get("status") == "ready",
        })
    return jsonify(events)


@app.route("/api/ring/webrtc_offer", methods=["POST"])
def ring_webrtc_offer():
    """WebRTC signaling proxy: relay SDP offer to Ring, return SDP answer.
    POST body: {"offer": "<SDP offer string>"}
    Returns:   {"answer": "<SDP answer string>", "session_id": "..."}

    Uses direct aiohttp + Ring WebSocket signaling to avoid event-loop binding issues
    with the poller's Ring device object.
    """
    import asyncio, uuid as _uuid, ssl, json as _json
    data = request.get_json(silent=True) or {}
    offer_sdp = data.get("offer", "")
    if not offer_sdp:
        return jsonify({"error": "Missing 'offer' field"}), 400

    # Get current access token
    tok = _ring_token_data or {}
    access_token = tok.get("access_token", "")
    if not access_token:
        return jsonify({"error": "No Ring access token available"}), 503

    session_id = str(_uuid.uuid4())
    dialog_id  = str(_uuid.uuid4())
    device_id  = 4662242

    TICKET_URL = "https://prd-api-us.prd.rings.solutions/api/v1/clap/ticket/request/signalsocket"
    WS_URL_TPL = "wss://api.prod.signalling.ring.devices.a2z.com:443/ws?api_version=4.0&auth_type=ring_solutions&client_id=ring_site-{0}&token={1}"
    SDP_TIMEOUT = 20

    async def _do_webrtc_direct():
        import aiohttp
        from websockets.asyncio.client import connect as ws_connect

        ssl_ctx = ssl.create_default_context()
        hdrs = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
            "User-Agent":    "android:com.ringapp",
        }

        async with aiohttp.ClientSession(headers=hdrs) as sess:
            # 1. Get signaling ticket
            async with sess.post(TICKET_URL) as resp:
                body = await resp.json()
                ticket = body.get("ticket")
                if not ticket:
                    raise RuntimeError(f"No ticket in response: {body}")

        # 2. Connect to Ring WebSocket signaling server
        ws_uri = WS_URL_TPL.format(_uuid.uuid4(), ticket)
        sdp_answer = None
        ice_candidates = []

        async with ws_connect(ws_uri, user_agent_header="android:com.ringapp", ssl=ssl_ctx) as ws:
            # 3. Send SDP offer
            offer_msg = _json.dumps({
                "method": "live_view",
                "dialog_id": dialog_id,
                "body": {
                    "doorbot_id": device_id,
                    "stream_options": {"audio_enabled": True, "video_enabled": True},
                    "sdp": offer_sdp,
                    "type": "offer",
                },
            })
            await ws.send(offer_msg)

            # 4. Wait for SDP answer + ICE candidates
            import asyncio as _aio
            deadline = _aio.get_event_loop().time() + SDP_TIMEOUT
            while _aio.get_event_loop().time() < deadline:
                try:
                    raw = await _aio.wait_for(ws.recv(), timeout=3)
                    msg = _json.loads(raw)
                    method = msg.get("method", "")
                    body   = msg.get("body", {})
                    if method in ("sdp", "live_view") and body.get("type") == "answer":
                        sdp_answer = body.get("sdp")
                    elif method == "ice":
                        cand = body.get("ice", "")
                        sdp_mid = body.get("sdpMid", "0")
                        sdp_mline = body.get("sdpMLineIndex", 0)
                        if cand:
                            ice_candidates.append((cand, sdp_mid, sdp_mline))
                    elif method == "close":
                        break
                    if sdp_answer and len(ice_candidates) >= 2:
                        break
                except _aio.TimeoutError:
                    if sdp_answer:
                        break

            # Close gracefully
            await ws.send(_json.dumps({
                "method": "close",
                "dialog_id": dialog_id,
                "body": {"reason": {"code": 0}},
            }))

        if not sdp_answer:
            raise RuntimeError("Ring did not return an SDP answer within timeout")

        # Inject ICE candidates into the SDP answer
        if ice_candidates:
            lines = sdp_answer.splitlines()
            out = []
            for line in lines:
                out.append(line)
                if line.startswith("a=mid:"):
                    mid = line[6:]
                    for cand, smid, _ in ice_candidates:
                        if smid == mid:
                            out.append(f"a={cand}")
            sdp_answer = "\r\n".join(out) + "\r\n"

        return sdp_answer

    try:
        answer_sdp = asyncio.run(_do_webrtc_direct())
        return jsonify({"answer": answer_sdp, "session_id": session_id})
    except Exception as e:
        log.warning("Ring WebRTC proxy error: %s", e)
        return jsonify({"error": str(e)}), 502


@app.route("/api/ring/webrtc_close", methods=["POST"])
def ring_webrtc_close():
    """No-op — WebRTC sessions are closed client-side."""
    return jsonify({"ok": True})


@app.route("/api/ring/webrtc_proxy", methods=["POST"])
def ring_webrtc_proxy():
    """Proxy WebRTC SDP offer to go2rtc (avoids browser CORS restriction)."""
    import urllib.request as _ur
    try:
        sdp = request.get_data()
        req = _ur.Request(
            "http://127.0.0.1:8558/api/webrtc?src=9884e3d2f0af_live",
            data=sdp,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST"
        )
        with _ur.urlopen(req, timeout=15) as resp:
            answer_sdp = resp.read().decode()
        return answer_sdp, 200, {"Content-Type": "application/sdp"}
    except Exception as e:
        log.warning("WebRTC proxy error: %s", e)
        return str(e), 502


@app.route("/ring")
def ring_page():
    """Ring doorbell page with live status, device info, recent events, and real-time ding popup."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ring Doorbell — Jarvis Home</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: #e0e0e0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            height: 100vh;
            overflow-y: auto;
        }

        .container {
            display: flex;
            flex-direction: column;
            min-height: 100vh;
            gap: 16px;
            padding: 16px;
        }

        /* ── Header ────────────────────────────────────────────────────── */
        .header {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            backdrop-filter: blur(12px);
            border: 1px solid rgba(0, 255, 136, 0.2);
            flex-shrink: 0;
        }

        .header-icon { font-size: 24px; }
        .header-main {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .device-name {
            font-size: 18px;
            font-weight: 600;
            color: #fff;
        }
        .header-subtitle {
            font-size: 11px;
            color: #999;
            letter-spacing: 0.3px;
        }

        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #00ff88;
            box-shadow: 0 0 8px rgba(0, 255, 136, 0.5);
            animation: pulse 2s ease-in-out infinite;
        }
        .status-dot.offline {
            background: #ff4444;
            box-shadow: 0 0 8px rgba(255, 68, 68, 0.5);
            animation: none;
        }

        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }

        /* ── Content (2-column + activity) ────────────────────────────── */
        .content {
            display: flex;
            gap: 16px;
            flex: 1;
            min-height: 320px;
        }

        /* Status Panels */
        .panel {
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 12px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(0, 255, 136, 0.15);
            border-radius: 6px;
            flex-shrink: 0;
        }

        .panel-title {
            font-size: 11px;
            font-weight: 600;
            color: #00ff88;
            text-transform: uppercase;
            letter-spacing: 0.4px;
        }

        .stat-row {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            font-size: 12px;
            gap: 8px;
        }

        .stat-label { color: #888; }
        .stat-value { color: #fff; font-weight: 500; }

        /* Activity List */
        .activity-section {
            display: flex;
            flex-direction: column;
            gap: 6px;
            flex: 1;
            overflow: hidden;
        }

        .activity-title {
            font-size: 11px;
            font-weight: 600;
            color: #00ff88;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            flex-shrink: 0;
        }

        .activity-list {
            flex: 1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 6px;
            padding-right: 6px;
        }

        .activity-list::-webkit-scrollbar {
            width: 5px;
        }
        .activity-list::-webkit-scrollbar-track {
            background: rgba(255, 255, 255, 0.03);
            border-radius: 2px;
        }
        .activity-list::-webkit-scrollbar-thumb {
            background: rgba(0, 255, 136, 0.25);
            border-radius: 2px;
        }

        .activity-item {
            background: rgba(255, 255, 255, 0.02);
            padding: 8px 10px;
            border-radius: 5px;
            border-left: 2px solid #00ff88;
            font-size: 11px;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: background 0.15s;
        }

        .activity-item.motion {
            border-left-color: #ffaa00;
        }

        .activity-item:hover {
            background: rgba(255, 255, 255, 0.04);
        }

        .activity-icon {
            font-size: 13px;
            flex-shrink: 0;
        }

        .activity-info {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 1px;
        }

        .activity-type {
            color: #aaa;
            font-size: 10px;
        }

        .activity-time {
            color: #00ff88;
            font-weight: 500;
            font-size: 11px;
        }

        .activity-reltime {
            color: #666;
            font-size: 10px;
        }

        /* ── Ding Popup ────────────────────────────────────────────────── */
        .ding-popup {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.85);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 9999;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s;
        }

        .ding-popup.show {
            opacity: 1;
            pointer-events: auto;
        }

        .ding-content {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 24px;
            text-align: center;
            animation: dingScale 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
        }

        @keyframes dingScale {
            from { transform: scale(0.7); opacity: 0; }
            to { transform: scale(1); opacity: 1; }
        }

        .ding-icon {
            font-size: 100px;
            animation: dingBounce 0.5s ease-in-out infinite;
        }

        @keyframes dingBounce {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-15px); }
        }

        .ding-text {
            font-size: 44px;
            font-weight: 700;
            color: #00ff88;
            letter-spacing: 1px;
        }

        .ding-subtitle {
            font-size: 22px;
            color: #ddd;
        }

        .ding-timestamp {
            font-size: 13px;
            color: #888;
        }

        .ding-countdown {
            font-size: 12px;
            color: #666;
            margin-top: 16px;
        }

        /* ── Live Video Stream ──────────────────────────────────────── */
        .video-section {
            display: flex;
            flex-direction: column;
            gap: 8px;
            flex-shrink: 0;
        }

        .video-controls {
            display: flex;
            gap: 8px;
            justify-content: space-between;
            align-items: center;
        }

        .video-btn {
            padding: 8px 16px;
            background: rgba(0, 255, 136, 0.15);
            border: 1px solid rgba(0, 255, 136, 0.4);
            color: #00ff88;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 500;
            transition: all 0.2s;
        }

        .video-btn:hover {
            background: rgba(0, 255, 136, 0.25);
            box-shadow: 0 0 12px rgba(0, 255, 136, 0.3);
        }

        .video-btn.close {
            padding: 4px 12px;
            background: rgba(255, 100, 100, 0.15);
            border-color: rgba(255, 100, 100, 0.4);
            color: #ff6464;
        }

        .video-btn.close:hover {
            background: rgba(255, 100, 100, 0.25);
            box-shadow: 0 0 12px rgba(255, 100, 100, 0.3);
        }

        #streamArea {
            display: none;
            border-radius: 8px;
            overflow: hidden;
            background: #000;
            height: 260px;
            border: 1px solid rgba(0, 255, 136, 0.2);
            flex-shrink: 0;
        }

        #streamArea.show {
            display: block;
        }

        #streamFrame {
            width: 100%;
            height: 100%;
            border: none;
            background: #000;
        }

        @media (max-width: 1200px) {
            .content { flex-direction: column; }
            .panel { width: 100%; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-icon">🔔</div>
            <div class="header-main">
                <div class="device-name" id="headerName">Front Door</div>
                <div class="header-subtitle" id="headerStats">Battery 100% • WiFi -42dBm • AC Wired</div>
            </div>
            <div class="status-dot" id="statusDot"></div>
        </div>

        <div class="video-section">
            <div class="video-controls">
                <span style="color: #888; font-size: 12px;">Live Video Stream</span>
                <button class="video-btn" id="toggleStreamBtn" onclick="toggleStream()">&#9654; View Live</button>
            </div>
            <div id="streamArea" style="width:100%;">
                <iframe id="streamFrame" src="about:blank"
                  allow="autoplay; camera; microphone; display-capture"
                  allowfullscreen
                  style="width:100%;height:260px;border:none;border-radius:6px;background:#000;display:block;">
                </iframe>
            </div>
        </div>

        <div class="content">
            <div class="panel" style="width: 240px;">
                <div class="panel-title">Live Status</div>
                <div class="stat-row">
                    <span class="stat-label">Last Ding:</span>
                </div>
                <div id="lastDingInfo" style="font-size: 11px; color: #888;">—</div>
                <div class="stat-row" style="margin-top: 6px;">
                    <span class="stat-label">Answered:</span>
                    <span class="stat-value" id="lastAnswered">—</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Duration:</span>
                    <span class="stat-value" id="lastDuration">—</span>
                </div>
            </div>

            <div class="panel" style="width: 240px;">
                <div class="panel-title">Device Status</div>
                <div class="stat-row">
                    <span class="stat-label">Firmware:</span>
                    <span class="stat-value" id="firmware">—</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Uptime:</span>
                    <span class="stat-value" id="uptime">—</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">WiFi:</span>
                    <span class="stat-value" id="wifiName">—</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Packet Loss:</span>
                    <span class="stat-value" id="packetLoss">—</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Signal:</span>
                    <span class="stat-value" id="signal">—</span>
                </div>
            </div>

            <div class="activity-section">
                <div class="activity-title">Recent Activity</div>
                <div class="activity-list" id="activityList">
                    <div style="color: #555; text-align: center; padding: 16px; font-size: 11px;">Loading events...</div>
                </div>
            </div>
        </div>
    </div>

    <div class="ding-popup" id="dingPopup">
        <div class="ding-content">
            <div class="ding-icon">🔔</div>
            <div>
                <div class="ding-text">DING DONG</div>
                <div class="ding-subtitle" id="dingDevice">Front Door</div>
                <div class="ding-timestamp" id="dingTime"></div>
            </div>
        </div>
        <div style="display:flex;gap:10px;justify-content:center;margin-top:8px">
            <button onclick="showStream();document.getElementById('dingPopup').classList.remove('show');clearTimeout(dingPopupTimer)"
              style="padding:10px 24px;background:#22c55e;color:#000;border:none;border-radius:8px;font-size:0.95rem;font-weight:700;cursor:pointer;touch-action:manipulation">
              ▶ View Live
            </button>
            <button onclick="document.getElementById('dingPopup').classList.remove('show');clearTimeout(dingPopupTimer)"
              style="padding:10px 24px;background:rgba(255,255,255,0.15);color:#fff;border:1px solid rgba(255,255,255,0.3);border-radius:8px;font-size:0.95rem;cursor:pointer;touch-action:manipulation">
              Dismiss
            </button>
        </div>
        <div class="ding-countdown" id="dingCountdown" style="margin-top:6px">Dismiss in 15s</div>
    </div>

    <script>
        const PAGE_LOAD_TIME = Date.now() / 1000;
        let events = [];
        let status = {};
        let lastHistoryFetch = 0;
        let streamOpen = false;

        // ── Format Helpers ────────────────────────────────────────────
        function formatAbsTime(ts) {
            const dt = new Date(ts * 1000);
            return dt.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
                   dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }

        function formatRelTime(ts) {
            const diff = (Date.now() / 1000) - ts;
            if (diff < 60) return 'just now';
            if (diff < 3600) return Math.floor(diff / 60) + 'min ago';
            if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
            if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
            return Math.floor(diff / 604800) + 'w ago';
        }

        function formatUptimeHours(hours) {
            if (hours < 24) return Math.floor(hours) + 'h';
            const d = Math.floor(hours / 24);
            const h = Math.floor(hours % 24);
            return d + 'd ' + h + 'h';
        }

        // ── Status Update ─────────────────────────────────────────────
        async function updateStatus() {
            try {
                const resp = await fetch('/api/ring/status');
                status = await resp.json();
                updateStatusUI();
            } catch (e) {
                console.error('Status fetch error:', e);
            }
        }

        function updateStatusUI() {
            // Header
            document.getElementById('headerName').textContent = status.device_name || 'Front Door';
            document.getElementById('headerStats').textContent =
                `Battery ${status.battery}% • WiFi ${status.rssi}dBm • ${status.ac_power ? 'AC Wired' : 'Battery'}`;

            // Status dot
            const dot = document.getElementById('statusDot');
            if (status.connected) {
                dot.classList.remove('offline');
            } else {
                dot.classList.add('offline');
            }

            // Device Status panel
            document.getElementById('firmware').textContent = status.firmware || '—';
            document.getElementById('uptime').textContent = formatUptimeHours(status.uptime_hours) || '—';
            document.getElementById('wifiName').textContent = status.wifi_name || '—';
            document.getElementById('packetLoss').textContent = (status.packet_loss || 0).toFixed(1) + '%';
            document.getElementById('signal').textContent = status.rssi_label + ' (' + status.rssi + 'dBm)';
        }

        // ── History Fetch ────────────────────────────────────────────
        async function updateHistory() {
            try {
                const resp = await fetch('/api/ring/history');
                const history = await resp.json();
                events = history.map(evt => ({
                    id: evt.id,
                    kind: evt.kind,
                    created_at: evt.created_at,
                    answered: evt.answered,
                    duration: evt.duration,
                    ts: new Date(evt.created_at).getTime() / 1000,
                }));
                renderEvents();
                updateLastDing();
            } catch (e) {
                console.error('History fetch error:', e);
            }
        }

        function updateLastDing() {
            const ding = events.find(e => e.kind === 'ding');
            if (!ding) {
                document.getElementById('lastDingInfo').textContent = '—';
                document.getElementById('lastAnswered').textContent = '—';
                document.getElementById('lastDuration').textContent = '—';
                return;
            }
            document.getElementById('lastDingInfo').textContent = formatAbsTime(ding.ts) + ' (' + formatRelTime(ding.ts) + ')';
            document.getElementById('lastAnswered').textContent = ding.answered ? '✓' : '✗';
            document.getElementById('lastDuration').textContent = Math.round(ding.duration) + 's';
        }

        function renderEvents() {
            const list = document.getElementById('activityList');
            if (!events.length) {
                list.innerHTML = '<div style="color: #555; text-align: center; padding: 16px; font-size: 11px;">No events yet</div>';
                return;
            }

            const sorted = [...events].sort((a, b) => b.ts - a.ts).slice(0, 30);
            list.innerHTML = sorted.map(evt => {
                const isMotion = evt.kind === 'motion';
                const icon = evt.kind === 'ding' ? '🔔' : (evt.kind === 'motion' ? '🚶' : '📱');
                const typeStr = evt.kind === 'ding' ? 'Ding' : (evt.kind === 'motion' ? 'Motion' : 'App View');
                const absTime = formatAbsTime(evt.ts);
                const relTime = formatRelTime(evt.ts);

                return `
                    <div class="activity-item ${isMotion ? 'motion' : ''}">
                        <span class="activity-icon">${icon}</span>
                        <div class="activity-info">
                            <div class="activity-type">${typeStr}${evt.answered ? ' ✓' : ''}${evt.duration ? ' · ' + Math.round(evt.duration) + 's' : ''}</div>
                            <div class="activity-time">${absTime}</div>
                        </div>
                        <div class="activity-reltime">${relTime}</div>
                    </div>
                `;
            }).join('');
        }

        // ── Live Stream Controls ──────────────────────────────────────
        let streamCheckTimer = null;

        async function checkStreamHealth() {
            try {
                const resp = await fetch('http://' + window.location.hostname + ':8558/api/streams');
                const data = await resp.json();
                const stream = data["9884e3d2f0af_live"];
                // If stream has no consumers after 5s, show setup notice
                if (!stream || !stream.consumers || stream.consumers.length === 0) {
                    document.getElementById('streamSetupNotice').style.display = 'block';
                }
            } catch (e) {
                document.getElementById('streamSetupNotice').style.display = 'block';
            }
        }

        const GO2RTC_STREAM_URL = 'http://' + window.location.hostname + ':8558/stream.html?src=9884e3d2f0af_live';

        function toggleStream() {
            const btn   = document.getElementById('toggleStreamBtn');
            const area  = document.getElementById('streamArea');
            const frame = document.getElementById('streamFrame');
            if (streamOpen) {
                frame.src = 'about:blank';
                area.classList.remove('show');
                btn.innerHTML = '&#9654; View Live';
                streamOpen = false;
            } else {
                frame.src = GO2RTC_STREAM_URL + '&ts=' + Date.now();
                area.classList.add('show');
                btn.innerHTML = '&#10005; Close Stream';
                streamOpen = true;
            }
        }

        function showStream() { if (!streamOpen) toggleStream(); }
        function hideStream() { if (streamOpen) toggleStream(); }

        // ── Ding Popup ────────────────────────────────────────────────
        let dingPopupTimer = null;

        function playDingSound() {
            try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                // 440Hz glide to 880Hz over 0.8s
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.frequency.setValueAtTime(440, ctx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.8);
                gain.gain.setValueAtTime(0.3, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.8);
                osc.start(ctx.currentTime);
                osc.stop(ctx.currentTime + 0.8);
            } catch (e) {}
        }

        function showDingPopup() {
            const popup = document.getElementById('dingPopup');
            clearTimeout(dingPopupTimer);

            popup.classList.add('show');
            showStream();  // Show live video when ding occurs
            playDingSound();

            let remaining = 15;
            function tick() {
                document.getElementById('dingCountdown').textContent = `Dismiss in ${remaining}s`;
                if (remaining <= 0) {
                    popup.classList.remove('show');
                    hideStream();  // Close audio/video when popup auto-dismisses
                    return;
                }
                remaining--;
                dingPopupTimer = setTimeout(tick, 1000);
            }
            tick();

            // Click to dismiss
            popup.onclick = () => {
                popup.classList.remove('show');
                hideStream();  // Close audio/video when manually dismissed
                clearTimeout(dingPopupTimer);
            };
        }

        // ── SSE Stream ────────────────────────────────────────────────
        let pageLoadTime = PAGE_LOAD_TIME;

        function connectSSE() {
            const src = new EventSource('/api/ring/events');
            src.onmessage = (e) => {
                try {
                    const evt = JSON.parse(e.data);
                    // Only show popup for events AFTER page load
                    if (evt.ts > pageLoadTime && evt.type === 'ding') {
                        showDingPopup();
                        updateHistory();  // Refresh history to get latest event
                    }
                } catch (err) {}
            };
            src.onerror = () => {
                src.close();
                setTimeout(connectSSE, 5000);
            };
        }

        // ── Init ──────────────────────────────────────────────────────
        document.addEventListener('DOMContentLoaded', () => {
            updateStatus();
            updateHistory();
            connectSSE();

            // Poll status every 30s
            setInterval(updateStatus, 30000);

            // Poll history every 60s
            setInterval(updateHistory, 60000);
        });
    </script>
</body>
</html>
"""
    return render_template_string(html)


# ── RTSP camera frame cache (background ffmpeg threads) ───────────────────────
_RTSP_CAM_URLS = {
    "front-side-cam": "rtsp://127.0.0.1:8554/front-side-cam",
    "upstairs-cam":   "rtsp://127.0.0.1:8554/upstairs-cam",
    "downstairs-cam": "rtsp://127.0.0.1:8554/downstairs-cam",
}
_rtsp_frame_cache: dict = {}        # cam_id → (jpeg_bytes, captured_at_epoch)
_rtsp_capture_threads: dict = {}
FRAME_MAX_AGE_S = 45                # serve 204 if frame older than this

def _rtsp_capture_loop(cam_id: str, rtsp_url: str):
    """Background thread: pull frames from wyze-bridge via ffmpeg, cache latest."""
    import subprocess as _sp, os as _os
    log.info("RTSP capture thread starting for %s", cam_id)
    while True:
        try:
            cmd = [
                'ffmpeg', '-loglevel', 'quiet',
                '-rtsp_transport', 'tcp',
                '-i', rtsp_url,
                '-vf', 'scale=640:-2',
                '-f', 'image2pipe',
                '-vcodec', 'mjpeg',
                '-q:v', '5',
                '-r', '0.5',   # 1 frame every 2s — fresh enough, low CPU
                'pipe:1',
            ]
            proc = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.DEVNULL, bufsize=0)
            buf = b''
            while True:
                chunk = _os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    s = buf.find(b'\xff\xd8')
                    if s == -1:
                        buf = buf[-4:]
                        break
                    e = buf.find(b'\xff\xd9', s + 2)
                    if e == -1:
                        break
                    _rtsp_frame_cache[cam_id] = (buf[s:e + 2], time.time())
                    buf = buf[e + 2:]
            proc.wait()
            log.info("RTSP ffmpeg exited for %s, reconnecting in 3s", cam_id)
        except Exception as exc:
            log.warning("RTSP capture error for %s: %s", cam_id, exc)
        time.sleep(3)

def _rtsp_watchdog():
    """Watchdog: respawn dead RTSP capture threads every 30s."""
    while True:
        time.sleep(30)
        for cam_id, rtsp_url in _RTSP_CAM_URLS.items():
            t = _rtsp_capture_threads.get(cam_id)
            if t is None or not t.is_alive():
                log.warning("RTSP watchdog: respawning thread for %s", cam_id)
                nt = threading.Thread(target=_rtsp_capture_loop, args=(cam_id, rtsp_url),
                                      daemon=True, name=f"rtsp-{cam_id}")
                nt.start()
                _rtsp_capture_threads[cam_id] = nt

def _start_rtsp_threads():
    for cam_id, rtsp_url in _RTSP_CAM_URLS.items():
        if cam_id not in _rtsp_capture_threads:
            t = threading.Thread(target=_rtsp_capture_loop, args=(cam_id, rtsp_url),
                                 daemon=True, name=f"rtsp-{cam_id}")
            t.start()
            _rtsp_capture_threads[cam_id] = t
    wd = threading.Thread(target=_rtsp_watchdog, daemon=True, name="rtsp-watchdog")
    wd.start()

@app.route("/api/camera/<cam_id>/frame")
def camera_frame(cam_id):
    """Return latest cached JPEG frame. Falls back to Wyze cloud snapshot if RTSP is stale/missing."""
    entry = _rtsp_frame_cache.get(cam_id)
    if entry:
        frame_bytes, captured_at = entry
        if time.time() - captured_at <= FRAME_MAX_AGE_S:
            resp = Response(frame_bytes, mimetype='image/jpeg')
            resp.headers['Cache-Control'] = 'no-cache, no-store'
            return resp
        else:
            log.debug("Stale frame for %s (%.0fs old), trying Wyze snapshot fallback", cam_id,
                      time.time() - captured_at)
    # Fallback: try Wyze cloud thumbnail for this camera
    _cam_name_to_rtsp = {v: k for k, v in {
        "front-side-cam": "front", "upstairs-cam": "upstairs", "downstairs-cam": "downstairs"
    }.items()}
    match_keyword = {"front-side-cam": "front", "upstairs-cam": "upstairs", "downstairs-cam": "downstairs"}.get(cam_id)
    if match_keyword:
        with _state_lock:
            cam_data = next((c for c in _state.get('cameras', [])
                             if match_keyword in (c.get('name', '') or '').lower()
                             and c.get('type') == 'wyze'), None)
        if cam_data and cam_data.get('thumbnail_url'):
            try:
                r = _requests.get(cam_data['thumbnail_url'], timeout=8,
                                  headers={"User-Agent": "WyzeAndroid/2.47.0"})
                if r.status_code == 200 and r.content:
                    ct = r.headers.get('Content-Type', 'image/jpeg')
                    resp = Response(r.content, mimetype=ct if 'image' in ct else 'image/jpeg')
                    resp.headers['Cache-Control'] = 'no-cache, no-store'
                    return resp
            except Exception:
                pass
    return '', 204


@app.route("/api/nest/setpoint", methods=["POST"])
def nest_setpoint():
    """Set cool and/or heat setpoint. Body: {device_name, cool_f, heat_f}"""
    if not NEST_PROJECT_ID or not NEST_REFRESH_TOKEN:
        return jsonify({"ok": False, "error": "not configured"})
    token = _get_nest_access_token()
    if not token:
        return jsonify({"ok": False, "error": "token refresh failed"})
    try:
        import urllib.request
        body = request.get_json() or {}
        # Use first thermostat if device_name not specified
        with _state_lock:
            thermostats = _state["nest"].get("thermostats", [])
        if not thermostats:
            return jsonify({"ok": False, "error": "no thermostats found"})
        device_name = body.get("device_name") or thermostats[0]["device_name"]
        cool_f = body.get("cool_f")
        heat_f = body.get("heat_f")

        def f_to_c(f): return (float(f) - 32) * 5 / 9

        if cool_f and heat_f:
            payload = {"command": "sdm.devices.commands.ThermostatTemperatureSetpoint.SetRange",
                       "params": {"coolCelsius": f_to_c(cool_f), "heatCelsius": f_to_c(heat_f)}}
        elif cool_f:
            payload = {"command": "sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool",
                       "params": {"coolCelsius": f_to_c(cool_f)}}
        else:
            payload = {"command": "sdm.devices.commands.ThermostatTemperatureSetpoint.SetHeat",
                       "params": {"heatCelsius": f_to_c(heat_f)}}

        url = f"https://smartdevicemanagement.googleapis.com/v1/{device_name}:executeCommand"
        req = urllib.request.Request(url,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/settings/wyze", methods=["POST"])
def api_settings_wyze():
    global WYZE_API_KEY, WYZE_KEY_ID, WYZE_EMAIL, WYZE_PASSWORD
    body = request.get_json()
    api_key  = (body.get("api_key")  or "").strip()
    key_id   = (body.get("key_id")   or "").strip()
    email    = (body.get("email")    or "").strip()
    password = (body.get("password") or "").strip()
    config_path = Path(__file__).parent / "config.py"
    try:
        import re as _re
        text = config_path.read_text()
        if api_key:
            text = _re.sub(r'^WYZE_API_KEY\s*=\s*.*$', f'WYZE_API_KEY = "{api_key}"', text, flags=_re.MULTILINE)
            WYZE_API_KEY = api_key
        if key_id:
            text = _re.sub(r'^WYZE_KEY_ID\s*=\s*.*$', f'WYZE_KEY_ID = "{key_id}"', text, flags=_re.MULTILINE)
            WYZE_KEY_ID = key_id
        if email:
            text = _re.sub(r'^WYZE_EMAIL\s*=\s*.*$', f'WYZE_EMAIL = "{email}"', text, flags=_re.MULTILINE)
            WYZE_EMAIL = email
        if password:
            text = _re.sub(r'^WYZE_PASSWORD\s*=\s*.*$', f'WYZE_PASSWORD = "{password}"', text, flags=_re.MULTILINE)
            WYZE_PASSWORD = password
        config_path.write_text(text)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/settings/ring", methods=["POST"])
def api_settings_ring():
    global RING_EMAIL, RING_PASSWORD
    body  = request.get_json()
    email = (body.get("email")    or "").strip()
    pw    = (body.get("password") or "").strip()
    config_path = Path(__file__).parent / "config.py"
    try:
        import re as _re
        text = config_path.read_text()
        if email:
            text = _re.sub(r'^RING_EMAIL\s*=\s*.*$', f'RING_EMAIL = "{email}"', text, flags=_re.MULTILINE)
            RING_EMAIL = email
        if pw:
            text = _re.sub(r'^RING_PASSWORD\s*=\s*.*$', f'RING_PASSWORD = "{pw}"', text, flags=_re.MULTILINE)
            RING_PASSWORD = pw
        config_path.write_text(text)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/settings/nest", methods=["POST"])
def api_settings_nest():
    global NEST_ACCESS_TOKEN
    body  = request.get_json()
    token = (body.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "token is required"}), 400
    config_path = Path(__file__).parent / "config.py"
    try:
        import re as _re
        text = config_path.read_text()
        text = _re.sub(r'^NEST_ACCESS_TOKEN\s*=\s*.*$', f'NEST_ACCESS_TOKEN = "{token}"', text, flags=_re.MULTILINE)
        config_path.write_text(text)
        NEST_ACCESS_TOKEN = token
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/bhyve/run", methods=["POST"])
def api_bhyve_run():
    global _bhyve_token
    if not BHYVE_EMAIL or not BHYVE_PASSWORD:
        return jsonify({"ok": False, "error": "B-Hyve not configured"}), 403
    body = request.get_json() or {}
    device_id = body.get("device_id", "")
    zone_id = int(body.get("zone_id", 1))
    minutes = int(body.get("minutes", 10))
    if not device_id:
        return jsonify({"ok": False, "error": "device_id required"}), 400
    try:
        with _bhyve_token_lock:
            if not _bhyve_token:
                _bhyve_login()
        from datetime import timezone
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = {
            "event": "change_mode",
            "device_id": device_id,
            "mode": "manual",
            "stations": [{"station": zone_id, "run_time": minutes}],
            "timestamp": ts,
        }
        _bhyve_ws_command(device_id, payload)
        return jsonify({"ok": True})
    except Exception as e:
        log.warning("B-Hyve run error: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/bhyve/stop", methods=["POST"])
def api_bhyve_stop():
    global _bhyve_token
    if not BHYVE_EMAIL or not BHYVE_PASSWORD:
        return jsonify({"ok": False, "error": "B-Hyve not configured"}), 403
    body = request.get_json() or {}
    device_id = body.get("device_id", "")
    if not device_id:
        return jsonify({"ok": False, "error": "device_id required"}), 400
    try:
        with _bhyve_token_lock:
            if not _bhyve_token:
                _bhyve_login()
        from datetime import timezone
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = {
            "event": "stop_watering",
            "device_id": device_id,
            "timestamp": ts,
        }
        _bhyve_ws_command(device_id, payload)
        return jsonify({"ok": True})
    except Exception as e:
        log.warning("B-Hyve stop error: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/settings/bhyve", methods=["POST"])
def api_settings_bhyve():
    global BHYVE_EMAIL, BHYVE_PASSWORD, _bhyve_token, _bhyve_next_retry
    body  = request.get_json() or {}
    email = (body.get("email")    or "").strip()
    pw    = (body.get("password") or "").strip()
    config_path = Path(__file__).parent / "config.py"
    try:
        import re as _re
        text = config_path.read_text()
        if email:
            text = _re.sub(r'^BHYVE_EMAIL\s*=\s*.*$', f'BHYVE_EMAIL = "{email}"', text, flags=_re.MULTILINE)
            BHYVE_EMAIL = email
        if pw:
            text = _re.sub(r'^BHYVE_PASSWORD\s*=\s*.*$', f'BHYVE_PASSWORD = "{pw}"', text, flags=_re.MULTILINE)
            BHYVE_PASSWORD = pw
        config_path.write_text(text)
        # Reset token and backoff so next poll re-authenticates immediately
        with _bhyve_token_lock:
            _bhyve_token = None
        _bhyve_next_retry = 0
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/settings/ge", methods=["POST"])
def api_settings_ge():
    global GE_CLIENT_ID, GE_CLIENT_SECRET, GE_REFRESH_TOKEN, _ge_access_token, _ge_next_retry
    body = request.get_json() or {}
    client_id     = (body.get("client_id")     or "").strip()
    client_secret = (body.get("client_secret") or "").strip()
    refresh_token = (body.get("refresh_token") or "").strip()
    config_path = Path(__file__).parent / "config.py"
    try:
        import re as _re
        text = config_path.read_text()
        if client_id:
            text = _re.sub(r'^GE_CLIENT_ID\s*=\s*.*$', f'GE_CLIENT_ID = "{client_id}"', text, flags=_re.MULTILINE)
            GE_CLIENT_ID = client_id
        if client_secret:
            text = _re.sub(r'^GE_CLIENT_SECRET\s*=\s*.*$', f'GE_CLIENT_SECRET = "{client_secret}"', text, flags=_re.MULTILINE)
            GE_CLIENT_SECRET = client_secret
        if refresh_token:
            text = _re.sub(r'^GE_REFRESH_TOKEN\s*=\s*.*$', f'GE_REFRESH_TOKEN = "{refresh_token}"', text, flags=_re.MULTILINE)
            GE_REFRESH_TOKEN = refresh_token
        config_path.write_text(text)
        # Clear cached token so next poll re-authenticates
        with _ge_token_lock:
            _ge_access_token = ""
        _ge_next_retry = 0
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ge/refresh", methods=["POST"])
def api_ge_refresh():
    """Force an immediate GE SmartHQ appliance re-poll on the next loop tick."""
    global _ge_poll_counter
    _ge_poll_counter = 99  # exceeds threshold — triggers on next tick
    return jsonify({"ok": True, "message": "GE refresh queued"})


@app.route("/api/ge/appliance/<aid>/command", methods=["POST"])
def api_ge_command(aid: str):
    """Send an attribute command to a GE SmartHQ appliance.
    Body: {"attribute": "erdCodeOrName", "value": "hexOrStringValue"}
    """
    body = request.get_json() or {}
    attribute = (body.get("attribute") or "").strip()
    value = (body.get("value") or "").strip()
    if not attribute:
        return jsonify({"ok": False, "error": "attribute required"}), 400
    try:
        token = _ge_get_token()
        if not token:
            return jsonify({"ok": False, "error": "GE SmartHQ not authenticated"}), 401
        payload = json.dumps({"attributes": [{"erd": attribute, "value": value}]}).encode()
        req = urllib.request.Request(
            f"{GE_API_BASE}/v1/appliance/{aid}/attribute",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp_body = r.read()
        resp_data = json.loads(resp_body) if resp_body.strip() else {}
        log.info("GE command OK — appliance=%s %s=%s", aid, attribute, value)
        return jsonify({"ok": True, "response": resp_data})
    except urllib.error.HTTPError as e:
        err_bytes = e.read()
        detail = err_bytes.decode(errors="replace")[:200] if err_bytes else str(e)
        log.warning("GE command error %s: HTTP %d — %s", aid, e.code, detail)
        return jsonify({"ok": False, "error": f"HTTP {e.code}", "detail": detail}), e.code
    except Exception as e:
        log.warning("GE command error %s: %s", aid, e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ge/appliance/<aid>/v2service", methods=["POST"])
def api_ge_v2service(aid: str):
    """Send a v2 Digital Twin service state PATCH to a GE device.
    Body: {"serviceType": "...", "domainType": "...", "serviceDeviceType": "...", "state": {...}}
    """
    body = request.get_json() or {}
    service_type = (body.get("serviceType") or "").strip()
    domain_type = (body.get("domainType") or "").strip()
    sdev_type = (body.get("serviceDeviceType") or "").strip()
    state_patch = body.get("state", {})
    if not service_type:
        return jsonify({"ok": False, "error": "serviceType required"}), 400
    try:
        token = _ge_get_token()
        if not token:
            return jsonify({"ok": False, "error": "GE SmartHQ not authenticated"}), 401
        svc: dict = {"serviceType": service_type, "state": state_patch}
        if domain_type:
            svc["domainType"] = domain_type
        if sdev_type:
            svc["serviceDeviceType"] = sdev_type
        payload = json.dumps({"services": [svc]}).encode()
        req = urllib.request.Request(
            f"{GE_API_BASE}/v2/device/{aid}",
            data=payload,
            method="PATCH",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp_body = r.read()
        resp_data = json.loads(resp_body) if resp_body.strip() else {}
        log.info("GE v2 service OK — device=%s svcType=%s", aid, service_type)
        return jsonify({"ok": True, "response": resp_data})
    except urllib.error.HTTPError as e:
        err_bytes = e.read()
        detail = err_bytes.decode(errors="replace")[:200] if err_bytes else str(e)
        log.warning("GE v2 service error %s: HTTP %d — %s", aid, e.code, detail)
        return jsonify({"ok": False, "error": f"HTTP {e.code}", "detail": detail}), e.code
    except Exception as e:
        log.warning("GE v2 service error %s: %s", aid, e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/devices")
def api_devices():
    return jsonify({
        "span": {"host": SPAN_HOST, "configured": bool(SPAN_TOKEN)},
        "enphase": {"host": ENPHASE_HOST, "serial": ENPHASE_SERIAL, "configured": bool(ENPHASE_TOKEN)},
        "pentair": {"host": PENTAIR_HOST, "port": PENTAIR_PORT, "configured": True},
        "tesla": {"host": TESLA_HOST or "not_found", "configured": bool(TESLA_HOST and TESLA_EMAIL)},
    })


# ── Energy Analytics API ───────────────────────────────────────────────────────

@app.route("/api/analytics/usage-patterns")
def api_usage_patterns():
    """Get usage pattern analysis: hourly peaks, daily averages, seasonal trends."""
    days = request.args.get("days", 30, type=int)
    patterns = get_usage_patterns(days)
    return jsonify(patterns or {})


@app.route("/api/analytics/daily-trends")
def api_daily_trends():
    """Fetch daily energy trends for charts (solar, load, grid, etc)."""
    days = request.args.get("days", 30, type=int)
    trends = get_recent_daily_trends(days)
    return jsonify({"trends": trends})


@app.route("/api/analytics/powerwall-roi")
def api_powerwall_roi():
    """Calculate ROI for Powerwall installation based on recent data patterns."""
    battery_kwh = request.args.get("battery_kwh", 13.5, type=float)
    install_cost = request.args.get("install_cost", 11000, type=int)
    lifetime_years = request.args.get("lifetime_years", 10, type=int)

    roi = calculate_powerwall_roi(battery_kwh, install_cost, lifetime_years)
    if not roi:
        return jsonify({"error": "insufficient data"}), 202  # Accepted but not ready
    return jsonify(roi)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DASHBOARD HTML                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Jarvis Home</title>
<style>
  :root {
    --bg: #0a0c10;
    --surface: #111318;
    --surface2: #1a1d24;
    --border: #2a2d35;
    --text: #e2e8f0;
    --text-dim: #64748b;
    --solar: #f59e0b;
    --battery: #10b981;
    --grid: #6366f1;
    --load: #ef4444;
    --pool: #06b6d4;
    --online: #10b981;
    --warning: #f59e0b;
    --error: #ef4444;
    --offline: #475569;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100dvh; overflow: hidden; }
  main { overflow-y: auto !important; -webkit-overflow-scrolling: touch; }

  body { background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; display: flex; flex-direction: column; }

  /* Header (status bar only — no nav buttons) */
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0; position: sticky; top: 0; z-index: 100; margin-left: 72px; }
  body.has-subnav header { margin-left: 232px; }
  #appliance-banner { margin-left: 72px; }
  body.has-subnav #appliance-banner { margin-left: 232px; }
  .header-top { display: flex; align-items: center; gap: 12px; padding: 0 16px; height: 42px; }
  .logo { font-size: 16px; font-weight: 700; letter-spacing: .05em; color: var(--solar); }
  .logo span { color: var(--text-dim); }
  .status-bar { display: flex; gap: 12px; align-items: center; margin-left: auto; }

  /* Left Rail Navigation */
  #left-rail {
    position: fixed; left: 0; top: 0; bottom: 0; width: 72px;
    background: var(--surface); border-right: 1px solid var(--border);
    z-index: 200; display: flex; flex-direction: column; align-items: center;
    overflow: hidden;
    -webkit-tap-highlight-color: transparent;
  }
  /* Header-height placeholder at top of left rail — aligns with header bar */
  #left-rail::before {
    content: ''; display: block; width: 100%; height: 43px; flex-shrink: 0;
    border-bottom: 1px solid var(--border);
  }
  #sub-rail {
    position: fixed; left: 72px; top: 0; bottom: 0; width: 160px;
    background: var(--surface); border-right: 1px solid var(--border);
    z-index: 190; display: none; flex-direction: column;
    overflow-y: auto;
  }
  /* Header-height placeholder at top of sub-rail */
  #sub-rail::before {
    content: ''; display: block; width: 100%; height: 43px; flex-shrink: 0;
    border-bottom: 1px solid var(--border);
  }
  #sub-rail.visible { display: flex; }
  .rail-btn {
    width: 100%; display: flex; flex-direction: column; align-items: center;
    justify-content: center; background: none; border: none;
    border-left: 3px solid transparent;
    color: var(--text-dim); cursor: pointer; padding: 8px 4px; gap: 3px;
    font-family: inherit; transition: color .15s, border-color .15s, background .15s;
    min-height: 72px; flex-shrink: 0;
  }
  .rail-btn.active { color: var(--solar); border-left-color: var(--solar); background: rgba(245,158,11,0.08); }
  .rail-btn:hover { color: var(--text); background: rgba(255,255,255,0.05); }
  .rail-icon { font-size: 1.35rem; line-height: 1; }
  .rail-label { font-size: 0.52rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; white-space: nowrap; text-align: center; }
  .sub-rail-btn {
    width: 100%; display: flex; align-items: center;
    background: none; border: none; border-left: 3px solid transparent;
    color: var(--text-dim); cursor: pointer; padding: 10px 14px;
    font-family: inherit; font-size: 0.82rem; text-align: left;
    transition: color .15s, border-color .15s, background .15s;
    min-height: 44px; gap: 6px; white-space: nowrap;
  }
  .sub-rail-btn.active { color: var(--text); border-left-color: var(--solar); background: rgba(245,158,11,0.08); }
  .sub-rail-btn:hover { color: var(--text); background: rgba(255,255,255,0.05); }

  .dot { width: 8px; height: 8px; border-radius: 50%; }
  .dot.online { background: var(--online); box-shadow: 0 0 6px var(--online); }
  .dot.error { background: var(--error); }
  .dot.offline { background: var(--offline); }
  .dot.warning { background: var(--warning); }
  .ts { color: var(--text-dim); font-size: 11px; }

  /* Views */
  main { padding: 0; margin-left: 72px; flex: 1; min-height: 0; overflow-y: auto; -webkit-overflow-scrolling: touch; display: flex; flex-direction: column; }
  body.has-subnav main { margin-left: 232px; }
  .view { display: none; }
  .view.active { display: block; }
  /* Sub-nav buttons */
  .sub-nav-btn { padding: 6px 14px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.12); background: transparent; color: #aaa; cursor: pointer; font-size: 0.9rem; min-height: 36px; transition: all 0.15s; white-space: nowrap; flex-shrink: 0; }
  .sub-nav-btn.active { background: rgba(99,102,241,0.2); border-color: rgba(99,102,241,0.4); color: #fff; }
  .sub-nav-btn:hover { background: rgba(255,255,255,0.08); color: #fff; }
  /* Horizontally scrollable sub-nav (no wrap, hide scrollbar) */
  .sub-nav { scrollbar-width: none; -webkit-overflow-scrolling: touch; }
  .sub-nav::-webkit-scrollbar { display: none; }
  /* Cockpit is a flex column; cockpit-panels fills remaining height */
  .view { display: none; flex-direction: column; overflow: visible; }
  .view.active { display: flex; flex: 1; min-height: 0; }
  /* view-energy is a shell (sub-nav moved to header) — zero height */
  #view-energy { flex: 0 !important; min-height: 0 !important; overflow: hidden; }
  #view-cockpit { display: none; flex-direction: column; overflow: hidden; }
  #view-cockpit.active { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: hidden; }
  /* Ring view: iframe must fill the full available height */
  #view-ring { overflow: hidden; padding: 0 !important; }
  #view-ring.active { display: block; }
  #view-ring iframe { display: block; width: 100%; height: calc(100vh - 42px); border: none; }

  /* Grid */
  .grid { display: grid; gap: 12px; }
  .grid-4 { grid-template-columns: repeat(4, 1fr); }
  .grid-3 { grid-template-columns: repeat(3, 1fr); }
  .grid-2 { grid-template-columns: repeat(2, 1fr); }
  @media (max-width: 900px) { .grid-4, .grid-3 { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 600px) { .grid-4, .grid-3, .grid-2 { grid-template-columns: 1fr; } }

  /* Card */
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 10px; }
  .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  .card-title { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--text-dim); }
  .badge { font-size: 10px; padding: 2px 8px; border-radius: 20px; font-weight: 600; }
  .badge.online { background: rgba(16,185,129,.15); color: var(--online); }
  .badge.error { background: rgba(239,68,68,.15); color: var(--error); }
  .badge.offline { background: rgba(71,85,105,.15); color: var(--offline); }
  .badge.warning { background: rgba(245,158,11,.15); color: var(--warning); }
  .badge.partial { background: rgba(99,102,241,.15); color: var(--grid); }
  .badge.unconfigured { background: rgba(71,85,105,.15); color: var(--text-dim); }
  .badge.no_token { background: rgba(245,158,11,.15); color: var(--warning); }

  /* Big metric */
  .big-val { font-size: 32px; font-weight: 700; line-height: 1; }
  .big-unit { font-size: 14px; color: var(--text-dim); margin-left: 4px; }
  .sub-val { font-size: 12px; color: var(--text-dim); margin-top: 6px; }

  /* Energy flow cards */
  .energy-solar { border-top: 3px solid var(--solar); }
  .energy-battery { border-top: 3px solid var(--battery); }
  .energy-grid { border-top: 3px solid var(--grid); }
  .energy-load { border-top: 3px solid var(--load); }
  .energy-pool { border-top: 3px solid var(--pool); }

  /* Power flow SVG animation */
  .flow-path-animated { animation: flowDash 1.5s linear infinite; }
  @keyframes flowDash { to { stroke-dashoffset: -18; } }
  .flow-path-slow     { animation: flowDash 3s linear infinite; }
  .flow-path-fast     { animation: flowDash 0.6s linear infinite; }
  .flow-path-idle     { opacity: 0.15; animation: none; }
  .flow-path-bridge   { stroke-dasharray: 6 8; animation: flowDash 2s linear infinite; }
  .c-solar { color: var(--solar); }
  .c-battery { color: var(--battery); }
  .c-grid { color: var(--grid); }
  .c-load { color: var(--load); }
  .c-pool { color: var(--pool); }

  /* Self-powered bar */
  .bar-bg { background: var(--surface2); border-radius: 4px; height: 8px; overflow: hidden; margin-top: 8px; }
  .bar-fill { height: 100%; border-radius: 4px; transition: width .5s; background: var(--solar); }

  /* SPAN Circuit Heatmap */
  .circuit-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; margin-top: 12px; }
  .circuit-tile { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; cursor: default; transition: all .2s; }
  .circuit-tile:hover { border-color: rgba(255,255,255,.2); }
  .circuit-tile.green { border-left: 3px solid var(--online); }
  .circuit-tile.yellow { border-left: 3px solid var(--warning); }
  .circuit-tile.red { border-left: 3px solid var(--error); }
  .circuit-tile.off { border-left: 3px solid var(--border); opacity: .6; }
  .ct-name { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px; }
  .ct-power { font-size: 18px; font-weight: 700; }
  .ct-unit { font-size: 11px; color: var(--text-dim); }
  .ct-relay { font-size: 10px; color: var(--text-dim); margin-top: 4px; }

  /* Pool — redesigned */
  .pc-grid { display: grid; grid-template-columns: 260px 1fr; gap: 12px; }
  @media (max-width: 700px) { .pc-grid { grid-template-columns: 1fr; } }
  .pc-hero-card { background: var(--surface2); border: 2px solid var(--border); border-radius: 14px; padding: 20px 16px; display: flex; flex-direction: column; align-items: center; gap: 4px; transition: border-color .3s, box-shadow .3s, background .3s; }
  .pc-hero-card.spa-on { background: rgba(255,120,0,0.10); border-color: rgba(255,120,0,0.75); box-shadow: 0 0 30px rgba(255,120,0,0.25); }
  .pc-section-lbl { font-size: 10px; font-weight: 700; letter-spacing: 2px; color: rgba(255,255,255,0.35); text-transform: uppercase; }
  .pc-hero-status { font-size: 28px; font-weight: 800; letter-spacing: 2px; margin: 4px 0 0; }
  .pc-hero-status.status-off { color: var(--text-dim); }
  .pc-hero-status.status-on  { color: #FF7820; text-shadow: 0 0 20px rgba(255,120,0,0.5); }
  .pc-hero-temp { font-size: 76px; font-weight: 800; color: #FF7820; line-height: 1; margin: 8px 0 2px; }
  .pc-hero-card:not(.spa-on) .pc-hero-temp { color: var(--text-dim); }
  .pc-hero-setpt { font-size: 13px; color: rgba(255,255,255,0.45); }
  .pc-hero-actions { display: flex; gap: 10px; margin-top: 18px; width: 100%; }
  .pc-action-btn { flex: 1; padding: 15px 0; border-radius: 10px; border: none; font-size: 15px; font-weight: 700; letter-spacing: 0.5px; cursor: pointer; font-family: inherit; transition: filter .15s, background .15s; }
  .pc-btn-on  { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.18); color: rgba(255,255,255,0.65); }
  .pc-btn-on:hover  { background: rgba(255,255,255,0.12); }
  .pc-hero-card.spa-on .pc-btn-on { background: linear-gradient(135deg,#FF7820,#FF4500); border: none; color: #fff; }
  .pc-hero-card.spa-on .pc-btn-on:hover { filter: brightness(1.15); }
  .pc-btn-off { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.18); color: rgba(255,255,255,0.65); }
  .pc-btn-off:hover { background: rgba(255,255,255,0.12); }
  .pc-right { display: grid; grid-template-columns: repeat(2,1fr); gap: 10px; align-content: start; }
  @media (max-width: 500px) { .pc-right { grid-template-columns: 1fr; } }
  .pc-stat-card { background: var(--surface2); border: 2px solid var(--border); border-radius: 12px; padding: 14px; transition: border-color .3s, box-shadow .3s; }
  .pc-stat-card.card-on  { border-color: #06b6d4; box-shadow: 0 0 18px rgba(6,182,212,0.35), inset 0 0 12px rgba(6,182,212,0.06); }
  .pc-stat-card.card-running { border-color: #22c55e; box-shadow: 0 0 18px rgba(34,197,94,0.4), inset 0 0 12px rgba(34,197,94,0.07); }
  .pc-stat-card.card-off  { border-color: rgba(255,255,255,0.08); opacity: 0.7; }
  .pc-stat-hdr  { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .pc-stat-temp { font-size: 34px; font-weight: 700; color: var(--pool); margin: 4px 0; }
  .pc-stat-sub  { font-size: 11px; color: var(--text-dim); margin-top: 3px; }
  .pc-pump-big  { font-size: 30px; font-weight: 700; color: var(--pool); }
  .pc-pump-unit { font-size: 12px; color: var(--text-dim); }
  .pc-pump-row  { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
  .pc-circ-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(118px,1fr)); gap: 8px; }
  .pc-circ-tile { background: var(--surface2); border: 2px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 11px 9px; text-align: center; transition: border-color .2s, background .2s, box-shadow .2s; opacity: 0.55; }
  .pc-circ-tile.circ-on { border-color: #06b6d4; background: rgba(6,182,212,0.1); box-shadow: 0 0 12px rgba(6,182,212,0.3); opacity: 1; }
  .pc-circ-nm   { font-size: 11px; font-weight: 600; color: var(--text); margin-bottom: 5px; }
  .pc-circ-st   { font-size: 10px; font-weight: 700; letter-spacing: 1px; }
  .pc-circ-tile.circ-on .pc-circ-st { color: #06b6d4; }
  .pc-circ-tile.circ-off .pc-circ-st { color: var(--text-dim); }
  .btn { background: var(--surface2); border: 1px solid var(--border); color: var(--text); cursor: pointer; padding: 7px 14px; border-radius: 6px; font-size: 11px; font-family: inherit; transition: all .15s; }
  .btn:hover { background: var(--border); }
  .btn.danger { border-color: var(--error); color: var(--error); }
  .btn.primary { border-color: var(--pool); color: var(--pool); }
  .circuit-row { display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border); }
  .circuit-row:last-child { border-bottom: none; }
  .circuit-status { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .circuit-status.ON { background: var(--online); box-shadow: 0 0 4px var(--online); }
  .circuit-status.OFF { background: var(--border); }
  .circuit-name-col { flex: 1; font-size: 12px; }
  .circuit-id { font-size: 10px; color: var(--text-dim); }

  /* Devices */
  .device-card { display: flex; align-items: center; gap: 12px; }
  .device-icon { font-size: 24px; }
  .device-info { flex: 1; }
  .device-name { font-size: 13px; font-weight: 600; }
  .device-detail { font-size: 11px; color: var(--text-dim); margin-top: 2px; }

  /* Device status grid (new) */
  .dev-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  @media (max-width: 1100px) { .dev-grid { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 600px)  { .dev-grid { grid-template-columns: 1fr; } }
  .dev-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; display: flex; align-items: flex-start; gap: 10px; position: relative; transition: border-color .2s; }
  .dev-card:hover { border-color: rgba(255,255,255,0.15); }
  .dev-card.status-online  { border-left: 3px solid var(--online); }
  .dev-card.status-error   { border-left: 3px solid var(--error); }
  .dev-card.status-offline { border-left: 3px solid var(--offline); }
  .dev-card.status-warning { border-left: 3px solid var(--warning); }
  .dev-sdot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; }
  .dev-sdot.online  { background: var(--online); box-shadow: 0 0 5px var(--online); }
  .dev-sdot.error   { background: var(--error); }
  .dev-sdot.offline { background: var(--offline); }
  .dev-sdot.warning { background: var(--warning); }
  .dev-body { flex: 1; min-width: 0; }
  .dev-header { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .dev-dicon { font-size: 16px; }
  .dev-dname { font-size: 12px; font-weight: 700; color: var(--text); }
  .dev-ip { font-size: 10px; color: var(--text-dim); margin-top: 2px; font-family: monospace; }
  .dev-metric { font-size: 13px; font-weight: 600; color: var(--text); margin-top: 5px; }
  .dev-metric span { color: var(--text-dim); font-size: 10px; font-weight: 400; }
  .dev-lastseen { font-size: 10px; color: var(--text-dim); margin-top: 3px; }

  /* Section title */
  .section-title { font-size: 11px; text-transform: uppercase; letter-spacing: .1em; color: var(--text-dim); margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
  .section-title::after { content: ''; flex: 1; height: 1px; background: var(--border); }

  /* Responsive row */
  .row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
  .row > * { flex: 1; min-width: 200px; }

  /* Tooltips */
  [title] { cursor: help; }

  /* Toasts */
  #toast { position: fixed; bottom: 20px; right: 20px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 16px; font-size: 12px; opacity: 0; transition: opacity .3s; pointer-events: none; z-index: 999; }
  #toast.show { opacity: 1; }

  /* ── SPAN Energy Visualization ── */
  .span-viz { margin-bottom: 16px; }
  .span-viz .card { background: #12121a; border-color: rgba(255,255,255,0.08); }
  .chart-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
  .chart-row .chart-card { flex: 1; min-width: 240px; background: #12121a; border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 14px; }
  .chart-card-title { font-size: 11px; text-transform: uppercase; letter-spacing: .1em; color: rgba(255,255,255,0.5); margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; }
  .donut-total { text-align: center; font-size: 20px; font-weight: 700; color: #00d4ff; margin-top: 6px; }
  .donut-sub { text-align: center; font-size: 10px; color: rgba(255,255,255,0.4); margin-top: 2px; }
  .sparkline-header { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
  .sparkline-stat { font-size: 10px; color: rgba(255,255,255,0.45); }
  .sparkline-stat span { color: rgba(255,255,255,0.8); font-weight: 600; }
  .circuit-tile { position: relative; overflow: hidden; }
  .ct-mini-spark { position: absolute; bottom: 0; left: 0; right: 0; height: 18px; opacity: 0.7; }

  /* ── Cameras ── */
  .camera-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; cursor: pointer; transition: border-color .2s; }
  .camera-card:hover { border-color: rgba(255,255,255,.25); }
  .camera-thumb { width: 100%; height: calc(100vh / 3); object-fit: cover; background: var(--surface2); display: block; }
  .camera-thumb-placeholder { width: 100%; height: calc(100vh / 3); background: var(--surface2); display: flex; align-items: center; justify-content: center; color: var(--text-dim); font-size: 24px; flex-direction: column; gap: 4px; }
  .camera-info { padding: 6px 8px; }
  .camera-name { font-weight: 700; font-size: 11px; margin-bottom: 4px; display: flex; align-items: center; justify-content: space-between; gap: 6px; }
  .camera-meta { font-size: 9px; color: var(--text-dim); margin-top: 2px; }
  .badge-wyze { background: rgba(0,212,255,.15); color: #00d4ff; }
  .badge-ring { background: rgba(16,185,129,.15); color: var(--battery); }
  .cam-live-dot { display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--online); box-shadow:0 0 5px var(--online); margin-right:4px; animation:pulse-run 1.5s infinite; vertical-align:middle; }
  /* ── Camera Modal ── */
  #cam-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.88); z-index:2000; align-items:center; justify-content:center; flex-direction:column; gap:14px; }
  #cam-modal.show { display:flex; }
  #cam-modal-close { position:fixed; top:14px; right:18px; font-size:28px; cursor:pointer; color:rgba(255,255,255,.5); background:none; border:none; line-height:1; transition:color .15s; }
  #cam-modal-close:hover { color:#fff; }
  #cam-modal-img { max-width:92vw; max-height:78vh; border-radius:10px; border:1px solid var(--border); object-fit:contain; display:block; }
  #cam-modal-placeholder { width:640px; max-width:92vw; height:360px; background:var(--surface2); border-radius:10px; display:flex; align-items:center; justify-content:center; font-size:56px; }
  #cam-modal-info { display:flex; gap:10px; align-items:center; flex-wrap:wrap; justify-content:center; }
  #cam-modal-title { font-size:14px; font-weight:700; }
  #cam-modal-meta { font-size:12px; color:var(--text-dim); }

  /* ── Nest tile ── */
  .nest-cockpit-tile { background: var(--surface2); border-radius: 8px; padding: 10px 14px; display: flex; gap: 12px; align-items: center; }
  .nest-cockpit-temp { font-size: 24px; font-weight: 700; color: var(--pool); }
  .nest-cockpit-label { font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing:.05em; }

  /* ── B-Hyve Sprinklers ── */
  .zone-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-top: 12px; }
  .zone-tile { background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; position: relative; }
  .zone-tile.running { border-color: var(--online); box-shadow: 0 0 10px rgba(16,185,129,.2); }
  .zone-name { font-size: 13px; font-weight: 700; margin-bottom: 8px; }
  .zone-countdown { font-size: 22px; font-weight: 700; color: var(--online); font-variant-numeric: tabular-nums; }
  .zone-next { font-size: 10px; color: var(--text-dim); margin-top: 6px; }
  .zone-btns { display: flex; gap: 6px; margin-top: 10px; }
  .btn-run { background: rgba(16,185,129,.15); border: 1px solid var(--online); color: var(--online); cursor: pointer; padding: 5px 12px; border-radius: 6px; font-size: 11px; font-family: inherit; transition: all .15s; }
  .btn-run:hover { background: rgba(16,185,129,.25); }
  .btn-stop { background: rgba(239,68,68,.15); border: 1px solid var(--error); color: var(--error); cursor: pointer; padding: 5px 12px; border-radius: 6px; font-size: 11px; font-family: inherit; transition: all .15s; }
  .btn-stop:hover { background: rgba(239,68,68,.25); }
  .badge-running { background: rgba(16,185,129,.2); color: var(--online); animation: pulse-run 1.5s infinite; }
  @keyframes pulse-run { 0%,100% { opacity:1; } 50% { opacity:.5; } }
  .badge-scheduled { background: rgba(99,102,241,.15); color: var(--grid); }
  /* GE SmartHQ appliance cards */
  @keyframes ge-border-pulse { 0%,100%{border-color:rgba(16,185,129,0.35)} 50%{border-color:rgba(16,185,129,0.85)} }
  @keyframes ge-dot-pulse { 0%,100%{transform:scale(1);opacity:1} 50%{transform:scale(1.6);opacity:.7} }
  @keyframes ge-prog-indeterminate { 0%{background-position:-200% 0} 100%{background-position:200% 0} }
  .ge-card-running { animation: ge-border-pulse 2s ease-in-out infinite; }
  .ge-progress-bar { height:5px; background:rgba(255,255,255,0.07); border-radius:3px; overflow:hidden; margin:6px 0 2px; }
  .ge-progress-fill { height:100%; border-radius:3px; background:linear-gradient(90deg,#059669,#10b981,#34d399); transition:width 1s linear; }
  .ge-progress-indet { height:100%; border-radius:3px; background:linear-gradient(90deg,transparent 0%,#10b981 50%,transparent 100%); background-size:200% 100%; animation:ge-prog-indeterminate 1.5s linear infinite; }
  .ge-attr-pill { display:inline-flex; align-items:center; gap:3px; padding:2px 8px; background:var(--surface2); border:1px solid var(--border); border-radius:10px; font-size:10px; color:var(--text-dim); margin:2px 2px 0 0; white-space:nowrap; }
  .ge-attr-val { color:var(--text); font-weight:600; }
  .ge-ctrl-btn { flex:1; padding:7px 0; border-radius:6px; font-size:11px; cursor:pointer; font-family:inherit; font-weight:600; transition:all .15s; border:1px solid; letter-spacing:.02em; }
  .ge-ctrl-btn:disabled { opacity:.4; cursor:default; }
  .ge-ctrl-btn.pause  { background:rgba(245,158,11,.1);  border-color:rgba(245,158,11,.4);  color:#f59e0b; }
  .ge-ctrl-btn.pause:hover:not(:disabled)  { background:rgba(245,158,11,.22); }
  .ge-ctrl-btn.resume { background:rgba(16,185,129,.1);  border-color:rgba(16,185,129,.4);  color:#10b981; }
  .ge-ctrl-btn.resume:hover:not(:disabled) { background:rgba(16,185,129,.22); }
  .ge-ctrl-btn.stop   { background:rgba(239,68,68,.1);   border-color:rgba(239,68,68,.3);   color:#ef4444; }
  .ge-ctrl-btn.stop:hover:not(:disabled)   { background:rgba(239,68,68,.22); }
  .ge-ctrl-btn.start  { background:rgba(99,102,241,.1);  border-color:rgba(99,102,241,.4);  color:#6366f1; }
  .ge-ctrl-btn.start:hover:not(:disabled)  { background:rgba(99,102,241,.22); }
  .ge-ctrl-btn.fridge { background:rgba(56,189,248,.1);  border-color:rgba(56,189,248,.35); color:#38bdf8; font-size:10px; padding:5px 10px; flex:none; }
  .ge-ctrl-btn.fridge:hover:not(:disabled) { background:rgba(56,189,248,.2); }
  /* Modal overlay */
  #bhyve-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.7); z-index:1000; align-items:center; justify-content:center; }
  #bhyve-modal.show { display:flex; }
  .modal-box { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:24px; min-width:280px; }
  .modal-title { font-size:14px; font-weight:700; margin-bottom:16px; }
  .modal-dur-btns { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; }
  .dur-btn { background:var(--surface2); border:1px solid var(--border); color:var(--text); cursor:pointer; padding:8px 16px; border-radius:8px; font-family:inherit; font-size:12px; transition:all .15s; }
  .dur-btn:hover, .dur-btn.selected { background:rgba(16,185,129,.2); border-color:var(--online); color:var(--online); }
  .modal-actions { display:flex; gap:8px; justify-content:flex-end; }

  /* ══════════════════════════════════════════════════════════════════════
     TABLET DASHBOARD MODES — Glassmorphism Design System
     ══════════════════════════════════════════════════════════════════════ */
  .tablet-view { overflow: hidden; background: #0a0e1a; padding: 0; display: flex; flex-direction: column; }
  .glass-card { background: rgba(255,255,255,0.05); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.10); box-shadow: 0 0 20px rgba(0,200,255,0.05); border-radius: 16px; padding: 16px; }
  .glass-card.glow-solar { border-color: rgba(255,215,0,0.35); box-shadow: 0 0 24px rgba(255,215,0,0.12); }
  .glass-card.glow-grid  { border-color: rgba(255,140,0,0.35); box-shadow: 0 0 24px rgba(255,140,0,0.12); }
  .glass-card.glow-truck { border-color: rgba(0,255,255,0.35); box-shadow: 0 0 24px rgba(0,255,255,0.12); }
  .glass-card.glow-load  { border-color: rgba(155,89,182,0.35); box-shadow: 0 0 24px rgba(155,89,182,0.12); }
  @keyframes island-pulse { 0%,100% { box-shadow: 0 0 20px rgba(245,158,11,.35); } 50% { box-shadow: 0 0 48px rgba(245,158,11,.7); } }
  .island-glow { animation: island-pulse 2s ease-in-out infinite; border-color: rgba(245,158,11,0.8) !important; }
  .hero-num { font-size: 2.8rem; font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; font-family: system-ui, -apple-system, sans-serif; }
  .label-sm { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.1em; color: rgba(255,255,255,0.38); margin-bottom: 3px; display: block; }
  .value-md { font-size: 1.3rem; font-weight: 600; font-variant-numeric: tabular-nums; }
  .tab-status-bar { display: flex; align-items: center; gap: 12px; padding: 6px 16px; background: rgba(255,255,255,0.03); border-bottom: 1px solid rgba(255,255,255,0.07); font-size: 11px; color: rgba(255,255,255,0.55); flex-shrink: 0; }
  .tab-status-bar .sb-time { font-size: 1rem; font-weight: 700; color: rgba(255,255,255,0.9); font-variant-numeric: tabular-nums; }
  .sb-rate { padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 700; }
  .sb-rate.off-peak { background: rgba(16,185,129,.18); color: #10b981; }
  .sb-rate.shoulder  { background: rgba(245,158,11,.18); color: #f59e0b; }
  .sb-rate.peak      { background: rgba(239,68,68,.2);   color: #ef4444; }
  .sb-grid { padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 700; }
  .sb-grid.up      { background: rgba(16,185,129,.15);  color: #10b981; }
  .sb-grid.islanded{ background: rgba(245,158,11,.2);   color: #f59e0b; }
  .island-badge { display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px; border-radius: 10px; background: rgba(239,68,68,.22); color: #ef4444; font-size: 10px; font-weight: 700; animation: island-pulse 2s infinite; }
  /* Mode 1 — Microgrid */
  .mc-layout { display: grid; grid-template-columns: 200px 1fr 200px; grid-template-rows: 1fr; gap: 10px; flex: 1; padding: 10px; min-height: 0; height: 100%; }
  .mc-left, .mc-right { display: flex; flex-direction: column; gap: 8px; justify-content: center; overflow: hidden; min-height: 0; }
  .mc-center { position: relative; min-height: 0; }
  .mc-center canvas { position: absolute; inset: 0; width: 100%; height: 100%; border-radius: 16px; display: block; }
  .mc-overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: none; }
  .mc-hero { pointer-events: auto; text-align: center; min-width: 200px; max-width: 260px; }
  /* Mode 2 — Trading */
  .td-layout { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: hidden; }
  .td-top { display: grid; grid-template-columns: 190px 1fr 230px; gap: 10px; padding: 10px 12px 6px; flex: 1; min-height: 0; overflow: hidden; }
  .td-bottom { padding: 0 12px 10px; flex-shrink: 0; display: none; }
  .td-col { display: flex; flex-direction: column; gap: 8px; overflow: hidden; min-height: 0; }
  .sparkline { width: 100%; height: 34px; display: block; }
  .circuit-bar-row { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
  .circuit-bar-label { font-size: 0.88rem; color: rgba(255,255,255,.6); width: 96px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-shrink: 0; }
  .circuit-bar-track { flex: 1; height: 6px; background: rgba(255,255,255,.08); border-radius: 3px; overflow: hidden; }
  .circuit-bar-fill  { height: 100%; border-radius: 3px; background: linear-gradient(90deg,#7c3aed,#9B59B6); transition: width .5s; }
  .circuit-bar-val   { font-size: 0.92rem; font-weight: 700; color: rgba(255,255,255,.4); width: 38px; text-align: right; flex-shrink: 0; }
  #view-trading .label-sm { font-size: 0.82rem; }
  .shed-btn { font-size: 9px; padding: 1px 5px; border-radius: 4px; cursor: pointer; border: 1px solid rgba(239,68,68,.5); background: rgba(239,68,68,.1); color: #ef4444; font-family: inherit; flex-shrink: 0; transition: background .15s; }
  .shed-btn:hover { background: rgba(239,68,68,.25); }
  /* Mode 3 — Backup */
  .bi-layout { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; gap: 10px; flex: 1; padding: 10px 12px; min-height: 0; }
  .bi-primary   { grid-column: 1; grid-row: 1 / 3; display: flex; flex-direction: column; gap: 8px; min-height: 0; overflow: hidden; }
  .bi-secondary { grid-column: 2; grid-row: 1; min-height: 0; overflow: hidden; }
  .bi-log       { grid-column: 2; grid-row: 2; min-height: 0; overflow: hidden; }
  .scenario-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 10px; background: rgba(255,255,255,.04); border-radius: 8px; margin-bottom: 5px; }
  .scenario-label { font-size: 11px; color: rgba(255,255,255,.6); }
  .scenario-hours { font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums; }
  .priority-item { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 8px; margin-bottom: 5px; }
  .priority-item.shed-first  { background: rgba(239,68,68,.1);  border: 1px solid rgba(239,68,68,.22); }
  .priority-item.shed-second { background: rgba(245,158,11,.1); border: 1px solid rgba(245,158,11,.22); }
  .priority-item.shed-third  { background: rgba(99,102,241,.1); border: 1px solid rgba(99,102,241,.22); }
  .priority-item.shed-nc     { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08); }
  .priority-num  { font-size: 0.85rem; font-weight: 700; width: 18px; flex-shrink: 0; }
  .priority-name { font-size: 11px; flex: 1; }
  .priority-kw   { font-size: 10px; color: rgba(255,255,255,.4); }
  .event-log { font-size: 10px; line-height: 1.85; color: rgba(255,255,255,.55); overflow-y: auto; height: calc(100% - 24px); }
  .event-log .ev-time { color: rgba(255,255,255,.28); margin-right: 6px; }
  .event-log .ev-type { color: #f59e0b; font-weight: 600; }
  .event-log .ev-solar { color: #FFD700; }
  @media (max-width: 900px) {
    .mc-layout { grid-template-columns: 1fr; grid-template-rows: auto 260px auto; }
    .td-top    { grid-template-columns: 1fr; grid-template-rows: auto auto auto; }
    .bi-layout { grid-template-columns: 1fr; grid-template-rows: auto auto auto; }
  }
  @media (max-width: 767px) {
    #view-microgrid .mc-layout { grid-template-columns: 1fr !important; }
    #view-microgrid .mc-left, #view-microgrid .mc-right { display: none !important; }
    #view-microgrid .mc-center { grid-column: 1 !important; width: 100% !important; }
    .mc-hero { min-width: 180px !important; width: 88vw !important; }
    #view-microgrid .tab-status-bar { font-size: 0.7rem !important; flex-wrap: wrap !important; gap: 4px 8px !important; min-height: auto !important; padding: 6px 8px !important; }
  }

  /* ── Cockpit Swipe Panels + Dot Indicators ──────────────────────────── */
  #cockpit-panels {
    display: flex; overflow-x: scroll; scroll-snap-type: x mandatory; flex: 1; min-height: 0; overflow-y: hidden;
    scrollbar-width: none; -webkit-overflow-scrolling: touch;
    flex: 1; min-height: 0;
  }
  #cockpit-panels::-webkit-scrollbar { display: none; }
  #cockpit-panels > div {
    scroll-snap-align: start; flex: 0 0 100%; width: 100%;
    overflow: hidden; box-sizing: border-box;
    display: flex; flex-direction: column; min-height: 0;
  }
  #cockpit-panels .tablet-view { display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
  #cockpit-dots {
    display: flex; justify-content: center; align-items: center;
    gap: 14px; padding: 8px 0; flex-shrink: 0;
    background: rgba(0,0,0,0.3); border-top: 1px solid rgba(255,255,255,0.06);
  }
  .ck-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: rgba(255,255,255,0.2); cursor: pointer;
    border: none; padding: 0; transition: all 0.2s;
    -webkit-tap-highlight-color: transparent;
  }
  .ck-dot.active { background: #fff; box-shadow: 0 0 8px rgba(255,255,255,0.6); transform: scale(1.25); }
  .ck-dot[data-sub='live'].active      { background: #10b981; box-shadow: 0 0 8px rgba(16,185,129,0.7); }
  .ck-dot[data-sub='microgrid'].active { background: #FFD700; box-shadow: 0 0 8px rgba(255,215,0,0.7); }
  .ck-dot[data-sub='trading'].active   { background: #3B82F6; box-shadow: 0 0 8px rgba(59,130,246,0.7); }
  .ck-dot[data-sub='backup'].active    { background: #00FFFF; box-shadow: 0 0 8px rgba(0,255,255,0.7); }

  /* ── 1280×800 Tablet Optimization ── */
  @media screen and (max-width: 1280px) {
    .card { padding: 10px 12px; }
    .big-val { font-size: 26px !important; }
    .big-unit { font-size: 12px !important; }
    .sub-val { font-size: 11px; margin-top: 4px; }
    .sub-nav-btn { padding: 4px 10px; font-size: 11px; }
    .row { gap: 8px; margin-bottom: 8px; }
    table { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  }
  @media screen and (max-width: 1280px) and (max-height: 900px) {
    /* Landscape 1280×800 — keep all cockpit pages fully visible without scrolling */
    main { padding: 0; }
    .card { padding: 6px 8px; }
    .card-header { margin-bottom: 4px; }
    .grid { gap: 6px; }
    .row { gap: 6px; margin-bottom: 4px; }
    .big-val { font-size: 16px !important; }
    .big-unit { font-size: 10px !important; }
    .sub-val { font-size: 10px; margin-top: 1px; }
    #power-flow-svg { max-height: none !important; }
    #csub-live > .card:first-child { margin-bottom: 4px !important; }
    #cockpit-dots { padding: 3px 0; }
    .ck-dot { width: 6px; height: 6px; }
    .header-top { height: 36px !important; }
    .sub-nav-btn { padding: 3px 8px; font-size: 10px; min-height: 28px; }
    .sub-nav { padding: 4px 10px !important; }

    /* ── Microgrid page ── */
    .hero-num { font-size: 1.8rem !important; }
    .mc-layout { grid-template-columns: 160px 1fr 160px !important; gap: 6px !important; padding: 6px !important; }
    .glass-card { padding: 8px 10px !important; border-radius: 10px !important; }
    .mc-hero { min-width: 160px !important; padding: 10px !important; }
    #mc-net-kw { font-size: 2rem !important; }
    .mc-left, .mc-right { gap: 5px !important; }
    .sparkline { height: 24px !important; }
    .value-md { font-size: 0.95rem !important; }
    #mc-home-circuits { font-size: 0.68rem !important; }

    /* ── Trading page ── */
    .td-top { grid-template-columns: 150px 1fr 180px !important; gap: 6px !important; padding: 6px 8px 4px !important; }
    .td-bottom { padding: 0 8px 6px !important; }
    #td-totals-bar { padding: 4px 10px !important; gap: 12px !important; }
    #td-totals-bar > div > div:last-child { font-size: 0.95rem !important; }
    .tab-status-bar { min-height: auto !important; padding: 3px 10px !important; }
    #csub-trading .glass-card { padding: 6px 8px !important; }

    /* ── Backup/Battery page ── */
    .bi-layout { gap: 6px !important; padding: 6px 8px !important; }
    .scenario-hours { font-size: 1.1rem !important; }
  }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head>
<body>

<header>
  <div class="header-top">
    <a href="/" class="logo" style="text-decoration:none;color:inherit">🏠 <span>Jarvis Home</span></a>
    <div class="status-bar">
      <div id="span-dot" class="dot offline" title="SPAN Panel"></div>
      <div id="enphase-dot" class="dot offline" title="Enphase"></div>
      <div id="pentair-dot" class="dot offline" title="Pentair"></div>
      <div id="tesla-dot" class="dot offline" title="Tesla Gateway"></div>
      <div id="wc-dot" class="dot offline" title="Wall Connector"></div>
      <span class="ts" id="ts">—</span>
    </div>
  </div>
</header>

<!-- ── Left Rail Navigation ──────────────────────────────────────────── -->
<nav id="left-rail">
  <button class="rail-btn active" data-rail="energy" onclick="showView('energy')">
    <span class="rail-icon">&#9889;</span>
    <span class="rail-label">Energy</span>
  </button>
  <button class="rail-btn" data-rail="pool" onclick="showView('pool')">
    <span class="rail-icon">&#127946;</span>
    <span class="rail-label">Pool</span>
  </button>
  <button class="rail-btn" data-rail="climate" onclick="showView('climate')">
    <span class="rail-icon">&#127777;</span>
    <span class="rail-label">Thermo</span>
  </button>
  <button class="rail-btn" data-rail="sprinklers" onclick="showView('sprinklers')">
    <span class="rail-icon">&#128167;</span>
    <span class="rail-label">Irrigation</span>
  </button>
  <button class="rail-btn" data-rail="cameras" onclick="showView('cameras')">
    <span class="rail-icon">&#128247;</span>
    <span class="rail-label">Cameras</span>
  </button>
  <button class="rail-btn" data-rail="ring" onclick="showView('ring')">
    <span class="rail-icon">&#128276;</span>
    <span class="rail-label">Doorbell</span>
  </button>
  <button class="rail-btn" data-rail="appliances" onclick="showView('appliances')">
    <span class="rail-icon">&#129767;</span>
    <span class="rail-label">Appliances</span>
  </button>
  <button class="rail-btn" data-rail="roku" onclick="showView('roku')">
    <span class="rail-icon">&#128250;</span>
    <span class="rail-label">TV</span>
  </button>
  <button class="rail-btn" data-rail="settings" onclick="showView('settings')">
    <span class="rail-icon">&#9881;</span>
    <span class="rail-label">Settings</span>
  </button>
</nav>

<!-- ── Sub-Rail Navigation ────────────────────────────────────────────── -->
<nav id="sub-rail">
  <!-- Energy sub-pages -->
  <div id="sr-energy" style="display:none;flex-direction:column;width:100%">
    <button class="sub-rail-btn active" data-sub="ck-microgrid" onclick="navCockpit('microgrid')">&#9889; Microgrid</button>
    <button class="sub-rail-btn" data-sub="ck-live" onclick="navCockpit('live')">&#127760; Live Flow</button>
    <button class="sub-rail-btn" data-sub="ck-trading" onclick="navCockpit('trading')">&#128200; Trading</button>
    <button class="sub-rail-btn" data-sub="ck-backup" onclick="navCockpit('backup')">&#128267; Backup</button>
    <button class="sub-rail-btn" data-sub="solar" onclick="showEnergySub('solar')">&#9728; Solar</button>
    <button class="sub-rail-btn" data-sub="span" onclick="showEnergySub('span')">&#128268; SPAN</button>
    <button class="sub-rail-btn" data-sub="tesla-energy" onclick="showEnergySub('tesla-energy')"><img src="/static/img/tesla-logo.svg" height="12" style="vertical-align:middle;margin-right:5px;filter:brightness(10) opacity(0.7)">Tesla</button>
    <button class="sub-rail-btn" data-sub="cybertruck" onclick="showEnergySub('cybertruck')"><img src="/static/img/cybertruck.png" height="14" style="vertical-align:middle;margin-right:5px;filter:brightness(1.2)">Cybertruck</button>
  </div>
  <!-- Climate sub-pages — Thermostat only, no sub-pages needed -->
  <div id="sr-climate" style="display:none;flex-direction:column;width:100%">
    <button class="sub-rail-btn active" data-sub="home-control" onclick="showClimateSub('home-control')">&#127777; Thermostat</button>
  </div>
</nav>

<!-- ── Active Appliance Banner (always visible when something is running) ── -->
<div id="appliance-banner" style="display:none;background:rgba(16,185,129,0.08);border-bottom:1px solid rgba(16,185,129,0.2);padding:6px 16px;font-size:12px;display:flex;align-items:center;gap:12px;flex-wrap:wrap"></div>

<main>

<!-- ═══ HOME DASHBOARD ═══════════════════════════════════════════════════════ -->


<!-- ═══ ENERGY WRAPPER (sub-nav moved to header) ══════════════════════════════ -->
<div id="view-energy" class="view active"></div>

<!-- ═══ CLIMATE WRAPPER ════════════════════════════════════════════════════ -->
<div id="view-climate" class="view" style="display:none"></div>

<!-- ═══ ENTERTAINMENT WRAPPER ════════════════════════════════════════════════ -->
<div id="view-entertainment" class="view"></div>

<!-- ═══ ENERGY COCKPIT ═══════════════════════════════════════════════════════ -->
<div id="view-cockpit" class="view" style="display:none">

<div id="cockpit-panels">


<div id="csub-microgrid" class="tablet-view">
  <div class="tab-status-bar" style="min-height:auto;gap:8px;padding:4px 10px;">
    <span class="sb-time" id="mc-time" style="font-size:0.82rem;font-weight:800">--:--</span>
    <span class="sb-rate off-peak" id="mc-rate" style="font-size:0.82rem">Off-Peak</span>
    <span id="mc-weather" style="opacity:0.7;font-size:0.82rem">Queen Creek, AZ</span>
    <span style="flex:1"></span>
    <span id="mc-banner-solar" style="color:#FFD700;font-weight:700;font-size:0.82rem">☀ — kW</span>
    <span id="mc-banner-load" style="color:#9B59B6;font-weight:700;font-size:0.82rem">🏠 — kW</span>
    <span id="mc-banner-grid" style="color:#3B82F6;font-weight:700;font-size:0.82rem">⚡ — kW</span>
    <span id="mc-banner-cost" style="color:#10b981;font-weight:700;font-size:0.82rem">$—/hr</span>
    <span id="mc-banner-coverage" style="color:#FFD700;font-weight:700;font-size:0.82rem">—% ☀</span>
    <span class="sb-grid up" id="mc-grid-status" style="font-size:0.82rem">Grid ✓</span>
    <span id="mc-island-badge" class="island-badge" style="display:none;font-size:0.82rem">⚡ ISLANDED</span>
  </div>
  <div class="mc-layout">
    <!-- LEFT — Sources -->
    <div class="mc-left">
      <div class="glass-card" id="mc-solar-card" style="border-color:rgba(255,215,0,0.3)">
        <span class="label-sm">Solar Production</span>
        <div style="display:flex;align-items:baseline;gap:5px">
          <div class="hero-num" id="mc-solar-total-kw" style="color:#FFD700">--</div>
          <span style="font-size:0.85rem;color:rgba(255,255,255,0.4)">kW</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 8px;margin-top:10px;font-size:0.78rem">
          <div style="opacity:0.55">Enphase</div><div style="opacity:0.55">SolarEdge</div>
          <div id="mc-enphase-sub" style="color:#FFD700;font-weight:600">--</div>
          <div id="mc-solaredge-sub" style="color:#FFC200;font-weight:600">--</div>
        </div>
        <canvas id="mc-solar-spark" class="sparkline" style="margin-top:8px"></canvas>
      </div>
      <div class="glass-card" id="mc-grid-card" style="border-color:rgba(59,130,246,0.3)">
        <span class="label-sm">SRP Grid</span>
        <div style="display:flex;align-items:baseline;gap:5px">
          <div class="hero-num" id="mc-grid-kw" style="color:#3B82F6">—</div>
          <span style="font-size:0.85rem;color:rgba(255,255,255,0.4)">kW</span>
        </div>
        <div id="mc-grid-direction" style="font-size:10px;opacity:0.5;margin-top:2px">—</div>
        <canvas id="mc-grid-spark" class="sparkline" style="margin-top:8px"></canvas>
      </div>
    </div>
    <!-- CENTER — Topology canvas + hero overlay -->
    <div class="mc-center">
      <canvas id="mc-canvas"></canvas>
      <div class="mc-overlay">
        <div class="glass-card mc-hero" style="min-width:240px;padding:20px">
          <span class="label-sm" style="text-align:center;display:block;margin-bottom:6px">NET FLOW</span>
          <div style="font-size:3rem;font-weight:800;line-height:1;font-variant-numeric:tabular-nums" id="mc-net-kw">—</div>
          <div style="font-size:0.85rem;opacity:0.45;margin-top:2px" id="mc-net-direction">kW</div>
          <div style="margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;text-align:left">
            <div><span class="label-sm">Home Load</span><div class="value-md" id="mc-home-kw">—</div></div>
            <div><span class="label-sm">Cost/hr</span><div class="value-md" id="mc-cost-hr" style="color:#10b981">—</div></div>
            <div><span class="label-sm">Solar Cover</span><div class="value-md" id="mc-solar-pct">—</div></div>
            <div><span class="label-sm">15-min Demand</span><div class="value-md" id="mc-demand-15m">—</div></div>
            <div style="grid-column:1/-1"><span class="label-sm">Session Peak</span><div class="value-md" id="mc-session-peak">—</div></div>
          </div>
        </div>
      </div>
    </div>
    <!-- RIGHT — Loads -->
    <div class="mc-right">
      <div class="glass-card" id="mc-home-card" style="flex:2;min-height:0;overflow:hidden;display:flex;flex-direction:column">
        <span class="label-sm">Home Panel</span>
        <div style="display:flex;align-items:baseline;gap:5px">
          <div class="hero-num" id="mc-home-load-kw" style="color:#9B59B6">—</div>
          <span style="font-size:0.85rem;color:rgba(255,255,255,0.4)">kW</span>
        </div>
        <canvas id="mc-home-spark" class="sparkline" style="margin-top:6px;flex-shrink:0"></canvas>
        <div id="mc-home-circuits" style="margin-top:6px;font-size:0.75rem;overflow:hidden;flex:1"></div>
      </div>
      <div class="glass-card" id="mc-pool-card" style="padding:8px 12px;flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column">
        <span class="label-sm">Pool Sub-Panel</span>
        <div style="display:flex;align-items:baseline;gap:4px">
          <div style="font-size:1.4rem;font-weight:800;font-variant-numeric:tabular-nums;color:#06b6d4" id="mc-pool-kw">—</div>
          <span style="font-size:0.75rem;color:rgba(255,255,255,0.4)">kW</span>
        </div>
        <div id="mc-pool-status" style="font-size:10px;opacity:0.5;margin-top:2px">—</div>
        <canvas id="mc-pool-spark" class="sparkline" style="margin-top:4px;height:22px"></canvas>
      </div>
      <div class="glass-card" id="mc-truck-card" style="border-color:rgba(0,255,255,0.3);padding:8px 12px;flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column">
        <span class="label-sm">Cybertruck</span>
        <div style="display:flex;align-items:baseline;gap:4px">
          <div style="font-size:1.4rem;font-weight:800;font-variant-numeric:tabular-nums;color:#00FFFF" id="mc-truck-kw">—</div>
          <span style="font-size:0.75rem;color:rgba(255,255,255,0.4)">kW</span>
        </div>
        <div id="mc-truck-mode" style="font-size:10px;opacity:0.5;margin-top:2px">Idle</div>
        <canvas id="mc-truck-spark" class="sparkline" style="margin-top:4px;height:22px"></canvas>
      </div>
    </div>
  </div>
</div><!-- /csub-microgrid -->

<div id="csub-live" style="display:flex;flex-direction:column;overflow:hidden">

  <!-- Animated Power Flow — flex:1 so it fills all available vertical space -->
  <div class="card" style="padding:0;overflow:hidden;flex:1;min-height:0;display:flex;flex-direction:column;margin-bottom:4px">
    <div style="padding:12px 16px 4px;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:13px;font-weight:600;color:var(--text)">&#x26A1; Live Power Flow</span>
      <span style="font-size:11px;color:var(--text-dim)" id="flow-total-label">Total load: &#x2014; W</span>
    </div>
    <svg id="power-flow-svg" viewBox="0 15 700 430" preserveAspectRatio="xMidYMid meet"
         style="width:100%;flex:1;min-height:0;display:block;max-height:none">

      <defs>
        <!-- Glow for active particles -->
        <filter id="pf-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
        <!-- Arrow markers -->
        <marker id="arr-solar" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#f59e0b"/>
        </marker>
        <marker id="arr-grid" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#f97316"/>
        </marker>
        <marker id="arr-bridge" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#f97316" opacity="0.7"/>
        </marker>
        <marker id="arr-ev" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#22d3ee"/>
        </marker>
        <marker id="arr-house" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#8b5cf6"/>
        </marker>
        <marker id="arr-pool" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#06b6d4"/>
        </marker>
      </defs>

      <!--
        LAYOUT (all coords absolute):
        ROW 1 (y=20–84):   [SRP GRID cx=85]  [ENPHASE cx=350]  [SOLAREDGE cx=615]
        bus y=123 — sources converge horizontally then drop to gateway
        ROW 2 (y=162–234): [TESLA GATEWAY 3V cx=350] — centered hub
        bus y=252 — gateway distributes left→Home, right→CT
        ROW 3 (y=270–334): [HOME PANEL cx=170]              [CYBERTRUCK cx=530]
        ROW 4 (y=362–426): [POOL cx=170] — directly below Home
      -->

      <!-- ── PATHS (behind nodes) ── -->

      <!-- Enphase → Tesla Gateway (straight vertical — center aligned) -->
      <path id="path-solar-span" d="M 350,84 L 350,162"
            stroke="#f59e0b" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-solar)"/>

      <!-- SolarEdge → bus → Tesla Gateway (right-angle bends) -->
      <path id="path-solar2-span" d="M 615,84 L 615,123 L 350,123 L 350,162"
            stroke="#f59e0b" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-solar)"/>

      <!-- SRP Grid → bus → Tesla Gateway (right-angle bends) -->
      <path id="path-grid-gw" d="M 85,84 L 85,123 L 350,123 L 350,162"
            stroke="#f97316" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-grid)"/>

      <!-- Tesla Gateway → Home Panel (center → left, right-angle) -->
      <path id="path-gw-span" d="M 350,234 L 350,252 L 170,252 L 170,270"
            stroke="#8b5cf6" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-house)"/>

      <!-- Tesla Gateway → Cybertruck CT (center → right, right-angle) -->
      <path id="path-gw-ct" d="M 350,234 L 350,252 L 530,252 L 530,270"
            stroke="#22d3ee" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-ev)"/>

      <!-- Home Panel → Pool (straight vertical) -->
      <path id="path-home-pool" d="M 170,334 L 170,362"
            stroke="#06b6d4" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-pool)"/>

      <!-- Bridge: SRP Grid → Home Panel direct (Tesla GW offline — routes above gateway) -->
      <path id="path-grid-span" d="M 85,84 L 85,140 L 170,140 L 170,270"
            stroke="#f97316" stroke-width="2" fill="none" opacity="0"
            stroke-dasharray="6 8" marker-end="url(#arr-bridge)"/>

      <!-- Bridge: SRP Grid → CT Charger direct (Tesla GW offline — routes above gateway) -->
      <path id="path-grid-ct" d="M 85,84 L 85,140 L 530,140 L 530,270"
            stroke="#22d3ee" stroke-width="2" fill="none" opacity="0"
            stroke-dasharray="6 8" marker-end="url(#arr-ev)"/>

      <!-- ── PARTICLE GROUPS (animateMotion dots, staggered) ── -->

      <g id="part-solar-span" visibility="hidden">
        <circle r="4.5" fill="#f59e0b" filter="url(#pf-glow)">
          <animateMotion dur="1.5s" begin="0s" repeatCount="indefinite"><mpath href="#path-solar-span"/></animateMotion>
        </circle>
        <circle r="3" fill="#f59e0b" opacity="0.65">
          <animateMotion dur="1.5s" begin="-0.5s" repeatCount="indefinite"><mpath href="#path-solar-span"/></animateMotion>
        </circle>
        <circle r="2" fill="#f59e0b" opacity="0.4">
          <animateMotion dur="1.5s" begin="-1s" repeatCount="indefinite"><mpath href="#path-solar-span"/></animateMotion>
        </circle>
      </g>

      <g id="part-solar2-span" visibility="hidden">
        <circle r="4.5" fill="#f59e0b" filter="url(#pf-glow)">
          <animateMotion dur="1.5s" begin="0s" repeatCount="indefinite"><mpath href="#path-solar2-span"/></animateMotion>
        </circle>
        <circle r="3" fill="#f59e0b" opacity="0.65">
          <animateMotion dur="1.5s" begin="-0.5s" repeatCount="indefinite"><mpath href="#path-solar2-span"/></animateMotion>
        </circle>
        <circle r="2" fill="#f59e0b" opacity="0.4">
          <animateMotion dur="1.5s" begin="-1s" repeatCount="indefinite"><mpath href="#path-solar2-span"/></animateMotion>
        </circle>
      </g>

      <g id="part-grid-gw" visibility="hidden">
        <circle r="4.5" fill="#f97316" filter="url(#pf-glow)">
          <animateMotion dur="1.5s" begin="0s" repeatCount="indefinite"><mpath href="#path-grid-gw"/></animateMotion>
        </circle>
        <circle r="3" fill="#f97316" opacity="0.65">
          <animateMotion dur="1.5s" begin="-0.5s" repeatCount="indefinite"><mpath href="#path-grid-gw"/></animateMotion>
        </circle>
        <circle r="2" fill="#f97316" opacity="0.4">
          <animateMotion dur="1.5s" begin="-1s" repeatCount="indefinite"><mpath href="#path-grid-gw"/></animateMotion>
        </circle>
      </g>

      <g id="part-gw-span" visibility="hidden">
        <circle r="4.5" fill="#8b5cf6" filter="url(#pf-glow)">
          <animateMotion dur="1.5s" begin="0s" repeatCount="indefinite"><mpath href="#path-gw-span"/></animateMotion>
        </circle>
        <circle r="3" fill="#8b5cf6" opacity="0.65">
          <animateMotion dur="1.5s" begin="-0.5s" repeatCount="indefinite"><mpath href="#path-gw-span"/></animateMotion>
        </circle>
      </g>

      <g id="part-grid-span" visibility="hidden">
        <circle r="4" fill="#f97316" filter="url(#pf-glow)" opacity="0.85">
          <animateMotion dur="1.5s" begin="0s" repeatCount="indefinite"><mpath href="#path-grid-span"/></animateMotion>
        </circle>
        <circle r="2.5" fill="#f97316" opacity="0.5">
          <animateMotion dur="1.5s" begin="-0.5s" repeatCount="indefinite"><mpath href="#path-grid-span"/></animateMotion>
        </circle>
      </g>

      <g id="part-home-pool" visibility="hidden">
        <circle r="4" fill="#06b6d4" filter="url(#pf-glow)">
          <animateMotion dur="1.5s" begin="0s" repeatCount="indefinite"><mpath href="#path-home-pool"/></animateMotion>
        </circle>
        <circle r="2.5" fill="#06b6d4" opacity="0.55">
          <animateMotion dur="1.5s" begin="-0.5s" repeatCount="indefinite"><mpath href="#path-home-pool"/></animateMotion>
        </circle>
      </g>

      <g id="part-gw-ct" visibility="hidden">
        <circle r="4" fill="#22d3ee" filter="url(#pf-glow)">
          <animateMotion dur="1.5s" begin="0s" repeatCount="indefinite"><mpath href="#path-gw-ct"/></animateMotion>
        </circle>
        <circle r="2.5" fill="#22d3ee" opacity="0.55">
          <animateMotion dur="1.5s" begin="-0.5s" repeatCount="indefinite"><mpath href="#path-gw-ct"/></animateMotion>
        </circle>
      </g>

      <g id="part-grid-ct" visibility="hidden">
        <circle r="4" fill="#22d3ee" filter="url(#pf-glow)">
          <animateMotion dur="1.5s" begin="0s" repeatCount="indefinite"><mpath href="#path-grid-ct"/></animateMotion>
        </circle>
        <circle r="2.5" fill="#22d3ee" opacity="0.55">
          <animateMotion dur="1.5s" begin="-0.5s" repeatCount="indefinite"><mpath href="#path-grid-ct"/></animateMotion>
        </circle>
      </g>

      <!-- ── NODES ── -->

      <!-- ROW 1: Sources — evenly spaced (gap=135px each side) -->

      <!-- SRP Grid node (top-left, cx=85) -->
      <g id="node-grid" transform="translate(20,20)" style="cursor:pointer" onclick="showView('tesla-energy')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect id="rect-grid" rx="12" ry="12" width="130" height="64" fill="#1c1917" stroke="#f97316" stroke-width="1.5"/>
        <text x="65" y="20" text-anchor="middle" font-size="17" fill="#f97316">&#x1F50C;</text>
        <text x="65" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">SRP GRID</text>
        <text id="lbl-grid" x="65" y="53" text-anchor="middle" font-size="13" fill="#f97316" font-weight="bold" font-family="sans-serif">&#x2014; W</text>
        <text id="lbl-grid-sub" x="65" y="72" text-anchor="middle" font-size="8" fill="#a3a3a3" font-family="sans-serif" visibility="hidden">&#x2014;</text>
      </g>

      <!-- Enphase Solar node (top-center, cx=350 — directly above gateway) -->
      <g id="node-solar" transform="translate(285,20)" style="cursor:pointer" onclick="showView('solar')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="130" height="64" fill="#1c1917" stroke="#f59e0b" stroke-width="1.5"/>
        <text x="65" y="20" text-anchor="middle" font-size="17" fill="#f59e0b">&#x2600;&#xFE0F;</text>
        <text x="65" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">ENPHASE</text>
        <text id="lbl-solar" x="65" y="53" text-anchor="middle" font-size="13" fill="#f59e0b" font-weight="bold" font-family="sans-serif">&#x2014; W</text>
      </g>

      <!-- SolarEdge node (top-right, cx=615) -->
      <g id="node-solar2" transform="translate(550,20)" style="cursor:pointer" onclick="showView('solar')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="130" height="64" fill="#1c1917" stroke="#f59e0b" stroke-width="1.5"/>
        <text x="65" y="20" text-anchor="middle" font-size="17" fill="#f59e0b">&#x2600;&#xFE0F;</text>
        <text x="65" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">SOLAREDGE</text>
        <text id="lbl-solar2" x="65" y="53" text-anchor="middle" font-size="13" fill="#f59e0b" font-weight="bold" font-family="sans-serif">&#x2014; W</text>
      </g>

      <!-- ROW 2: Tesla Gateway — centered hub (cx=350) -->
      <g id="node-gateway" transform="translate(280,162)" style="cursor:pointer" onclick="showView('tesla-energy')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="140" height="72" fill="#1c1917" stroke="#3b82f6" stroke-width="1.5"/>
        <text x="70" y="20" text-anchor="middle" font-size="17" fill="#3b82f6">&#x1F50B;</text>
        <text x="70" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">TESLA GATEWAY 3V</text>
        <text id="lbl-gw" x="70" y="52" text-anchor="middle" font-size="12" fill="#94a3b8" font-family="sans-serif">&#x2014;</text>
        <text id="lbl-gw-soe" x="70" y="65" text-anchor="middle" font-size="10" fill="#60a5fa" font-family="sans-serif">&#x2014;</text>
      </g>

      <!-- ROW 3: Loads -->

      <!-- Home Panel node (left, cx=170) -->
      <g id="node-home" transform="translate(105,270)" style="cursor:pointer" onclick="showView('span')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="130" height="64" fill="#1c1917" stroke="#8b5cf6" stroke-width="1.5"/>
        <text x="65" y="20" text-anchor="middle" font-size="17" fill="#8b5cf6">&#x1F3E0;</text>
        <text x="65" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">HOME PANEL</text>
        <text id="lbl-home" x="65" y="53" text-anchor="middle" font-size="13" fill="#8b5cf6" font-weight="bold" font-family="sans-serif">&#x2014; W</text>
      </g>

      <!-- Cybertruck CT node (right, cx=530) -->
      <g id="node-ct" transform="translate(465,270)" style="cursor:pointer" onclick="showView('cybertruck')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="130" height="64" fill="#1c1917" stroke="#22d3ee" stroke-width="1.5"/>
        <text x="65" y="20" text-anchor="middle" font-size="17" fill="#22d3ee">&#x1F697;</text>
        <text x="65" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">CYBERTRUCK CT</text>
        <text id="lbl-ct" x="65" y="53" text-anchor="middle" font-size="12" fill="#22d3ee" font-weight="bold" font-family="sans-serif">idle</text>
      </g>

      <!-- ROW 4: Sub-loads -->

      <!-- Pool node (below Home Panel, cx=170 — straight vertical path) -->
      <g id="node-pool" transform="translate(105,362)" style="cursor:pointer" onclick="showView('pool')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="130" height="64" fill="#1c1917" stroke="#06b6d4" stroke-width="1.5"/>
        <text x="65" y="20" text-anchor="middle" font-size="17" fill="#06b6d4">&#x1F3CA;</text>
        <text x="65" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">POOL</text>
        <text id="lbl-pool" x="65" y="53" text-anchor="middle" font-size="12" fill="#06b6d4" font-weight="bold" font-family="sans-serif">&#x2014; W</text>
      </g>

      <!-- Bridge mode label (shown when Tesla offline) -->
      <g id="pf-bridge-label" visibility="hidden">
        <rect x="250" y="144" rx="6" ry="6" width="200" height="17" fill="#1c1917" stroke="#f97316" stroke-width="0.8" stroke-dasharray="3 2" opacity="0.85"/>
        <text x="350" y="156" text-anchor="middle" font-size="8.5" fill="#f97316" font-family="sans-serif">&#x26A1; SPAN-bridged &#xB7; no Tesla GW</text>
      </g>

      <!-- Normal source label (shown when Tesla online) -->
      <g id="pf-source-label" visibility="visible">
        <text x="350" y="432" text-anchor="middle" font-size="9" fill="#4b5563" font-family="sans-serif">Jarvis bridges SPAN + Tesla Gateway data</text>
      </g>

    </svg>
  </div>

  <!-- Legacy hidden elements for backward compat with renderState refs -->
  <span id="f-solar" style="display:none"></span>
  <span id="f-load" style="display:none"></span>
  <span id="f-battery" style="display:none"></span>
  <span id="f-soe" style="display:none"></span>
  <span id="f-grid" style="display:none"></span>
  <span id="f-grid-dir" style="display:none"></span>

  <!-- Metric Cards — flex-shrink:0 so SVG above gets remaining space -->
  <div class="grid grid-4" style="margin-bottom:4px;flex-shrink:0;padding:0 8px">
    <div class="card energy-solar">
      <div class="card-header">
        <span class="card-title">Solar Production</span>
        <span class="badge online" id="enphase-badge">online</span>
      </div>
      <div class="big-val c-solar" id="solar-w">—</div>
      <span class="big-unit">W</span>
      <div class="sub-val" id="solar-sub">Enphase IQ · 192.168.68.63</div>
    </div>

    <div class="card" style="border-color:rgba(0,255,255,0.2)">
      <div class="card-header">
        <span class="card-title">Cybertruck</span>
        <span class="badge" id="ct-lm-badge" style="background:rgba(0,255,255,0.15);color:#22d3ee">—</span>
      </div>
      <div class="big-val" id="ct-lm-soc" style="color:#22d3ee">—</div>
      <span class="big-unit">%</span>
      <div class="sub-val" id="ct-lm-sub">Wall Connector · —</div>
    </div>

    <div class="card energy-grid">
      <div class="card-header">
        <span class="card-title">Grid</span>
        <span class="badge offline" id="grid-badge">—</span>
      </div>
      <div class="big-val c-grid" id="grid-w">—</div>
      <span class="big-unit">W</span>
      <div class="sub-val" id="grid-dir">import / export</div>
    </div>

    <div class="card energy-load">
      <div class="card-header">
        <span class="card-title">Home Load</span>
        <span class="badge online">live</span>
      </div>
      <div class="big-val c-load" id="load-w">—</div>
      <span class="big-unit">W</span>
      <div class="sub-val" id="load-sub">Total consumption</div>
    </div>
  </div>

  <!-- Self-Powered + Pool + Nest -->
  <div class="row" style="flex-shrink:0;margin-bottom:0;padding:0 8px">
    <div class="card">
      <div class="card-header"><span class="card-title">Solar Self-Powered</span></div>
      <div class="big-val" id="self-pct" style="color:var(--solar)">—</div><span class="big-unit">%</span>
      <div class="bar-bg"><div class="bar-fill" id="self-bar" style="width:0%"></div></div>
      <div class="sub-val">of home load powered by solar</div>
    </div>

    <div class="card energy-pool">
      <div class="card-header">
        <span class="card-title">Pool System</span>
        <span class="badge online" id="pentair-badge">online</span>
      </div>
      <div style="display:flex;gap:20px;flex-wrap:wrap">
        <div>
          <div class="sub-val">Pool Temp</div>
          <div class="big-val c-pool" id="pool-temp">—</div><span class="big-unit">°F</span>
        </div>
        <div>
          <div class="sub-val">Pump</div>
          <div class="big-val" id="pump-rpm" style="color:var(--text)">—</div><span class="big-unit">RPM</span>
        </div>
        <div>
          <div class="sub-val">Pump Power</div>
          <div class="big-val" id="pump-w" style="color:var(--pool)">—</div><span class="big-unit">W</span>
        </div>
      </div>
      <div class="sub-val" id="pool-status-line" style="margin-top:8px;display:none">—</div>
    </div>

    <div class="card" style="cursor:pointer" onclick="showView('home-control')" title="Click for thermostat control">
      <div class="card-header">
        <span class="card-title">🌡️ Thermostat</span>
        <span class="badge" id="nest-cockpit-badge">unconfigured</span>
      </div>
      <div id="nest-cockpit-content">
        <div style="color:var(--text-dim);font-size:11px">Not configured — click to set up</div>
      </div>
    </div>
  </div>

</div><!-- /csub-live -->

<div id="csub-trading" class="tablet-view">
  <div class="tab-status-bar" style="font-size:0.82rem;padding:3px 10px;gap:10px;min-height:auto;flex-wrap:wrap;flex-shrink:0">
    <span id="td-time" style="font-weight:800">--:--</span>
    <span class="sb-rate off-peak" id="td-rate" style="font-size:0.82rem;padding:2px 6px">Off-Peak</span>
    <span id="td-weather" style="opacity:0.85">☀ --</span>
    <span style="flex:1"></span>
    <span style="font-size:0.85rem;opacity:0.45" id="td-last-update">--</span>
  </div>
  <div id="td-totals-bar" style="display:flex;gap:16px;padding:4px 10px;background:rgba(255,255,255,0.03);border-bottom:1px solid rgba(255,255,255,0.06);flex-shrink:0;flex-wrap:wrap;align-items:center">
    <div style="text-align:center"><div class="label-sm">Solar</div><div id="td-total-solar" style="color:#FFD700;font-size:0.95rem;font-weight:800">--</div></div>
    <div style="text-align:center"><div class="label-sm">Load</div><div id="td-total-load" style="color:#9B59B6;font-size:0.95rem;font-weight:800">--</div></div>
    <div style="text-align:center"><div class="label-sm">Grid</div><div id="td-total-grid" style="color:#3B82F6;font-size:0.95rem;font-weight:800">--</div></div>
    <div style="text-align:center"><div class="label-sm">Coverage</div><div id="td-total-coverage" style="color:#10b981;font-size:0.95rem;font-weight:800">--</div></div>
    <div style="text-align:center"><div class="label-sm">Cost/hr</div><div id="td-total-cost" style="color:#10b981;font-size:0.95rem;font-weight:800">--</div></div>
    <div style="text-align:center"><div class="label-sm">$/kWh</div><div style="color:#10b981;font-size:0.95rem;font-weight:800">$0.18</div></div>
  </div>
  <div class="td-layout">
    <div class="td-top">
      <!-- LEFT — Solar Production -->
      <div class="td-col">
        <div class="glass-card" style="flex-shrink:0">
          <span class="label-sm">Enphase Production</span>
          <div class="value-md" id="td-enphase-kw" style="color:#FFD700;font-size:1.2rem">— <span style="font-size:0.8rem;opacity:0.4">kW</span></div>
          <canvas class="sparkline" id="td-enphase-spark"></canvas>
        </div>
        <div class="glass-card" style="flex-shrink:0">
          <span class="label-sm">SolarEdge Production</span>
          <div class="value-md" id="td-solaredge-kw" style="color:#FFC200;font-size:1.2rem">— <span style="font-size:0.8rem;opacity:0.4">kW</span></div>
          <canvas class="sparkline" id="td-solaredge-spark"></canvas>
        </div>
        <div class="glass-card" style="flex-shrink:0">
          <span class="label-sm">Combined Solar</span>
          <div class="value-md" id="td-total-solar-kw" style="font-size:2.4rem">— <span style="font-size:0.8rem;opacity:0.4">kW</span></div>
          <div style="font-size:10px;opacity:0.45;margin-top:4px" id="td-solar-capacity-pct">— % of 11.8 kW</div>
        </div>
      </div>
      <!-- CENTER — Sankey Distribution -->
      <div class="td-col" style="overflow:hidden">
        <div class="glass-card" style="flex:1;padding:12px;min-height:0;display:flex;flex-direction:column">
          <span class="label-sm" style="margin-bottom:6px">Live Energy Distribution</span>
          <canvas id="td-sankey-canvas" style="flex:1;width:100%;display:block;min-height:0"></canvas>
        </div>
      </div>
      <!-- RIGHT — Load Intelligence -->
      <div class="td-col" style="overflow:hidden">
        <div class="glass-card" style="flex:1;overflow:hidden;display:flex;flex-direction:column">
          <span class="label-sm" style="margin-bottom:8px;flex-shrink:0">Top Circuit Loads</span>
          <div id="td-circuit-bars" style="overflow-y:auto;flex:1;min-height:0"></div>
        </div>
      </div>
    </div><!-- /td-top -->
    <!-- BOTTOM — Demand strip -->
    <div class="td-bottom">
      <div class="glass-card" style="padding:5px 10px">
        <div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap">
          <div>
            <span class="label-sm">15-min Demand</span>
            <div class="value-md" id="td-demand-15m" style="font-size:1.1rem">— <span style="font-size:0.75rem;opacity:0.4">kW</span></div>
          </div>
          <div>
            <span class="label-sm">Session Peak</span>
            <div class="value-md" id="td-peak-proj" style="font-size:1.1rem">— <span style="font-size:0.8rem;opacity:0.4">kW</span></div>
          </div>
          <div style="text-align:center">
            <span class="label-sm">Cost/hr</span>
            <div id="td-cost-hr" style="color:#10b981;font-size:1.1rem;font-weight:700">--</div>
          </div>
          <div style="text-align:center">
            <span class="label-sm">Solar Coverage</span>
            <div id="td-solar-coverage" style="color:#FFD700;font-size:1.1rem;font-weight:700">--</div>
          </div>
          <div style="flex:1;min-width:120px">
            <span class="label-sm" style="margin-bottom:3px">Demand Exposure</span>
            <div style="height:7px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden">
              <div id="td-demand-bar" style="height:100%;width:0%;background:linear-gradient(90deg,#10b981,#f59e0b,#ef4444);border-radius:3px;transition:width 0.5s"></div>
            </div>
          </div>
          <canvas id="td-demand-chart" style="width:260px;height:42px;flex-shrink:0"></canvas>
        </div>
      </div>
    </div>
  </div>
</div><!-- /csub-trading -->

<div id="csub-backup" class="tablet-view">
  <div class="tab-status-bar" id="bi-statusbar">
    <span style="font-size:12px;font-weight:700">🔋 Backup Intelligence</span>
    <span id="bi-island-badge" class="island-badge" style="display:none">⚡ ISLANDED</span>
    <span style="flex:1"></span>
    <span style="font-size:10px;opacity:0.45" id="bi-last-update">—</span>
  </div>
  <div class="bi-layout">
    <!-- LEFT — Primary backup card -->
    <div class="bi-primary">
      <div class="glass-card" id="bi-main-card">
        <span class="label-sm" style="margin-bottom:8px">Backup Status — Cybertruck Powershare</span>
        <div style="display:flex;align-items:center;gap:14px">
          <canvas id="bi-soc-ring" width="110" height="110" style="flex-shrink:0"></canvas>
          <div>
            <div style="font-size:3rem;font-weight:800;line-height:1;font-variant-numeric:tabular-nums" id="bi-soc-pct"><span style="font-size:1rem;opacity:0.35">No data</span></div>
            <div style="font-size:11px;opacity:0.4;margin-top:3px">Cybertruck SoC</div>
            <div style="margin-top:8px"><span class="badge offline" id="bi-readiness-badge">No Data</span></div>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px">
          <div><span class="label-sm">Discharge Rate</span><div class="value-md" id="bi-discharge-kw">— <span style="font-size:0.8rem;opacity:0.4">kW</span></div></div>
          <div><span class="label-sm">Est. Runtime</span><div class="value-md" id="bi-runtime-hr" style="color:#10b981">— <span style="font-size:0.8rem;opacity:0.4">hrs</span></div></div>
        </div>
      </div>
      <!-- Runtime Scenarios -->
      <div class="glass-card" style="flex-shrink:0">
        <span class="label-sm" style="margin-bottom:8px">Runtime Scenarios (~95 kWh usable)</span>
        <div class="scenario-row">
          <div><div class="scenario-label">Critical Loads Only</div><div style="font-size:9px;opacity:0.4">~1.5 kW — bedroom, office, hallway</div></div>
          <div class="scenario-hours" style="color:#10b981" id="bi-rt-critical">— <span style="font-size:0.8rem;opacity:0.4">h</span></div>
        </div>
        <div class="scenario-row">
          <div><div class="scenario-label">Current Load</div><div style="font-size:9px;opacity:0.4" id="bi-current-load-label">—</div></div>
          <div class="scenario-hours" style="color:#f59e0b" id="bi-rt-current">— <span style="font-size:0.8rem;opacity:0.4">h</span></div>
        </div>
        <div class="scenario-row" style="margin-bottom:0">
          <div><div class="scenario-label">Peak (session max)</div><div style="font-size:9px;opacity:0.4" id="bi-peak-load-label">—</div></div>
          <div class="scenario-hours" style="color:#ef4444" id="bi-rt-peak">— <span style="font-size:0.8rem;opacity:0.4">h</span></div>
        </div>
      </div>
    </div><!-- /bi-primary -->

    <!-- RIGHT TOP — Load Shedding -->
    <div class="bi-secondary">
      <div class="glass-card" style="height:100%;overflow:hidden">
        <span class="label-sm" style="margin-bottom:8px">Load Shedding Priority</span>
        <div class="priority-item shed-first" id="shed-row-pool">
          <div class="priority-num" style="color:#ef4444">1</div>
          <div class="priority-name">Pool Sub-Panel <span id="shed-badge-pool" style="display:none;font-size:9px;padding:1px 5px;border-radius:3px;background:rgba(239,68,68,.25);color:#ef4444;margin-left:4px;">OFF</span></div>
          <div class="priority-kw" id="bi-pool-kw">—</div>
          <button id="shed-btn-pool" class="shed-btn" onclick="shedCircuit('pool')">Shed</button>
          <button id="restore-btn-pool" class="shed-btn" onclick="restoreCircuit('pool')" style="display:none;border-color:rgba(74,222,128,.5);background:rgba(74,222,128,.1);color:#4ade80;">Restore</button>
        </div>
        <div class="priority-item shed-second" id="shed-row-ev">
          <div class="priority-num" style="color:#f59e0b">2</div>
          <div class="priority-name">EV Charging (Wall Connector) <span id="shed-badge-ev" style="display:none;font-size:9px;padding:1px 5px;border-radius:3px;background:rgba(239,68,68,.25);color:#ef4444;margin-left:4px;">OFF</span></div>
          <div class="priority-kw" id="bi-ev-kw">—</div>
          <button id="shed-btn-ev" class="shed-btn" onclick="shedCircuit('ev')">Shed</button>
          <button id="restore-btn-ev" class="shed-btn" onclick="restoreCircuit('ev')" style="display:none;border-color:rgba(74,222,128,.5);background:rgba(74,222,128,.1);color:#4ade80;">Restore</button>
        </div>
        <div class="priority-item shed-third" id="shed-row-ac2">
          <div class="priority-num" style="color:#6366f1">3</div>
          <div class="priority-name">AC Condenser 2 <span id="shed-badge-ac2" style="display:none;font-size:9px;padding:1px 5px;border-radius:3px;background:rgba(239,68,68,.25);color:#ef4444;margin-left:4px;">OFF</span></div>
          <div class="priority-kw" id="bi-ac2-kw">—</div>
          <button id="shed-btn-ac2" class="shed-btn" onclick="shedCircuit('ac2')">Shed</button>
          <button id="restore-btn-ac2" class="shed-btn" onclick="restoreCircuit('ac2')" style="display:none;border-color:rgba(74,222,128,.5);background:rgba(74,222,128,.1);color:#4ade80;">Restore</button>
        </div>
        <div class="priority-item shed-nc">
          <div class="priority-num" style="color:rgba(255,255,255,0.3)">4</div>
          <div class="priority-name" style="opacity:0.45">Non-critical circuits</div>
          <div class="priority-kw">—</div>
        </div>
      </div>
    </div><!-- /bi-secondary -->

    <!-- RIGHT BOTTOM — Island Event Log -->
    <div class="bi-log">
      <div class="glass-card" style="height:100%;overflow:hidden">
        <span class="label-sm" style="margin-bottom:6px">Island Event Log</span>
        <div class="event-log" id="bi-event-log">
          <div><span class="ev-time">—</span>No events recorded</div>
        </div>
      </div>
    </div><!-- /bi-log -->
  </div>
</div><!-- /csub-backup -->

</div><!-- /cockpit-panels -->

<!-- cockpit-dots removed: navigation moved to Energy sub-rail -->

</div><!-- /cockpit -->


<!-- ═══ SOLAR PRODUCTION ═════════════════════════════════════════════════════ -->
<div id="view-solar" class="view">
  <h2 style="color:var(--solar)">☀️ Solar Production</h2>

  <!-- Enphase section -->
  <div class="card energy-solar" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <h3 style="margin:0;color:var(--solar)">Enphase IQ8PLUS</h3>
      <span id="solar-enphase-total" style="font-size:24px;font-weight:700;color:var(--solar)">— W</span>
    </div>
    <div style="font-size:12px;color:#94a3b8;margin-bottom:16px">
      20 microinverters · 5,961W capacity · SPAN branches 29+31
    </div>
    <!-- Inverter grid: 20 cards, 4 or 5 per row -->
    <div id="solar-inverter-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px">
      <!-- populated by JS -->
    </div>
    <div id="solar-inverter-status" style="margin-top:12px;font-size:12px;color:#94a3b8">Loading inverters...</div>
  </div>

  <!-- SolarEdge section -->
  <div class="card energy-solar">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <h3 style="margin:0;color:var(--solar)">SolarEdge SE5000H</h3>
      <span id="solar-se-total" style="font-size:24px;font-weight:700;color:var(--solar)">— W</span>
    </div>
    <div style="font-size:12px;color:#94a3b8">5kW string inverter · SPAN branches 30+32</div>
  </div>
</div><!-- /solar -->


<!-- ═══ SPAN CIRCUITS ════════════════════════════════════════════════════════ -->
<div id="view-span" class="view">
  <div class="row">
    <div class="card">
      <div class="card-header">
        <span class="card-title">SPAN Panel</span>
        <span class="badge" id="span-badge2">—</span>
      </div>
      <div class="device-detail" id="span-meta">Serial: nj-2307-006gl · 192.168.68.93</div>
      <div class="device-detail" id="span-grid-power" style="margin-top:6px">Grid: — W</div>
    </div>
  </div>

  <!-- ═══ SPAN ENERGY VISUALIZATION ════════════════════════════════════════ -->
  <div id="span-charts" style="display:none" class="span-viz">

    <!-- Row 1: Total Load Timeline + Power Donut -->
    <div class="chart-row">
      <div class="chart-card" style="flex:2;min-width:280px">
        <div class="chart-card-title">⚡ Total Load — Last 5 min <span id="span-timeline-now" style="color:#00d4ff;font-size:13px;font-weight:700">—</span></div>
        <div style="height:110px;position:relative"><canvas id="span-timeline-chart"></canvas></div>
      </div>
      <div class="chart-card" style="flex:0 0 260px">
        <div class="chart-card-title">🍩 Power Breakdown</div>
        <div style="height:170px;position:relative"><canvas id="span-donut-chart"></canvas></div>
        <div class="donut-total" id="span-donut-total">— W</div>
        <div class="donut-sub">total grid load</div>
      </div>
    </div>

    <!-- Row 2: Live Circuit Power Bar -->
    <div class="chart-card" style="margin-bottom:12px">
      <div class="chart-card-title">📊 Live Circuit Power <span style="color:rgba(255,255,255,0.28);font-size:10px">click a bar to inspect</span></div>
      <div id="span-bar-container" style="position:relative;height:320px"><canvas id="span-bar-chart"></canvas></div>
    </div>

    <!-- Row 3: Circuit Sparkline detail (shown on bar/tile click) -->
    <div class="chart-card" id="span-sparkline-card" style="display:none;margin-bottom:12px">
      <div class="sparkline-header">
        <div class="chart-card-title" style="margin-bottom:0;flex:1" id="span-sparkline-title">Circuit Detail</div>
        <div class="sparkline-stat">min: <span id="sk-min">—</span> W</div>
        <div class="sparkline-stat">avg: <span id="sk-avg">—</span> W</div>
        <div class="sparkline-stat">max: <span id="sk-max">—</span> W</div>
        <div class="sparkline-stat"><a href="#" onclick="document.getElementById('span-sparkline-card').style.display='none';selectedCircuit=null;return false" style="color:rgba(255,255,255,0.28);text-decoration:none">✕</a></div>
      </div>
      <div style="height:110px;position:relative"><canvas id="span-sparkline-chart"></canvas></div>
    </div>

    <!-- Row 4: Circuit History 60-min multi-line -->
    <div class="chart-card" style="margin-bottom:12px">
      <div class="chart-card-title">📈 Circuit History — Last 60 min <span style="color:rgba(255,255,255,0.28);font-size:10px">legend: click to toggle</span></div>
      <div style="height:300px;position:relative"><canvas id="span-history-chart"></canvas></div>
    </div>

  </div><!-- /span-charts -->

  <div class="section-title">Circuit Heatmap</div>
  <div id="span-no-token" style="display:none" class="card">
    <span class="badge warning">No SPAN token configured</span>
    <div class="sub-val" style="margin-top:8px">Token required for circuit data. See setup instructions above.</div>
  </div>
  <div class="circuit-grid" id="circuit-grid"></div>
</div><!-- /span -->


<!-- ═══ POOL CONTROL ═════════════════════════════════════════════════════════ -->
<div id="view-pool" class="view">

  <!-- Header -->
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
    <div style="font-size:13px;font-weight:600;color:var(--text-dim)">Pentair IntelliCenter · 192.168.68.89</div>
    <span class="badge" id="pc-pentair-badge">—</span>
  </div>

  <!-- 2-column main layout: Hot Tub hero | Pool / Pump / Heater / Lights -->
  <div class="pc-grid">

    <!-- LEFT — Hot Tub Hero Card -->
    <div class="pc-hero-card" id="pc-spa-hero">
      <div class="pc-section-lbl">HOT TUB</div>
      <div class="pc-hero-status status-off" id="pc-spa-status">OFF</div>
      <div class="pc-hero-temp" id="pc-spa-temp">—<sup>°F</sup></div>
      <div class="pc-hero-setpt" id="pc-spa-setpoint">Target: — °F</div>
      <div class="pc-hero-actions">
        <button class="pc-action-btn pc-btn-on"  onclick="pentairSet('C0001',{STATUS:'ON'})">SPA ON</button>
        <button class="pc-action-btn pc-btn-off" onclick="pentairSet('C0001',{STATUS:'OFF'})">SPA OFF</button>
      </div>
      <!-- Air Blower quick toggle -->
      <div style="margin-top:10px;display:flex;gap:8px;width:100%">
        <button class="btn" style="flex:1;font-size:11px" onclick="pentairSet('C0009',{STATUS:'ON'})">Blower ON</button>
        <button class="btn danger" style="flex:1;font-size:11px" onclick="pentairSet('C0009',{STATUS:'OFF'})">Blower OFF</button>
      </div>
    </div>

    <!-- RIGHT — status grid (2 cols) -->
    <div class="pc-right">

      <!-- Pool body -->
      <div class="pc-stat-card" id="pc-pool-card">
        <div class="pc-stat-hdr">
          <span class="pc-section-lbl">POOL</span>
          <span class="badge" id="pool-body-badge">—</span>
        </div>
        <div class="pc-stat-temp" id="pc-pool-temp">—°F</div>
        <div class="pc-stat-sub" id="pc-pool-setpoint">Setpoint: —</div>
        <div class="pc-stat-sub" id="pc-pool-heat" style="display:none">Heat: —</div>
        <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
          <button class="btn primary" onclick="pentairSet('C0006',{STATUS:'ON'})">Pool ON</button>
          <button class="btn danger"  onclick="pentairSet('C0006',{STATUS:'OFF'});setTimeout(()=>pentairSet('FTR01',{STATUS:'OFF'}),500)">Pool OFF</button>
          <button class="btn danger" style="background:#7f1d1d;font-size:10px;margin-top:4px;width:100%" onclick="pentairSet('C0006',{STATUS:'OFF'});setTimeout(()=>{pentairSet('FTR01',{STATUS:'OFF'})},500)">⏹ ALL OFF (Pool + Cleaner)</button>
        </div>
      </div>

      <!-- VSF Pump -->
      <div class="pc-stat-card" id="pc-pump-card">
        <div class="pc-stat-hdr">
          <span class="pc-section-lbl">VSF PUMP</span>
          <span class="badge" id="pc-pump-badge">—</span>
        </div>
        <div><span class="pc-pump-big" id="pc-pump-rpm">—</span><span class="pc-pump-unit"> RPM</span></div>
        <div class="pc-pump-row"><span id="pc-pump-gpm-val">—</span> GPM &nbsp;·&nbsp; <span id="pc-pump-w-val">—</span> W</div>
        <!-- hidden compat element for old JS refs -->
        <span id="pc-pump-status" style="display:none"></span>
        <span id="pc-pump-gpm"    style="display:none"></span>
      </div>

      <!-- Gas Heater -->
      <div class="pc-stat-card" id="pc-heater-card">
        <div class="pc-stat-hdr">
          <span class="pc-section-lbl">GAS HEATER</span>
          <span class="badge" id="pc-heater-badge">—</span>
        </div>
        <div class="pc-stat-sub" id="pc-heater-status">Spa heat: — · Pool heat: —</div>
        <div style="margin-top:6px;font-size:10px;opacity:0.6">Spa heat source:</div>
        <div style="margin-top:4px;display:flex;gap:6px">
          <button class="btn primary" style="flex:1;font-size:11px" onclick="pentairSet('B1202',{HTSRC:'H0001'})">Gas ON</button>
          <button class="btn danger"  style="flex:1;font-size:11px" onclick="pentairSet('B1202',{HTSRC:'00000'})">Gas OFF</button>
        </div>
      </div>

      <!-- Lights & Cleaner -->
      <div class="pc-stat-card">
        <div class="pc-section-lbl" style="margin-bottom:10px">LIGHTS &amp; CLEANER</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button class="btn" style="font-size:10px" onclick="pentairSet('GRP01',{STATUS:'ON'})">All ON</button>
          <button class="btn danger" style="font-size:10px" onclick="pentairSet('GRP01',{STATUS:'OFF'})">All OFF</button>
          <button class="btn" style="font-size:10px" onclick="pentairSet('C0003',{STATUS:'ON'})">Deep</button>
          <button class="btn" style="font-size:10px" onclick="pentairSet('C0004',{STATUS:'ON'})">Spa Lt</button>
          <button class="btn" style="font-size:10px" onclick="pentairSet('C0002',{STATUS:'ON'})">Shallow</button>
          <button class="btn" style="font-size:10px" onclick="pentairSet('C0008',{STATUS:'ON'})">Tree</button>
        </div>
        <div style="margin-top:8px;display:flex;gap:6px">
          <button class="btn primary" style="flex:1;font-size:10px" onclick="pentairSet('FTR01',{STATUS:'ON'})">Cleaner ON</button>
          <button class="btn danger"  style="flex:1;font-size:10px" onclick="pentairSet('FTR01',{STATUS:'OFF'})">Cleaner OFF</button>
        </div>
      </div>

    </div><!-- /pc-right -->
  </div><!-- /pc-grid -->

  <!-- Circuit Status tiles -->
  <div class="section-title" style="margin-top:18px">Circuit Status</div>
  <div class="pc-circ-grid" id="pool-circuits"></div>

</div><!-- /pool -->


<!-- ═══ DEVICES ══════════════════════════════════════════════════════════════ -->
<div id="view-devices" class="view" style="display:none">
  <div class="section-title">Connected Devices <span id="dev-online-count" style="font-size:10px;color:var(--online);font-weight:600;text-transform:none;letter-spacing:0;margin-left:4px"></span></div>

  <!-- Hidden compat spans for old renderState refs that use direct assignment -->
  <span id="dev-span-door"    style="display:none"></span>
  <span id="dev-enphase-prod" style="display:none"></span>
  <span id="tesla-gw-detail"  style="display:none"></span>
  <span id="wc-detail"        style="display:none"></span>
  <span id="wc-session"       style="display:none"></span>

  <div class="dev-grid">

    <!-- SPAN Panel -->
    <div class="dev-card status-offline" id="dc-span">
      <div class="dev-sdot offline" id="dc-span-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">⚡</span>
          <span class="dev-dname">SPAN Panel</span>
          <span class="badge offline" id="dev-span-badge">—</span>
        </div>
        <div class="dev-ip">192.168.68.93 · nj-2307-006gl</div>
        <div class="dev-metric" id="dc-span-metric">—<span> W grid</span></div>
        <div class="dev-lastseen" id="dc-span-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- Enphase IQ Gateway -->
    <div class="dev-card status-offline" id="dc-enphase">
      <div class="dev-sdot offline" id="dc-enphase-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">☀️</span>
          <span class="dev-dname">Enphase IQ Gateway</span>
          <span class="badge offline" id="dev-enphase-badge">—</span>
        </div>
        <div class="dev-ip">192.168.68.63 · S/N 202324023651</div>
        <div class="dev-metric" id="dc-enphase-metric">—<span> W solar</span></div>
        <div class="dev-lastseen" id="dc-enphase-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- Tesla Energy Gateway 3V -->
    <div class="dev-card status-offline" id="dc-tesla">
      <div class="dev-sdot offline" id="dc-tesla-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">🔋</span>
          <span class="dev-dname">Tesla Gateway 3V</span>
          <span class="badge offline" id="tesla-gw-badge">—</span>
        </div>
        <div class="dev-ip">192.168.68.86 · Fleet API OAuth</div>
        <div class="dev-metric" id="dc-tesla-metric">—<span>% SoE</span></div>
        <div class="dev-lastseen" id="dc-tesla-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- Tesla Wall Connector Gen 3 -->
    <div class="dev-card status-offline" id="dc-wc">
      <div class="dev-sdot offline" id="dc-wc-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">🔌</span>
          <span class="dev-dname">Wall Connector Gen 3</span>
          <span class="badge offline" id="wc-badge">—</span>
        </div>
        <div class="dev-ip">192.168.68.87 · no auth</div>
        <div class="dev-metric" id="dc-wc-metric">—</div>
        <div class="dev-lastseen" id="dc-wc-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- Pentair IntelliCenter -->
    <div class="dev-card status-offline" id="dc-pentair">
      <div class="dev-sdot offline" id="dc-pentair-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">🏊</span>
          <span class="dev-dname">Pentair IntelliCenter</span>
          <span class="badge offline" id="dev-pentair-badge">—</span>
        </div>
        <div class="dev-ip">192.168.68.89:6681 TCP</div>
        <div class="dev-metric" id="dc-pentair-metric">—</div>
        <div class="dev-lastseen" id="dc-pentair-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- Nest Thermostat -->
    <div class="dev-card status-offline" id="dc-nest">
      <div class="dev-sdot offline" id="dc-nest-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">🌡️</span>
          <span class="dev-dname">Nest Thermostat</span>
          <span class="badge offline" id="dev-nest-badge">—</span>
        </div>
        <div class="dev-ip">192.168.68.65 · Google SDM API</div>
        <div class="dev-metric" id="dc-nest-metric">—<span>°F</span></div>
        <div class="dev-lastseen" id="dc-nest-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- B-Hyve Sprinklers -->
    <div class="dev-card status-offline" id="dc-bhyve">
      <div class="dev-sdot offline" id="dc-bhyve-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">💧</span>
          <span class="dev-dname">B-Hyve Sprinklers</span>
          <span class="badge offline" id="dev-bhyve-badge">—</span>
        </div>
        <div class="dev-ip">cloud API · Orbit B-Hyve</div>
        <div class="dev-metric" id="dc-bhyve-metric">—<span> zones</span></div>
        <div class="dev-lastseen" id="dc-bhyve-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- MyQ Garage Door -->
    <div class="dev-card status-offline" id="dc-myq">
      <div class="dev-sdot offline" id="dc-myq-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">🚗</span>
          <span class="dev-dname">MyQ Garage</span>
          <span class="badge offline" id="dev-myq-badge">—</span>
        </div>
        <div class="dev-ip">cloud API · Chamberlain/LiftMaster</div>
        <div id="dc-myq-doors" style="margin-top:6px"></div>
        <div class="dev-lastseen" id="dc-myq-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- Wyze Cam — Front Side -->
    <div class="dev-card status-offline" id="dc-cam-front">
      <div class="dev-sdot offline" id="dc-cam-front-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">📷</span>
          <span class="dev-dname">Wyze — Front Side</span>
          <span class="badge offline" id="dc-cam-front-badge">—</span>
        </div>
        <div class="dev-ip">192.168.68.76 · RTSP :8554</div>
        <div class="dev-metric" id="dc-cam-front-metric">—</div>
        <div class="dev-lastseen" id="dc-cam-front-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- Wyze Cam — Upstairs -->
    <div class="dev-card status-offline" id="dc-cam-up">
      <div class="dev-sdot offline" id="dc-cam-up-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">📷</span>
          <span class="dev-dname">Wyze — Upstairs</span>
          <span class="badge offline" id="dc-cam-up-badge">—</span>
        </div>
        <div class="dev-ip">192.168.68.51 · Wyze Cloud</div>
        <div class="dev-metric" id="dc-cam-up-metric">—</div>
        <div class="dev-lastseen" id="dc-cam-up-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- Wyze Cam — Downstairs -->
    <div class="dev-card status-offline" id="dc-cam-down">
      <div class="dev-sdot offline" id="dc-cam-down-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">📷</span>
          <span class="dev-dname">Wyze — Downstairs</span>
          <span class="badge offline" id="dc-cam-down-badge">—</span>
        </div>
        <div class="dev-ip">192.168.68.82 · Wyze Cloud</div>
        <div class="dev-metric" id="dc-cam-down-metric">—</div>
        <div class="dev-lastseen" id="dc-cam-down-lastseen">last seen: —</div>
      </div>
    </div>

    <!-- GE SmartHQ Appliances -->
    <div class="dev-card status-offline" id="dc-ge">
      <div class="dev-sdot offline" id="dc-ge-dot"></div>
      <div class="dev-body">
        <div class="dev-header">
          <span class="dev-dicon">&#127968;</span>
          <span class="dev-dname">GE SmartHQ</span>
          <span class="badge offline" id="dev-ge-badge">&#x2014;</span>
        </div>
        <div class="dev-ip">cloud API &middot; SmartHQ OAuth2</div>
        <div class="dev-metric" id="dc-ge-metric">&#x2014;<span> appliances</span></div>
        <div class="dev-lastseen" id="dc-ge-lastseen">last seen: &#x2014;</div>
      </div>
    </div>

  </div>
</div><!-- /devices -->


<!-- ═══ TESLA ENERGY ════════════════════════════════════════════════════════ -->
<div id="view-tesla-energy" class="view">

  <!-- Header row -->
  <div class="row">
    <div class="card" style="flex:2;min-width:300px">
      <div class="card-header">
        <span class="card-title" style="font-size:13px;font-weight:700">⚡ Tesla Energy Gateway 3V</span>
        <span class="badge" id="tesla-energy-badge">—</span>
      </div>
      <div id="te-site-name" style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:4px">—</div>
      <div class="device-detail">192.168.68.86 · Serial: GF2240460002D2 · Firmware: 25.26.0</div>
      <div class="device-detail">Backup: Whole Home · Utility: SRP</div>
    </div>
    <div class="card" style="flex:1;min-width:180px">
      <div class="card-header"><span class="card-title">Grid State</span></div>
      <div style="display:flex;align-items:center;gap:10px;margin-top:4px">
        <div id="te-grid-state-dot" style="width:12px;height:12px;border-radius:50%;background:var(--offline);flex-shrink:0"></div>
        <span style="font-size:15px;font-weight:700" id="te-grid-state-text">—</span>
      </div>
      <div class="device-detail" style="margin-top:6px" id="te-grid-state-detail">Waiting for gateway…</div>
    </div>
  </div>

  <!-- Offline card — shown when Tesla Fleet API is not polling -->
  <div id="tesla-setup-card" class="card" style="border-color:var(--warning);margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">⚠️ Tesla Gateway 3V — Offline</span>
      <span class="badge warning">no data</span>
    </div>
    <div style="color:var(--text-dim);font-size:12px">
      Auth: Fleet API OAuth via <code>auth.tesla.com</code> · tokens auto-refresh every 8h.<br>
      If offline, check <code>jarvis-home-energy/tesla_cache.json</code> — refresh_token may have expired (re-run teslapy browser auth flow to re-authorize).
    </div>
  </div>

  <!-- Live gauges — shown only when online -->
  <div id="tesla-energy-tiles" style="display:none">
    <div class="section-title">Live Energy Flow</div>

    <!-- Gauge row: Battery SOC ring · Solar arc · Grid + Load -->
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px">

      <!-- Battery SOC ring -->
      <div class="card energy-battery" style="flex:1;min-width:210px;display:flex;flex-direction:column;align-items:center;padding:20px 16px">
        <div class="card-title" style="margin-bottom:10px;align-self:flex-start">Battery SOC</div>
        <svg viewBox="0 0 120 120" style="width:130px;height:130px">
          <circle cx="60" cy="60" r="50" fill="none" stroke="var(--surface2)" stroke-width="12"/>
          <circle id="te-soc-arc" cx="60" cy="60" r="50" fill="none" stroke="var(--battery)" stroke-width="12"
            stroke-dasharray="314" stroke-dashoffset="314"
            stroke-linecap="round" transform="rotate(-90 60 60)"
            style="transition:stroke-dashoffset .8s ease,stroke .4s"/>
          <text id="te-soc-text" x="60" y="56" text-anchor="middle" dominant-baseline="central"
            fill="#10b981" font-size="26" font-weight="700" font-family="monospace">—</text>
          <text x="60" y="76" text-anchor="middle" fill="#64748b" font-size="11" font-family="monospace">% SOC</text>
        </svg>
        <span id="te-soe" style="display:none"></span>
        <div class="sub-val" id="te-bat-w" style="margin-top:4px;font-size:13px">— W</div>
        <div class="sub-val" id="te-bat-dir" style="color:var(--battery);margin-top:2px">—</div>
        <div style="width:100%;margin-top:12px">
          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-dim);margin-bottom:4px">
            <span>Backup Reserve</span>
            <span id="te-reserve-pct" style="color:var(--grid);font-weight:600">—</span>
          </div>
          <div class="bar-bg"><div class="bar-fill" id="te-reserve-bar" style="width:0%;background:var(--grid)"></div></div>
        </div>
      </div>

      <!-- Solar arc gauge (half-circle, max 10 kW) -->
      <!-- viewBox 0 0 140 90; center=(70,80) r=56 → half-circle arc length≈176 -->
      <div class="card energy-solar" style="flex:1;min-width:210px;display:flex;flex-direction:column;align-items:center;padding:20px 16px">
        <div class="card-title" style="margin-bottom:10px;align-self:flex-start">Solar Production</div>
        <svg viewBox="0 0 140 90" style="width:150px;height:96px">
          <path d="M 14,80 A 56,56 0 0 1 126,80" fill="none" stroke="var(--surface2)" stroke-width="12" stroke-linecap="round"/>
          <path id="te-solar-arc" d="M 14,80 A 56,56 0 0 1 126,80" fill="none" stroke="var(--solar)" stroke-width="12"
            stroke-linecap="round" stroke-dasharray="176" stroke-dashoffset="176"
            style="transition:stroke-dashoffset .8s ease"/>
          <text id="te-solar-text" x="70" y="68" text-anchor="middle"
            fill="#f59e0b" font-size="22" font-weight="700" font-family="monospace">—</text>
          <text x="70" y="83" text-anchor="middle" fill="#64748b" font-size="10" font-family="monospace">WATTS</text>
        </svg>
        <div style="display:flex;align-items:baseline;gap:4px;margin-top:8px">
          <div class="big-val c-solar" id="te-solar" style="font-size:32px">—</div>
          <span class="big-unit" style="font-size:16px">W</span>
        </div>
        <div class="sub-val" style="margin-top:6px">max 10 kW</div>
      </div>

      <!-- Grid + Home Load -->
      <div class="card" style="flex:1;min-width:200px">
        <div class="card-header">
          <span class="card-title">Grid</span>
          <span class="badge" id="te-grid-badge">—</span>
        </div>
        <div class="big-val c-grid" id="te-grid">—</div><span class="big-unit">W</span>
        <div class="sub-val" id="te-grid-dir" style="margin-top:4px">—</div>
        <div style="height:1px;background:var(--border);margin:14px 0"></div>
        <div class="card-title" style="margin-bottom:8px">Home Load</div>
        <div class="big-val c-load" id="te-load">—</div><span class="big-unit">W</span>
        <div class="sub-val" style="margin-top:4px">Total consumption</div>
      </div>

    </div>
  </div>

  <!-- Current Tesla state raw display -->
  <div class="card">
    <div class="card-header"><span class="card-title">Current State</span></div>
    <div id="tesla-state-raw" style="font-size:11px;color:var(--text-dim);line-height:2.2">Waiting for data…</div>
  </div>

</div><!-- /tesla-energy -->


<!-- ═══ CYBERTRUCK ════════════════════════════════════════════════════════════ -->
<div id="view-cybertruck" class="view">

  <div class="row">
    <div class="card" style="flex:2;min-width:300px">
      <div class="card-header">
        <span class="card-title" style="font-size:14px;font-weight:700">🚚 Cybertruck</span>
        <span class="badge" id="ct-connection-badge">—</span>
      </div>
      <div class="device-detail">Wall Connector Gen 3 · 192.168.68.87 · No auth required</div>
    </div>
  </div>

  <div class="section-title">Wall Connector</div>
  <div class="row">
    <div class="card" style="flex:2;min-width:280px">
      <div class="card-header">
        <span class="card-title">Tesla Wall Connector Gen 3</span>
        <span class="badge" id="ct-wc-badge">—</span>
      </div>
      <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:16px">
        <div>
          <div class="sub-val">Charge Status</div>
          <div style="font-size:20px;font-weight:700" id="ct-charge-status">—</div>
        </div>
        <div>
          <div class="sub-val">Vehicle Connected</div>
          <div style="font-size:20px;font-weight:700" id="ct-vehicle">—</div>
        </div>
        <div>
          <div class="sub-val">Charging Rate</div>
          <div class="big-val" id="ct-rate-w" style="color:var(--battery)">—</div><span class="big-unit">W</span>
          <div class="sub-val" id="ct-rate-a">— A</div>
        </div>
        <div>
          <div class="sub-val">Session Energy</div>
          <div class="big-val" id="ct-session" style="color:var(--solar)">—</div><span class="big-unit">Wh</span>
        </div>
      </div>
      <div style="display:flex;gap:24px;flex-wrap:wrap">
        <div>
          <div class="sub-val">Grid Voltage</div>
          <div style="font-size:16px;font-weight:600" id="ct-grid-v">— V</div>
        </div>
        <div>
          <div class="sub-val">Board Temp</div>
          <div style="font-size:16px;font-weight:600" id="ct-temp">— °C</div>
        </div>
        <div>
          <div class="sub-val">Session Duration</div>
          <div style="font-size:16px;font-weight:600;font-variant-numeric:tabular-nums" id="ct-session-dur">—</div>
        </div>
      </div>
    </div>

    <div class="card" style="flex:1;min-width:200px">
      <div class="card-header"><span class="card-title">Device Details</span></div>
      <div class="device-detail">Model: Universal Wall Connector</div>
      <div class="device-detail">Max Amperage: 48A</div>
      <div class="device-detail">Serial: B7S24058J22706</div>
      <div class="device-detail">Firmware: 25.42.1</div>
      <div class="device-detail">IP: 192.168.68.87</div>
    </div>
  </div>



</div><!-- /cybertruck -->


<!-- ═══ CAMERAS ══════════════════════════════════════════════════════════════ -->
<div id="view-cameras" class="view" style="padding:4px 8px">
  <div class="section-title" style="margin-bottom:4px">Security Cameras</div>
  <div id="cameras-setup-card" class="card" style="border-color:var(--warning);display:none">
    <div class="card-header">
      <span class="card-title">📷 No cameras configured</span>
      <span class="badge warning">setup needed</span>
    </div>
    <div style="color:var(--text-dim);font-size:12px;margin-bottom:12px">
      Add your Wyze API key or Ring credentials in the <strong>Settings</strong> tab to connect cameras.
    </div>
    <button class="btn primary" onclick="showView('settings')">Go to Settings →</button>
  </div>
  <div id="camera-grid" class="grid grid-2" style="margin-bottom:4px;gap:4px"></div>
</div><!-- /cameras -->

<!-- ═══ ROKU TVs ══════════════════════════════════════════════════════════════ -->
<div id="view-roku" class="view">
  <div class="section-title">📺 Roku TVs</div>
  <div id="roku-grid" style="display:flex;gap:1rem;flex-wrap:wrap;padding:4px 0;"></div>
</div><!-- /roku -->

<!-- ── Camera Enlarge Modal ────────────────────────────────────────────── -->
<div id="cam-modal" onclick="if(event.target===this)closeCameraModal()">
  <button id="cam-modal-close" onclick="closeCameraModal()">✕</button>
  <img id="cam-modal-img" src="" alt="" style="display:none" onerror="this.style.display='none';document.getElementById('cam-modal-placeholder').style.display='flex'">
  <div id="cam-modal-placeholder" style="display:none">📷</div>
  <div id="cam-modal-info">
    <span id="cam-modal-title"></span>
    <span id="cam-modal-badge" class="badge"></span>
    <span id="cam-modal-meta"></span>
  </div>
</div>


<!-- ═══ HOME CONTROL ════════════════════════════════════════════════════════ -->
<div id="view-home-control" class="view">
  <div class="section-title">Controls</div>

  <!-- Nest Thermostats (dynamically rendered per device) -->
  <div class="card" style="margin-bottom:16px">
    <div class="card-header">
      <span class="card-title">🌡️ Nest Thermostats</span>
      <span class="badge" id="nest-badge">unconfigured</span>
    </div>
    <div id="nest-setup-msg" style="color:var(--text-dim);font-size:12px">
      Configure Nest in the <strong>Settings</strong> tab to connect.
      <br><br>
      <button class="btn primary" onclick="showView('settings')">Go to Settings →</button>
    </div>
    <div id="nest-cards-container" style="display:none;display:flex;gap:16px;flex-wrap:wrap"></div>
  </div>
</div><!-- /home-control -->


<!-- ═══ SPRINKLERS ══════════════════════════════════════════════════════════ -->
<div id="view-sprinklers" class="view">
  <div class="section-title">B-Hyve Sprinkler System</div>

  <!-- Header card with status -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">💧 Orbit B-Hyve — Cloud Integration</span>
      <span class="badge unconfigured" id="bhyve-badge">unconfigured</span>
    </div>
    <div id="bhyve-setup-card" style="display:block">
      <div style="color:var(--text-dim);font-size:12px;margin-bottom:10px">
        B-Hyve uses cloud-only authentication. Configure your Orbit/B-Hyve account credentials in
        <a href="#" onclick="showView('settings');return false" style="color:var(--solar)">Settings → B-Hyve</a>.
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;max-width:480px;margin-bottom:10px">
        <div>
          <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Email</div>
          <input type="email" id="bhyve-quick-email" placeholder="orbit@email.com"
            style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
        </div>
        <div>
          <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Password</div>
          <input type="password" id="bhyve-quick-password" placeholder="B-Hyve password"
            style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
        </div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <button class="btn primary" onclick="saveBhyveQuick()">Connect B-Hyve</button>
        <span id="bhyve-quick-status" style="font-size:11px;color:var(--text-dim)"></span>
      </div>
    </div>
    <div id="bhyve-device-info" style="display:none">
      <div id="bhyve-devices-list"></div>
    </div>
  </div>

  <!-- Zone grid (shown when online) -->
  <div id="bhyve-zones-section" style="display:none">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <div class="section-title" style="margin-bottom:0">Zones</div>
      <button class="btn primary" onclick="bhyveRunAll()" id="bhyve-run-all-btn" style="font-size:11px">▶ Run All Zones</button>
    </div>
    <div class="zone-grid" id="bhyve-zone-grid"></div>
  </div>
</div>

<!-- ── B-Hyve Run Modal ──────────────────────────────────────────────────── -->
<div id="bhyve-modal">
  <div class="modal-box">
    <div class="modal-title" id="bhyve-modal-title">Run Zone</div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:12px">Select duration:</div>
    <div class="modal-dur-btns">
      <button class="dur-btn" onclick="selectDur(this,5)">5 min</button>
      <button class="dur-btn selected" onclick="selectDur(this,10)">10 min</button>
      <button class="dur-btn" onclick="selectDur(this,15)">15 min</button>
      <button class="dur-btn" onclick="selectDur(this,20)">20 min</button>
      <button class="dur-btn" onclick="selectDur(this,30)">30 min</button>
    </div>
    <div class="modal-actions">
      <button class="btn" onclick="closeBhyveModal()">Cancel</button>
      <button class="btn-run" onclick="confirmBhyveRun()">▶ Start</button>
    </div>
  </div>
</div>

<!-- ═══ APPLIANCES ═══════════════════════════════════════════════════════════ -->
<div id="view-appliances" class="view">
  <div class="section-title">GE SmartHQ Appliances
    <span id="ge-online-count" style="font-size:10px;color:var(--online);font-weight:600;text-transform:none;letter-spacing:0"></span>
    <button id="ge-refresh-btn" onclick="geForceRefresh()" title="Force immediate re-poll" style="margin-left:4px;padding:2px 9px;background:var(--surface2);border:1px solid var(--border);border-radius:5px;color:var(--text-dim);font-size:11px;cursor:pointer;font-family:inherit">&#8635; Refresh</button>
  </div>

  <!-- Summary strip — visible when configured & online -->
  <div id="ge-summary-strip" style="display:none;margin-bottom:14px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;overflow:hidden">
    <div style="display:flex;flex-wrap:wrap">
      <div style="display:flex;align-items:center;gap:10px;padding:12px 20px;border-right:1px solid var(--border)">
        <span style="font-size:26px;font-weight:800;color:var(--text);line-height:1" id="ge-sum-total">0</span>
        <span style="font-size:11px;color:var(--text-dim);line-height:1.3">appliances<br>on account</span>
      </div>
      <div style="display:flex;align-items:center;gap:10px;padding:12px 20px;border-right:1px solid var(--border)">
        <span class="dev-sdot online" style="flex-shrink:0;animation:ge-dot-pulse 1.5s ease-in-out infinite"></span>
        <span style="font-size:26px;font-weight:800;color:var(--online);line-height:1" id="ge-sum-running">0</span>
        <span style="font-size:11px;color:var(--text-dim);line-height:1.3">currently<br>running</span>
      </div>
      <div style="display:flex;align-items:center;gap:10px;padding:12px 20px;border-right:1px solid var(--border)">
        <span style="font-size:14px;color:#f59e0b">&#9889;</span>
        <span style="font-size:22px;font-weight:800;color:#f59e0b;line-height:1" id="ge-sum-watts">0 W</span>
        <span style="font-size:11px;color:var(--text-dim);line-height:1.3">estimated<br>draw</span>
      </div>
      <div style="display:flex;align-items:center;gap:10px;padding:12px 20px;border-right:1px solid var(--border)">
        <span style="font-size:14px">&#128260;</span>
        <span style="font-size:22px;font-weight:800;color:#a78bfa;line-height:1" id="ge-sum-cycles">0</span>
        <span style="font-size:11px;color:var(--text-dim);line-height:1.3">cycles<br>today</span>
      </div>
      <div style="display:flex;align-items:center;padding:12px 20px;margin-left:auto">
        <span style="font-size:11px;color:var(--text-dim)" id="ge-sum-lastseen"></span>
      </div>
    </div>
  </div>

  <!-- Status / setup card -->
  <div class="card" style="margin-bottom:14px" id="ge-header-card">
    <div class="card-header">
      <span class="card-title">&#127968; GE SmartHQ &mdash; Cloud Integration</span>
      <span class="badge unconfigured" id="ge-badge">unconfigured</span>
    </div>
    <div id="ge-unconfigured-msg" style="display:none;color:var(--text-dim);font-size:12px;padding:8px 0">
      GE SmartHQ is not configured. Add <code>GE_CLIENT_ID</code>, <code>GE_CLIENT_SECRET</code>,
      and <code>GE_REFRESH_TOKEN</code> to <code>config.py</code> to enable live appliance status.
      Complete the OAuth2 Authorization Code flow at <strong>developers.smarthq.com</strong>
      to obtain a refresh token.
    </div>
    <div id="ge-error-msg" style="display:none;color:var(--error);font-size:12px;padding:8px 0">
      &#9888; Unable to reach the GE SmartHQ API. Check credentials and network connectivity.
    </div>
    <div id="ge-status-line" style="display:none;font-size:12px;color:var(--text-dim)">
      Polling every 60 s &nbsp;&middot;&nbsp; OAuth2 refresh token (Authorization Code flow) &nbsp;&middot;&nbsp; api.brillion.geappliances.com
    </div>
  </div>

  <!-- Appliance card grid — populated by renderAppliances() -->
  <div id="ge-appliance-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px"></div>

</div><!-- /appliances -->


<!-- ═══ RING DOORBELL ════════════════════════════════════════════════════════ -->
<div id="view-ring" class="view" style="display:none;padding:0">
  <iframe src="/ring" style="width:100%;border:none;display:block"></iframe>
</div>


<!-- ═══ SETTINGS ════════════════════════════════════════════════════════════ -->
<div id="view-settings" class="view">
  <div class="section-title">🔧 Devices &amp; Settings</div>
  <p style="color:var(--text-dim);font-size:12px;margin-bottom:16px">All connected devices. Green = live data. Edit IPs or credentials inline.</p>

  <!-- SPAN Panel -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">⚡ SPAN Panel</span>
      <span class="badge offline" id="cfg-badge-span">checking...</span>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
      <span style="font-size:11px;color:var(--text-dim)">IP:</span>
      <code style="font-size:11px" id="cfg-ip-span">192.168.68.93</code>
      <button onclick="editDeviceIp('span')" style="font-size:10px;padding:2px 7px;border-radius:4px;border:1px solid #444;background:transparent;color:#aaa;cursor:pointer;">Edit</button>
    </div>
    <div id="cfg-edit-span" style="display:none;margin-bottom:8px;gap:8px;align-items:center">
      <input type="text" id="cfg-ip-input-span" placeholder="192.168.68.x" style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:12px;width:200px;outline:none">
      <button onclick="saveDeviceIp('span')" class="btn primary" style="font-size:11px;padding:5px 12px">Save</button>
      <button onclick="cancelDeviceIp('span')" class="btn" style="font-size:11px;padding:5px 12px">Cancel</button>
      <span id="cfg-ip-status-span" style="font-size:11px;color:var(--text-dim)"></span>
    </div>
    <div id="cfg-stats-span" style="font-size:11px;color:var(--text-dim)">—</div>
  </div>

  <!-- Enphase Solar -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">☀️ Enphase IQ Gateway</span>
      <span class="badge offline" id="cfg-badge-enphase">checking...</span>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">192.168.68.63 · S/N 202324023651 · local API (no token needed)</div>
    <div id="cfg-stats-enphase" style="font-size:11px;color:var(--text-dim)">—</div>
  </div>

  <!-- SolarEdge Solar -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">☀️ SolarEdge SE5000H</span>
      <span class="badge offline" id="cfg-badge-solaredge">checking...</span>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">Derived from SPAN circuits (SPAN net − Enphase)</div>
    <div id="cfg-stats-solaredge" style="font-size:11px;color:var(--text-dim)">—</div>
  </div>

  <!-- Tesla Energy Gateway -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">🔋 Tesla Energy Gateway 3V</span>
      <span class="badge" id="settings-tesla-badge">—</span>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">
      192.168.68.86 · Serial: GF2240460002D2 · FW: 25.26.0 · Fleet API OAuth<br>
      Token cached in <code>tesla_cache.json</code>, auto-refreshes every 8h.<br>
      To re-authorize: run teslapy browser flow → approve callback → token auto-saved.
    </div>
    <div id="cfg-stats-tesla" style="font-size:11px;color:var(--text-dim)">—</div>
  </div>

  <!-- Tesla Wall Connector -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">🔌 Tesla Wall Connector Gen 3</span>
      <span class="badge offline" id="cfg-badge-wallconnector">checking...</span>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">192.168.68.87 · No auth required · local API port 443</div>
    <div id="cfg-stats-wallconnector" style="font-size:11px;color:var(--text-dim)">—</div>
  </div>

  <!-- Pentair Pool -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">🏊 Pentair IntelliCenter</span>
      <span class="badge offline" id="cfg-badge-pentair">checking...</span>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
      <span style="font-size:11px;color:var(--text-dim)">IP:</span>
      <code style="font-size:11px" id="cfg-ip-pentair">192.168.68.89</code>
      <button onclick="editDeviceIp('pentair')" style="font-size:10px;padding:2px 7px;border-radius:4px;border:1px solid #444;background:transparent;color:#aaa;cursor:pointer;">Edit</button>
      <span style="font-size:11px;color:var(--text-dim)">Port: 6681 TCP</span>
    </div>
    <div id="cfg-edit-pentair" style="display:none;margin-bottom:8px;gap:8px;align-items:center">
      <input type="text" id="cfg-ip-input-pentair" placeholder="192.168.68.x" style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:12px;width:200px;outline:none">
      <button onclick="saveDeviceIp('pentair')" class="btn primary" style="font-size:11px;padding:5px 12px">Save</button>
      <button onclick="cancelDeviceIp('pentair')" class="btn" style="font-size:11px;padding:5px 12px">Cancel</button>
      <span id="cfg-ip-status-pentair" style="font-size:11px;color:var(--text-dim)"></span>
    </div>
    <div id="cfg-stats-pentair" style="font-size:11px;color:var(--text-dim)">—</div>
  </div>

  <!-- Nest Thermostats -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">🌡️ Nest Thermostats</span>
      <span class="badge" id="nest-cfg-badge">unconfigured</span>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">192.168.68.65 · Google Smart Device Management API</div>
    <div id="cfg-stats-nest" style="font-size:11px;color:var(--text-dim)">—</div>
    <details id="cfg-creds-nest" style="margin-top:8px">
      <summary style="font-size:11px;color:var(--text-dim);cursor:pointer;list-style:none">⚙️ Credentials &amp; Setup</summary>
      <div style="margin-top:8px">
        <div style="color:var(--text-dim);font-size:11px;margin-bottom:8px">
          Provide a Nest access token from the Google Smart Device Management API or the legacy nest_thermostat auth flow.
        </div>
        <div style="margin-bottom:8px">
          <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Access Token</div>
          <input type="password" id="nest-token-input" placeholder="ya29.a0… or legacy token"
            style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <button class="btn primary" onclick="saveNest()">Save Nest Token</button>
          <span id="nest-save-status" style="font-size:11px;color:var(--text-dim)"></span>
        </div>
      </div>
    </details>
  </div>

  <!-- Wyze Cameras -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">📷 Wyze Cameras</span>
      <span class="badge" id="wyze-cfg-badge">unconfigured</span>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">Front Side 192.168.68.76 · Upstairs 192.168.68.51 · Downstairs 192.168.68.82</div>
    <div id="cfg-stats-wyze" style="font-size:11px;color:var(--text-dim)">—</div>
    <details id="cfg-creds-wyze" style="margin-top:8px">
      <summary style="font-size:11px;color:var(--text-dim);cursor:pointer;list-style:none">⚙️ Credentials &amp; Setup</summary>
      <div style="margin-top:8px">
        <div style="color:var(--text-dim);font-size:11px;margin-bottom:8px">
          Get your API Key and Key ID from <a href="https://developer.wyze.com" target="_blank" style="color:var(--solar)">developer.wyze.com</a>.
          API key auth is preferred over username/password.
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
          <div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">API Key (preferred)</div>
            <input type="password" id="wyze-api-key" placeholder="wyze_api_key_…"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
          <div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Key ID</div>
            <input type="password" id="wyze-key-id" placeholder="key_id_…"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
          <div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Email <span style="color:var(--error)">*required</span></div>
            <input type="email" id="wyze-email" placeholder="you@example.com"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
          <div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Password <span style="color:var(--error)">*required</span></div>
            <input type="password" id="wyze-password" placeholder="password"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <button class="btn primary" onclick="saveWyze()">Save Wyze Credentials</button>
          <span id="wyze-save-status" style="font-size:11px;color:var(--text-dim)"></span>
        </div>
      </div>
    </details>
  </div>

  <!-- Ring Doorbell -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">🔔 Ring Doorbell</span>
      <span class="badge" id="ring-cfg-badge">unconfigured</span>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">Cloud API · Ring account credentials</div>
    <div id="cfg-stats-ring" style="font-size:11px;color:var(--text-dim)">—</div>
    <details id="cfg-creds-ring" style="margin-top:8px">
      <summary style="font-size:11px;color:var(--text-dim);cursor:pointer;list-style:none">⚙️ Credentials &amp; Setup</summary>
      <div style="margin-top:8px">
        <div style="color:var(--text-dim);font-size:11px;margin-bottom:8px">
          Enter your Ring account credentials. MFA is not supported — disable it if active.
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
          <div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Email</div>
            <input type="email" id="ring-email" placeholder="you@example.com"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
          <div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Password</div>
            <input type="password" id="ring-password" placeholder="Ring account password"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <button class="btn primary" onclick="saveRing()">Save Ring Credentials</button>
          <span id="ring-save-status" style="font-size:11px;color:var(--text-dim)"></span>
        </div>
      </div>
    </details>
  </div>

  <!-- B-Hyve Sprinklers -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">💧 B-Hyve Sprinklers</span>
      <span class="badge" id="bhyve-cfg-badge">unconfigured</span>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">Cloud API · api.orbitbhyve.com · Device: 192.168.68.66 (cloud-only)</div>
    <div id="cfg-stats-bhyve" style="font-size:11px;color:var(--text-dim)">—</div>
    <details id="cfg-creds-bhyve" style="margin-top:8px">
      <summary style="font-size:11px;color:var(--text-dim);cursor:pointer;list-style:none">⚙️ Credentials &amp; Setup</summary>
      <div style="margin-top:8px">
        <div style="color:var(--text-dim);font-size:11px;margin-bottom:8px">
          Orbit B-Hyve cloud account credentials.
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
          <div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Email</div>
            <input type="email" id="bhyve-email" placeholder="orbit@email.com"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
          <div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Password</div>
            <input type="password" id="bhyve-password" placeholder="B-Hyve account password"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <button class="btn primary" onclick="saveBhyve()">Save B-Hyve Credentials</button>
          <span id="bhyve-save-status" style="font-size:11px;color:var(--text-dim)"></span>
        </div>
      </div>
    </details>
  </div>

  <!-- GE SmartHQ Appliances -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">&#127968; GE SmartHQ Appliances</span>
      <span class="badge" id="ge-cfg-badge">unconfigured</span>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">Cloud API · api.brillion.geappliances.com · OAuth2</div>
    <div id="cfg-stats-ge" style="font-size:11px;color:var(--text-dim)">—</div>
    <details id="cfg-creds-ge" style="margin-top:8px">
      <summary style="font-size:11px;color:var(--text-dim);cursor:pointer;list-style:none">⚙️ Credentials &amp; Setup</summary>
      <div style="margin-top:8px">
        <div style="color:var(--text-dim);font-size:11px;margin-bottom:8px">
          Uses OAuth2 Authorization Code flow. Complete auth at <strong>developers.smarthq.com</strong>
          to obtain a refresh token, then save it here or directly in <code>config.py</code>.<br>
          Keys: <code>GE_CLIENT_ID</code>, <code>GE_CLIENT_SECRET</code>, <code>GE_REFRESH_TOKEN</code>.
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
          <div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Client ID</div>
            <input type="text" id="ge-client-id" placeholder="GE SmartHQ client_id"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
          <div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Client Secret</div>
            <input type="password" id="ge-client-secret" placeholder="GE SmartHQ client_secret"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
          <div style="grid-column:1/-1">
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Refresh Token</div>
            <input type="password" id="ge-refresh-token" placeholder="refresh_token from OAuth2 Authorization Code flow"
              style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <button class="btn primary" onclick="saveGE()">Save GE SmartHQ Credentials</button>
          <span id="ge-save-status" style="font-size:11px;color:var(--text-dim)"></span>
        </div>
      </div>
    </details>
  </div>

  <!-- Roku TVs -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">📺 Roku TVs</span>
      <span class="badge offline" id="cfg-badge-roku">checking...</span>
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">Auto-discovered via SSDP on local network</div>
    <div id="cfg-stats-roku" style="font-size:11px;color:var(--text-dim)">—</div>
  </div>

</div><!-- /settings -->


</main>
<div id="toast"></div>

<!-- ─── Ring Doorbell Popup Overlay ────────────────────────────────────────── -->
<div id="ring-popup" style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.88);backdrop-filter:blur(8px);flex-direction:column;align-items:center;justify-content:center;gap:20px;padding:24px">
  <div style="font-size:4rem">&#128276;</div>
  <div style="color:#FFD700;font-size:2rem;font-weight:900;letter-spacing:1px;text-align:center">Someone at the Door</div>
  <div style="color:rgba(255,255,255,0.65);font-size:1rem" id="ring-popup-time">&#8212;</div>
  <div style="color:rgba(255,255,255,0.45);font-size:0.9rem" id="ring-popup-device">Front Door</div>
  <div style="display:flex;gap:16px;margin-top:4px;flex-wrap:wrap;justify-content:center">
    <button onclick="dismissDoorbellPopup();showView('ring');setTimeout(()=>{const f=document.getElementById('streamFrame');const a=document.getElementById('streamArea');if(f&&a&&!a.classList.contains('show')){f.src='http://'+window.location.hostname+':8558/stream.html?src=9884e3d2f0af_live&ts='+Date.now();a.classList.add('show');}},400)"
      style="padding:18px 40px;font-size:1.3rem;font-weight:800;background:#22c55e;color:#000;border:none;border-radius:12px;cursor:pointer;min-height:64px;touch-action:manipulation;letter-spacing:0.5px">
      ▶ View Live
    </button>
    <button id="ring-dismiss-btn" onclick="dismissDoorbellPopup()"
      style="padding:18px 40px;font-size:1.3rem;font-weight:800;background:#FFD700;color:#000;border:none;border-radius:12px;cursor:pointer;min-height:64px;touch-action:manipulation;letter-spacing:1px">
      DISMISS
    </button>
  </div>
  <div style="color:rgba(255,255,255,0.3);font-size:0.8rem;margin-top:4px" id="ring-popup-countdown">Auto-dismiss in 60s</div>
</div>

<script>
const views = ['energy','climate','pool','cameras','appliances','settings','devices','cockpit','solar','span','tesla-energy','cybertruck','home-control','sprinklers','roku','ring'];
const _energySubs = ['cockpit','solar','span','tesla-energy','cybertruck'];
const _climateSubs = ['home-control'];
let _curEnergySub = 'cockpit';
let _curClimateSub = 'home-control';

function showEnergySub(name) {
  _curEnergySub = name;
  _energySubs.forEach(s => {
    const el = document.getElementById('view-'+s);
    if (el) el.style.display = (s === name) ? 'block' : 'none';
  });
  // cockpit uses flex layout
  const ckEl = document.getElementById('view-cockpit');
  if (name === 'cockpit' && ckEl) ckEl.style.display = 'flex';
  // Update sub-rail active state (only non-ck-* buttons; ck-* are managed by navCockpit)
  document.querySelectorAll('#sr-energy .sub-rail-btn').forEach(btn => {
    if (!btn.dataset.sub.startsWith('ck-')) {
      btn.classList.toggle('active', btn.dataset.sub === name);
    } else {
      btn.classList.remove('active');
    }
  });
}

// Navigate directly to a cockpit sub-page from the Energy sub-rail
function navCockpit(sub) {
  showEnergySub('cockpit');
  setCockpitSub(sub);
  // Mark the matching ck-* button active (showEnergySub cleared them all)
  document.querySelectorAll('#sr-energy .sub-rail-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.sub === 'ck-' + sub);
  });
}

function showClimateSub(name) {
  _curClimateSub = name;
  _climateSubs.forEach(s => {
    const el = document.getElementById('view-'+s);
    if (el) el.style.display = (s === name) ? 'block' : 'none';
  });
  // Update sub-rail active state
  document.querySelectorAll('#sr-climate .sub-rail-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.sub === name);
  });
}

function showEntertainmentSub(name) {
  const el = document.getElementById('view-roku');
  if (el) el.style.display = 'block';
  // Update sub-rail active state
  document.querySelectorAll('#sr-entertainment .sub-rail-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.sub === name);
  });
}

function showView(v) {
  // Determine which left-rail section this view belongs to
  const _energyViews = ['energy','cockpit','solar','span','tesla-energy','cybertruck'];
  const _climateViews = ['climate','thermostat','home-control'];
  let railSection = v;
  if (_energyViews.includes(v)) railSection = 'energy';
  else if (_climateViews.includes(v)) railSection = 'climate';
  else if (v === 'sprinklers') railSection = 'sprinklers'; // own rail item
  // roku is its own rail item — railSection stays 'roku'

  // Show/hide sub-rail and toggle body class
  const hasSubnav = ['energy'].includes(railSection);
  document.body.classList.toggle('has-subnav', hasSubnav);
  const srEl = document.getElementById('sub-rail');
  if (srEl) srEl.classList.toggle('visible', hasSubnav);
  ['energy','climate'].forEach(s => {
    const el = document.getElementById('sr-'+s);
    if (el) el.style.display = (s === railSection && hasSubnav) ? 'flex' : 'none';
  });

  // Update left rail active state
  document.querySelectorAll('#left-rail .rail-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.rail === railSection);
  });

  // Hide all top-level views and sub-views
  views.forEach(id => { const el = document.getElementById('view-'+id); if(el) el.style.display='none'; });
  _energySubs.forEach(s => { const el = document.getElementById('view-'+s); if(el) el.style.display='none'; });
  _climateSubs.forEach(s => { const el = document.getElementById('view-'+s); if(el) el.style.display='none'; });
  const rokuEl = document.getElementById('view-roku');
  if (rokuEl) rokuEl.style.display = 'none';

  // Show requested view
  const target = document.getElementById('view-'+v);
  if (target) target.style.display = 'block';

  // Handle grouped views — delegate to sub-show functions which also update sub-rail highlights
  if (_energyViews.includes(v)) {
    if (v === 'energy') showEnergySub(_curEnergySub);
    else showEnergySub(v);  // direct energy sub-view (solar, span, cybertruck, etc.)
  } else if (_climateViews.includes(v)) {
    showClimateSub('home-control');  // climate, thermostat, home-control all → thermostat
  } else if (v === 'roku') {
    if (rokuEl) rokuEl.style.display = 'block';
    // Use already-loaded SSE state — no separate fetch
    const _rk = (window._lastState||{}).roku || window._lastRoku || [];
    if (_rk.length) try { renderRoku(_rk); } catch(e) {}
  }

  // Refit heights whenever view changes
  setTimeout(fitCockpit, 50);
}

function fmt(w, unit='W') {
  if (w === null || w === undefined || isNaN(w)) return '—';
  const abs = Math.abs(w);
  if (abs >= 1000) return (w/1000).toFixed(2) + 'k' + unit;
  return Math.round(w) + ' ' + unit;
}

function updateFlowDiagram(s) {
  const sum  = s.summary  || {};
  const wc   = s.wall_connector || {};
  const span = s.span || {};
  const td   = s.tesla || {};

  const enphaseW    = sum.enphase_solar_w || 0;       // Solar 1 — Enphase IQ8 (API)
  const solarEdgeW  = sum.solaredge_solar_w || 0;    // Solar 2 — SolarEdge SE5000H (SPAN − Enphase)
  const spanSolarW  = sum.span_solar_w || 0;         // SPAN raw positive circuits (both systems)
  const solarW      = sum.solar_w || (enphaseW + solarEdgeW); // total for path animations
  const srpGridW    = sum.srp_grid_w != null ? sum.srp_grid_w : (sum.grid_w || 0); // true SRP total (signed)
  const spanGridW   = sum.span_grid_w != null ? sum.span_grid_w : srpGridW;         // SPAN-only grid (signed)
  const rawGrid     = srpGridW;          // signed: + importing, - exporting
  const gridW       = Math.abs(srpGridW);
  const spanGridAbs = Math.abs(spanGridW);
  const spanW       = sum.load_w || span.total_load_w || 0;  // pure SPAN circuit consumption
  const ctW         = sum.ct_charging_w || wc.charging_w || 0;
  const ctV2H       = sum.ct_v2h || false;
  const ctV2HW      = sum.ct_v2h_w || 0;
  const circuits    = (span.circuits || []);
  const poolCircuit = circuits.find(c => (c.name || '').includes('Pool'));
  const poolW       = poolCircuit ? Math.abs(poolCircuit.power_w || 0) : 0;
  const totalW      = spanW + ctW;
  const teslaOnline = td.status === 'online';
  const batW        = td.battery_w || 0;  // + discharging, - charging

  const setLbl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

  // Labels — two separate solar systems
  // lbl-solar  = Enphase IQ8 (Solar 1) on node-solar
  // lbl-solar2 = SolarEdge SE5000H (Solar 2) on node-solar2
  setLbl('lbl-solar', fmt(enphaseW));
  setLbl('lbl-solar2', fmt(solarEdgeW));
  setLbl('lbl-grid',  fmt(gridW) + (rawGrid >= 0 ? ' \u2193' : ' \u2191'));
  // Breakdown subtitle on SRP Grid node: home load + CT when bridge mode + CT charging
  const gridSubEl = document.getElementById('lbl-grid-sub');
  if (gridSubEl) {
    if (!teslaOnline && ctW > 50) {
      gridSubEl.textContent = '(home ' + fmt(spanGridAbs) + ' + CT ' + fmt(ctW) + ')';
      gridSubEl.setAttribute('visibility', 'visible');
    } else {
      gridSubEl.setAttribute('visibility', 'hidden');
    }
  }
  setLbl('lbl-home',  fmt(spanW));  // pure SPAN circuit consumption
  // CT label: show V2H mode if active, otherwise charging status
  if (ctV2H) {
    setLbl('lbl-ct', fmt(ctV2HW) + ' V2H');
    const ctEl = document.getElementById('lbl-ct');
    if (ctEl) ctEl.style.fill = '#a78bfa';  // purple for V2H
  } else {
    setLbl('lbl-ct', ctW > 50 ? fmt(ctW) + ' chg' : 'idle');
    const ctEl = document.getElementById('lbl-ct');
    if (ctEl) ctEl.style.fill = '';  // reset color
  }
  setLbl('lbl-pool',  poolW > 30 ? fmt(poolW) : 'off');
  if (teslaOnline) {
    // No battery in this setup — Gateway 3V is just the meter/gateway
    const stormMode = td.storm_mode_active;
    setLbl('lbl-gw',    stormMode ? 'storm mode' : 'on-grid');
    setLbl('lbl-gw-soe', stormMode ? 'Storm Mode ON' : 'Gateway 3V');
  } else {
    setLbl('lbl-gw',    'offline');
    setLbl('lbl-gw-soe', '\u2014');
  }
  const totalLbl = document.getElementById('flow-total-label');
  if (totalLbl) totalLbl.textContent = 'Total load: ' + fmt(totalW) + (ctW > 50 ? ' (incl. ' + fmt(ctW) + ' EV)' : '');

  // Bridge mode: switch between Gateway route and direct Grid→SPAN
  const elGridGw    = document.getElementById('path-grid-gw');
  const elGwSpan    = document.getElementById('path-gw-span');
  const elGwCt      = document.getElementById('path-gw-ct');    // Gateway → CT (Tesla online)
  const elGridSpan  = document.getElementById('path-grid-span');
  const elGridCt    = document.getElementById('path-grid-ct');  // Direct Grid → CT (bridge fallback)
  const elBridgeLbl = document.getElementById('pf-bridge-label');
  const elSrcLbl    = document.getElementById('pf-source-label');
  if (teslaOnline) {
    // SRP → Gateway → SPAN always visible; Gateway → CT visible only when charging
    if (elGridGw)    elGridGw.setAttribute('opacity', '0.9');
    if (elGwSpan)    elGwSpan.setAttribute('opacity', '0.9');
    if (elGwCt)      elGwCt.setAttribute('opacity', ctW > 50 ? '0.88' : '0.25');
    // Hide bridge-mode paths
    if (elGridSpan)  elGridSpan.setAttribute('opacity', '0');
    if (elGridCt)  { elGridCt.setAttribute('opacity', '0'); elGridCt.style.animation = 'none'; }
    if (elBridgeLbl) elBridgeLbl.setAttribute('visibility', 'hidden');
    if (elSrcLbl)    elSrcLbl.setAttribute('visibility', 'visible');
  } else {
    // Bridge mode: Gateway offline, grid connects directly to SPAN and CT
    if (elGridGw)    elGridGw.setAttribute('opacity', '0.1');
    if (elGwSpan)    elGwSpan.setAttribute('opacity', '0.1');
    if (elGwCt)      elGwCt.setAttribute('opacity', '0');
    if (elGridSpan)  elGridSpan.setAttribute('opacity', '0.88');
    if (elBridgeLbl) elBridgeLbl.setAttribute('visibility', 'visible');
    if (elSrcLbl)    elSrcLbl.setAttribute('visibility', 'hidden');
    // Animate bridge home path speed via inline style (SPAN-only grid, not total SRP)
    if (elGridSpan) {
      const dur = spanGridAbs > 3000 ? '0.75s' : spanGridAbs > 500 ? '1.4s' : '2.8s';
      elGridSpan.style.animation = spanGridAbs > 30 ? ('flowDash ' + dur + ' linear infinite') : 'none';
    }
    // Grid → CT direct path (bridge mode: CT on dedicated circuit separate from SPAN)
    if (elGridCt) {
      if (ctW > 30 && !ctV2H) {
        elGridCt.setAttribute('opacity', '0.88');
        const ctDur = ctW > 3000 ? '0.75s' : ctW > 500 ? '1.4s' : '2.8s';
        elGridCt.style.animation = 'flowDash ' + ctDur + ' linear infinite';
      } else {
        elGridCt.setAttribute('opacity', '0');
        elGridCt.style.animation = 'none';
      }
    }
  }

  // Particle groups: show/hide + adjust speed
  function setParticle(groupId, watts, maxW) {
    const g = document.getElementById(groupId);
    if (!g) return;
    if (watts < 30) { g.setAttribute('visibility', 'hidden'); return; }
    g.setAttribute('visibility', 'visible');
    const dur = watts > 3000 ? '0.75s' : watts > 500 ? '1.4s' : '2.8s';
    g.querySelectorAll('animateMotion').forEach(a => a.setAttribute('dur', dur));
  }

  setParticle('part-solar-span',  enphaseW,   6000);  // Enphase → Home
  setParticle('part-solar2-span', solarEdgeW, 6000);  // SolarEdge → Home
  if (teslaOnline) {
    setParticle('part-grid-gw',  gridW, 15000);
    setParticle('part-gw-span',  spanW, 15000);
    const pg   = document.getElementById('part-grid-span');
    const pgct = document.getElementById('part-grid-ct');
    if (pg)   pg.setAttribute('visibility', 'hidden');
    if (pgct) pgct.setAttribute('visibility', 'hidden');
  } else {
    const p1 = document.getElementById('part-grid-gw');
    const p2 = document.getElementById('part-gw-span');
    if (p1) p1.setAttribute('visibility', 'hidden');
    if (p2) p2.setAttribute('visibility', 'hidden');
    setParticle('part-grid-span', spanGridAbs, 15000);  // SPAN-only home grid flow
    // CT charging direct from grid only when NOT in V2H mode
    setParticle('part-grid-ct', ctV2H ? 0 : ctW, 11500);
  }
  setParticle('part-home-pool', poolW, 5000);
  // Gateway→CT only when Tesla online and CT not in V2H mode
  setParticle('part-gw-ct', teslaOnline && !ctV2H ? ctW : 0, 11500);
  // V2H: CT feeding home — use part-ct-home if it exists, otherwise part-gw-ct reversed
  const partCtHome = document.getElementById('part-ct-home');
  if (partCtHome) {
    partCtHome.setAttribute('visibility', ctV2H && ctV2HW > 50 ? 'visible' : 'hidden');
    if (ctV2H && ctV2HW > 50) {
      const dur = ctV2HW > 3000 ? '0.75s' : ctV2HW > 500 ? '1.4s' : '2.8s';
      partCtHome.querySelectorAll('animateMotion').forEach(a => a.setAttribute('dur', dur));
    }
  }

  // Stroke width scaling (power proportional)
  function setPathWidth(id, watts, maxW) {
    const el = document.getElementById(id);
    if (!el) return;
    el.setAttribute('stroke-width', Math.max(1.5, Math.min(1, watts / maxW) * 7).toFixed(1));
  }
  setPathWidth('path-solar-span',  enphaseW,   6000);
  setPathWidth('path-solar2-span', solarEdgeW, 6000);
  setPathWidth('path-grid-gw',    teslaOnline ? gridW : 0,         15000);
  setPathWidth('path-gw-span',    teslaOnline ? spanW : 0,         15000);
  setPathWidth('path-grid-span',  teslaOnline ? 0 : spanGridAbs,   15000);  // SPAN-only home flow
  setPathWidth('path-home-pool',  poolW, 5000);
  setPathWidth('path-gw-ct',      teslaOnline ? ctW : 0,           11500);  // Tesla online only
  setPathWidth('path-grid-ct',    teslaOnline ? 0 : ctW,           11500);  // bridge mode only

  // CSS dash animation class (speed tiers)
  function setPathAnim(id, watts) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('flow-path-animated','flow-path-slow','flow-path-fast','flow-path-idle','flow-path-bridge');
    if (watts < 30)        el.classList.add('flow-path-idle');
    else if (watts < 500)  el.classList.add('flow-path-slow');
    else if (watts < 3000) el.classList.add('flow-path-animated');
    else                   el.classList.add('flow-path-fast');
  }
  setPathAnim('path-solar-span',  enphaseW);
  setPathAnim('path-solar2-span', solarEdgeW);
  setPathAnim('path-grid-gw',    teslaOnline ? gridW : 0);
  setPathAnim('path-gw-span',    teslaOnline ? spanW : 0);
  setPathAnim('path-home-pool',  poolW);
  setPathAnim('path-gw-ct',      teslaOnline ? ctW : 0);   // Gateway→CT only when Tesla online
  setPathAnim('path-grid-ct',    teslaOnline ? 0 : ctW);   // Grid→CT direct in bridge mode
  // Bridge paths animation handled above via inline style; clear class conflicts
  if (elGridSpan) elGridSpan.classList.remove('flow-path-animated','flow-path-slow','flow-path-fast','flow-path-idle','flow-path-bridge');
  if (elGridCt)   elGridCt.classList.remove('flow-path-animated','flow-path-slow','flow-path-fast','flow-path-idle','flow-path-bridge');
}

function updateSolarView(s) {
  const sum  = s.summary || {};
  const enph = s.enphase || {};
  const enphaseW = sum.enphase_solar_w || 0;
  const seW      = sum.solaredge_solar_w || 0;

  const el = (id) => document.getElementById(id);
  if (el('solar-enphase-total')) el('solar-enphase-total').textContent = fmt(enphaseW) + ' W';
  if (el('solar-se-total'))      el('solar-se-total').textContent      = fmt(seW) + ' W';

  // Inverter grid
  const inverters = enph.inverters || [];
  const grid = el('solar-inverter-grid');
  const now = Math.floor(Date.now() / 1000);
  if (grid && inverters.length > 0) {
    const isDaytime = (new Date().getHours() >= 6 && new Date().getHours() < 20);
    grid.innerHTML = inverters.map(inv => {
      const ageMin = Math.round((now - inv.reportDate) / 60);
      const ageStr = ageMin < 60 ? ageMin + 'm ago' : Math.round(ageMin/60) + 'h ago';
      const health = (!isDaytime)  ? '#94a3b8' :
                     (ageMin < 30) ? '#22c55e' :
                                     '#ef4444';
      const shortSerial = inv.serial.slice(-6);
      return `<div style="background:#1e293b;border:1px solid ${health};border-radius:8px;padding:8px;text-align:center">
        <div style="font-size:11px;color:#94a3b8;font-family:monospace">${shortSerial}</div>
        <div style="font-size:16px;font-weight:700;color:${health}">${inv.watts}W</div>
        <div style="font-size:10px;color:#64748b">${inv.maxWatts}W max</div>
        <div style="font-size:10px;color:#64748b">${ageStr}</div>
      </div>`;
    }).join('');

    const stale = isDaytime ? inverters.filter(i => (now - i.reportDate) > 1800).length : 0;
    const statusEl = el('solar-inverter-status');
    if (statusEl) {
      statusEl.textContent = stale > 0
        ? `⚠️ ${stale} inverter(s) not reporting`
        : isDaytime ? `✅ All ${inverters.length} inverters reporting` : `🌙 Nighttime — all inverters sleeping`;
      statusEl.style.color = stale > 0 ? '#ef4444' : '#94a3b8';
    }
  }
}

function statusColor(s) {
  if (s==='online') return 'online';
  if (s==='error') return 'error';
  if (s==='partial') return 'partial';
  if (s==='no_token') return 'warning';
  return 'offline';
}

function dotClass(s) {
  if (s==='online'||s==='partial') return 'online';
  if (s==='error') return 'error';
  if (s==='warning'||s==='no_token') return 'warning';
  return 'offline';
}

function toast(msg, dur=3000) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), dur);
}

function pentairSet(objnam, params) {
  fetch('/api/pentair/set', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({objnam, params})
  }).then(r=>r.json()).then(d => {
    if (d.ok) toast('✓ ' + objnam + ' → ' + JSON.stringify(params));
    else toast('✗ ' + (d.error||'Error'), 5000);
  }).catch(e => toast('✗ ' + e, 5000));
}

function saveTeslaPassword() {
  const pw = document.getElementById('tesla-pw-input').value.trim();
  if (!pw) { toast('Enter a password first'); return; }
  const statusEl = document.getElementById('tesla-pw-status');
  statusEl.textContent = 'Saving…';
  statusEl.style.color = 'var(--text-dim)';
  fetch('/api/tesla/set_password', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({password: pw})
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      statusEl.textContent = '✓ Connected — status: ' + d.status;
      statusEl.style.color = 'var(--online)';
      toast('✓ Tesla password saved · status: ' + d.status);
      document.getElementById('tesla-pw-input').value = '';
    } else {
      statusEl.textContent = '✗ ' + (d.error || 'Failed');
      statusEl.style.color = 'var(--error)';
      toast('✗ ' + (d.error || 'Error'), 5000);
    }
  }).catch(e => {
    statusEl.textContent = '✗ Network error: ' + e;
    statusEl.style.color = 'var(--error)';
    toast('✗ Network error', 5000);
  });
}

function renderState(s) {
  window._lastState = s;
  const ts = s.ts ? new Date(s.ts*1000).toLocaleTimeString() : '—';
  document.getElementById('ts').textContent = ts;

  // Status dots
  const sd = s.span||{};  const ed = s.enphase||{}; const pd = s.pentair||{}; const td = s.tesla||{}; const wc = s.wall_connector||{}; const ge = s.ge_appliances||{};
  document.getElementById('span-dot').className    = 'dot ' + dotClass(sd.status);
  document.getElementById('enphase-dot').className = 'dot ' + dotClass(ed.status);
  document.getElementById('pentair-dot').className = 'dot ' + dotClass(pd.status);
  document.getElementById('tesla-dot').className   = 'dot ' + dotClass(td.status);
  document.getElementById('wc-dot').className      = 'dot ' + dotClass(wc.status);

  // ── Wall Connector ──
  const wcBadge = document.getElementById('wc-badge');
  if (wcBadge) {
    wcBadge.textContent = wc.status||'—';
    wcBadge.className = 'badge ' + statusColor(wc.status);
    const wcStatus = wc.charge_status||'—';
    const wcDetail = document.getElementById('wc-detail');
    const wcSession = document.getElementById('wc-session');
    if (wcDetail) wcDetail.textContent = wc.vehicle_connected
      ? (wcStatus==='charging'
          ? `Charging · ${wc.charging_w}W · ${wc.current_a}A · ${wc.grid_v}V`
          : `Vehicle connected · ${wcStatus} · ${wc.grid_v}V grid`)
      : 'No vehicle connected';
    if (wcSession) wcSession.textContent = wc.session_energy_wh
      ? `Session: ${wc.session_energy_wh} Wh · PCBA ${wc.pcba_temp_c}°C`
      : '—';
  }

  // ── Tesla Gateway ──
  const gwBadge = document.getElementById('tesla-gw-badge');
  const gwDetail = document.getElementById('tesla-gw-detail');
  if (gwBadge) {
    gwBadge.textContent = td.status||'not found';
    gwBadge.className = 'badge ' + statusColor(td.status);
  }
  if (gwDetail && td.status==='online') {
    gwDetail.textContent = `SoE: ${td.soe}% · Solar: ${td.solar_w}W · Grid: ${td.grid_w}W · Battery: ${td.battery_w}W`;
  }

  // ── Cockpit ──
  const sum = s.summary||{};
  const solarW = sum.solar_w||0, loadW = sum.load_w||0, batW = sum.battery_w||0, gridW = sum.grid_w||0;

  document.getElementById('f-solar').textContent  = fmt(solarW);
  document.getElementById('f-load').textContent   = fmt(loadW);
  document.getElementById('f-battery').textContent = fmt(Math.abs(batW)) + (batW>0?' ↓':batW<0?' ↑':'');
  document.getElementById('f-grid').textContent   = fmt(Math.abs(gridW));
  document.getElementById('f-soe').textContent    = td.soe != null ? td.soe+'%' : '—';
  document.getElementById('f-grid-dir').textContent = gridW > 0 ? 'importing' : (gridW < 0 ? 'exporting' : 'balanced');

  document.getElementById('solar-w').textContent  = solarW >= 1000 ? (solarW/1000).toFixed(2)+'k' : Math.round(solarW);
  const _bSoe = document.getElementById('battery-soe'); if(_bSoe) _bSoe.textContent = td.soe != null ? Math.round(td.soe) : '—';
  document.getElementById('grid-w').textContent   = Math.abs(gridW) >= 1000 ? (Math.abs(gridW)/1000).toFixed(2)+'k' : Math.round(Math.abs(gridW));
  document.getElementById('load-w').textContent   = loadW >= 1000 ? (loadW/1000).toFixed(2)+'k' : Math.round(loadW);
  document.getElementById('grid-dir').textContent = gridW > 50 ? 'Importing from grid' : (gridW < -50 ? 'Exporting to grid' : 'Grid balanced');

  const selfPct = sum.self_powered_pct||0;
  document.getElementById('self-pct').textContent = selfPct.toFixed(0);
  document.getElementById('self-bar').style.width = selfPct + '%';

  // Update animated SVG power flow diagram
  updateFlowDiagram(s);

  // Update Solar view (inverter grid + totals)
  updateSolarView(s);

  // Badges
  document.getElementById('enphase-badge').textContent = ed.status||'—';
  document.getElementById('enphase-badge').className = 'badge ' + statusColor(ed.status);
  const _tbadge = document.getElementById('tesla-badge'); if(_tbadge){_tbadge.textContent=td.status||'—';_tbadge.className='badge '+statusColor(td.status);}
  document.getElementById('pentair-badge').textContent = pd.status||'—';
  document.getElementById('pentair-badge').className = 'badge ' + statusColor(pd.status);

  // Pool summary in cockpit
  const pump = (pd.pool && pd) ? pd.pump||{} : {};
  const pool = pd.pool||{};
  document.getElementById('pool-temp').textContent = pool.temp || '—';
  document.getElementById('pump-rpm').textContent  = pump.rpm != null ? pump.rpm : '—';
  document.getElementById('pump-w').textContent    = pump.power_w != null ? pump.power_w : '—';
  document.getElementById('pool-status-line').textContent =
    `Pool: ${pool.status||'?'} · Spa: ${(pd.spa||{}).status||'?'} · Heater: ${((pool.status==='ON'&&(pool.heat_source||'')==='H0001')||((pd.spa||{}).status==='ON'&&((pd.spa||{}).heat_source||'')==='H0001'))?'HEATING':'IDLE'}`;

  // Solar sub
  document.getElementById('solar-sub').textContent =
    ed.status==='online'||ed.status==='partial' ? `Enphase D8.3.5167 · ${ed.serial||'202324023651'}` : 'Enphase · needs token';
  const _bsub = document.getElementById('battery-sub'); if(_bsub) _bsub.textContent = td.status==='online' ? 'Tesla Gateway 3V · online' : 'Tesla Gateway 3V · offline';

  // Grid badge
  const gb = document.getElementById('grid-badge');
  if (td.status==='online') { gb.textContent = td.islanded?'islanded':'grid-tie'; gb.className='badge '+(td.islanded?'warning':'online'); }
  else { gb.textContent='no tesla'; gb.className='badge offline'; }

  // ── SPAN View ──
  const sb2 = document.getElementById('span-badge2');
  sb2.textContent = sd.status||'—';
  sb2.className = 'badge ' + statusColor(sd.status);
  document.getElementById('span-grid-power').textContent = `Grid: ${fmt(sd.grid_power)}`;
  document.getElementById('span-no-token').style.display = (sd.status==='no_token'||!SPAN_TOKEN_CONFIGURED) ? 'block' : 'none';

  const circGrid = document.getElementById('circuit-grid');
  const circuits = sd.circuits||[];
  if (circuits.length) {
    circGrid.innerHTML = circuits.map(c => {
      const col = circuitColors.get(c.name) || '#00d4ff';
      const svg = miniSparkSVG(history5.get(c.name), col);
      const isOff = c.relay === 'OPEN';
      return `<div class="circuit-tile ${c.relay==='CLOSED'?c.color:'off'}" data-name="${c.name}" title="${c.id}" style="cursor:pointer;padding-bottom:${svg?'22px':'10px'};position:relative;" onclick="if(chartsReady)selectCircuit(this.dataset.name)">
        <div class="ct-name">${c.name}</div>
        <div><span class="ct-power">${Math.abs(c.power_w)||0}</span><span class="ct-unit"> W</span></div>
        <div class="ct-relay">${c.relay||'?'} · ${c.priority||'?'}</div>
        ${isOff ? `<button onclick="event.stopPropagation();restoreSpanCircuit('${c.id}','${c.name}')" style="margin-top:4px;width:100%;padding:3px 0;border-radius:4px;border:1px solid rgba(74,222,128,.5);background:rgba(74,222,128,.1);color:#4ade80;font-size:9px;cursor:pointer;">⚡ Restore</button>` : ''}
        ${svg}
      </div>`;
    }).join('');
  } else if (sd.status==='no_token') {
    circGrid.innerHTML = '';
  }
  updateSpanCharts(sd);

  // ── Pool View ──
  // Pentair system badge
  const pcBadge = document.getElementById('pc-pentair-badge');
  if (pcBadge) { pcBadge.textContent = pd.status||'?'; pcBadge.className = 'badge ' + statusColor(pd.status); }

  // Pool body card
  const bpb = document.getElementById('pool-body-badge');
  if (bpb) { bpb.textContent = pool.status||'?'; bpb.className = 'badge ' + (pool.status==='ON'?'online':'offline'); }
  const poolCard = document.getElementById('pc-pool-card');
  if (poolCard) { poolCard.className = 'pc-stat-card ' + (pool.status==='ON' ? 'card-on' : 'card-off'); }
  const pcPoolTemp = document.getElementById('pc-pool-temp');
  if (pcPoolTemp) pcPoolTemp.textContent = pool.temp ? pool.temp+'°F' : '—°F';
  const pcPoolSp = document.getElementById('pc-pool-setpoint');
  if (pcPoolSp) pcPoolSp.textContent = `Setpoint: ${pool.setpoint_lo||'?'} / ${pool.setpoint_hi||'?'} °F`;
  const pcPoolHeat = document.getElementById('pc-pool-heat');
  if (pcPoolHeat) pcPoolHeat.textContent = `Heat: ${pool.heat_source||'?'}`;

  // Spa hero card
  const spa = pd.spa||{};
  const spaOn = spa.status === 'ON';
  const spaHero = document.getElementById('pc-spa-hero');
  if (spaHero) { spaHero.classList.toggle('spa-on', spaOn); }
  const pcSpaStatus = document.getElementById('pc-spa-status');
  if (pcSpaStatus) { pcSpaStatus.textContent = spaOn ? 'ON' : 'OFF'; pcSpaStatus.className = 'pc-hero-status ' + (spaOn ? 'status-on' : 'status-off'); }
  const pcSpaTemp = document.getElementById('pc-spa-temp');
  if (pcSpaTemp) pcSpaTemp.innerHTML = spa.temp ? spa.temp+'<sup>°F</sup>' : '—<sup>°F</sup>';
  const pcSpaSp = document.getElementById('pc-spa-setpoint');
  if (pcSpaSp) pcSpaSp.textContent = `Target: ${spa.setpoint_lo||'?'} °F`;

  // Pump card
  const pumpOn = (pump.power_w != null && pump.power_w > 10) || (pump.rpm != null && pump.rpm > 0);
  const pcPumpCard = document.getElementById('pc-pump-card');
  if (pcPumpCard) { pcPumpCard.className = 'pc-stat-card ' + (pumpOn ? 'card-running' : 'card-off'); }
  const pcPumpBadge = document.getElementById('pc-pump-badge');
  if (pcPumpBadge) { pcPumpBadge.textContent = pump.status||'?'; pcPumpBadge.className = 'badge ' + (pumpOn?'online':'offline'); }
  const pcPumpRpm = document.getElementById('pc-pump-rpm');
  if (pcPumpRpm) pcPumpRpm.textContent = pump.rpm != null ? pump.rpm : '—';
  const pcPumpGpm = document.getElementById('pc-pump-gpm-val');
  if (pcPumpGpm) pcPumpGpm.textContent = pump.gpm != null ? pump.gpm : '—';
  const pcPumpW = document.getElementById('pc-pump-w-val');
  if (pcPumpW) pcPumpW.textContent = pump.power_w != null ? pump.power_w : '—';

  // Heater card — "active" only when a body is ON and using H0001 as heat source
  const poolHtsrc = (pd.pool||{}).heat_source||'';
  const spaHtsrc  = (pd.spa||{}).heat_source||'';
  const poolOn    = ((pd.pool||{}).status||'') === 'ON';
  const spaOnH    = ((pd.spa||{}).status||'') === 'ON';
  const heaterActive = (poolOn && poolHtsrc === 'H0001') || (spaOnH && spaHtsrc === 'H0001');
  const heaterLabel  = heaterActive ? 'HEATING' : 'IDLE';
  const spaHeatLabel = spaHtsrc === 'H0001' ? 'Gas' : (spaHtsrc === '00000' ? 'None' : spaHtsrc);
  const pcHeaterCard = document.getElementById('pc-heater-card');
  if (pcHeaterCard) { pcHeaterCard.className = 'pc-stat-card ' + (heaterActive ? 'card-running' : 'card-off'); }
  const pcHeaterBadge = document.getElementById('pc-heater-badge');
  if (pcHeaterBadge) { pcHeaterBadge.textContent = heaterLabel; pcHeaterBadge.className = 'badge ' + (heaterActive?'online':'offline'); }
  const pcHeaterSt = document.getElementById('pc-heater-status');
  if (pcHeaterSt) pcHeaterSt.textContent = `Spa heat: ${spaHeatLabel} · Pool heat: ${poolHtsrc==='H0001'?'Gas':'None'}`;

  // Circuit tiles
  const poolCirc = document.getElementById('pool-circuits');
  if (poolCirc) {
    poolCirc.innerHTML = (pd.circuits||[]).map(c => {
      const on = c.status === 'ON';
      return `<div class="pc-circ-tile ${on?'circ-on':'circ-off'}">
        <div class="pc-circ-nm">${c.name}</div>
        <div class="pc-circ-st">${c.status||'?'}</div>
        <div style="display:flex;gap:4px;margin-top:6px">
          <button class="btn" style="flex:1;padding:4px 0;font-size:10px" onclick="pentairSet('${c.id}',{STATUS:'ON'})">ON</button>
          <button class="btn" style="flex:1;padding:4px 0;font-size:10px" onclick="pentairSet('${c.id}',{STATUS:'OFF'})">OFF</button>
        </div>
      </div>`;
    }).join('');
  }

  // ── Devices View ──
  function fmtLastSeen(ts) {
    if (!ts) return 'never';
    const ago = Math.round((Date.now()/1000) - ts);
    if (ago < 15)  return 'just now';
    if (ago < 60)  return ago + 's ago';
    if (ago < 3600) return Math.round(ago/60) + 'm ago';
    return Math.round(ago/3600) + 'h ago';
  }
  function dcUpdate(id, st, metric, lastseen) {
    const card = document.getElementById('dc-' + id);
    const dot  = document.getElementById('dc-' + id + '-dot');
    const badge = document.getElementById('dev-' + id + '-badge') || document.getElementById('dc-' + id + '-badge') || (id==='wc'?document.getElementById('wc-badge'):null) || (id==='tesla'?document.getElementById('tesla-gw-badge'):null);
    const metEl = document.getElementById('dc-' + id + '-metric');
    const lsEl  = document.getElementById('dc-' + id + '-lastseen');
    const cls = statusColor(st);
    if (card) { card.className = 'dev-card status-' + (st==='online'?'online':st==='error'?'error':st==='no_token'||st==='warning'?'warning':'offline'); }
    if (dot)  { dot.className  = 'dev-sdot ' + (st==='online'?'online':st==='error'?'error':st==='no_token'||st==='warning'?'warning':'offline'); }
    if (badge){ badge.textContent = st||'—'; badge.className = 'badge ' + cls; }
    if (metEl && metric != null) { metEl.innerHTML = metric; }
    if (lsEl)  { lsEl.textContent = 'last seen: ' + fmtLastSeen(lastseen); }
  }

  dcUpdate('span',    sd.status, `${sd.grid_power!=null?Math.round(sd.grid_power):'—'}<span> W grid · door: ${sd.door||'?'}</span>`, sd.last_seen);
  dcUpdate('enphase', ed.status, `${ed.production_w!=null?Math.round(ed.production_w):'—'}<span> W solar</span>`, ed.last_seen);
  dcUpdate('tesla',   td.status, `${td.soe!=null?td.soe:'—'}<span>% SoE · ${td.solar_w!=null?Math.round(td.solar_w):'—'} W solar</span>`, td.last_seen);

  // Wall Connector — show charge state + watts
  const wcSt = wc.status;
  let wcMetric = '—';
  if (wcSt === 'online') {
    wcMetric = wc.vehicle_connected
      ? (wc.charge_status === 'charging'
          ? `${wc.charging_w!=null?Math.round(wc.charging_w):'—'}<span> W · ${wc.current_a}A · charging</span>`
          : `<span>vehicle connected · ${wc.charge_status||'—'}</span>`)
      : '<span>no vehicle</span>';
  }
  dcUpdate('wc', wcSt, wcMetric, wc.last_seen);

  // Pentair
  const poolT = (pd.pool||{}).temp;
  const pumpR = (pd.pump||{}).rpm;
  dcUpdate('pentair', pd.status,
    poolT ? `${poolT}<span>°F pool · ${pumpR||'—'} RPM</span>` : '<span>—</span>',
    pd.last_seen);

  // Nest
  const nd = s.nest||{};
  dcUpdate('nest', nd.status,
    nd.temp_f ? `${nd.temp_f}<span>°F · ${nd.hvac_state||'—'}</span>` : '<span>—°F</span>',
    nd.last_seen);

  // B-Hyve
  const bh = s.bhyve||{};
  const bhZones = (bh.zones||[]).length;
  const bhRunning = (bh.zones||[]).filter(z=>z.is_running).length;
  dcUpdate('bhyve', bh.status,
    bhZones ? `${bhZones}<span> zones${bhRunning?' · '+bhRunning+' running':''}</span>` : '<span>—</span>',
    bh.last_seen);

  // GE SmartHQ
  const geApps = (ge.appliances||[]).length;
  const geRunning = (ge.appliances||[]).filter(a=>a.state==='running').length;
  dcUpdate('ge', ge.status,
    geApps ? `${geApps}<span> appliance${geApps!==1?'s':''}${geRunning?' \xb7 '+geRunning+' running':''}</span>` : '<span>\u2014</span>',
    ge.last_seen);

  // Wyze cameras — match by name fragment
  const cams = s.cameras||[];
  function camCard(cardSuffix, nameHint) {
    const cam = cams.find(c=>c.name&&c.name.toLowerCase().includes(nameHint));
    const card = document.getElementById('dc-cam-' + cardSuffix);
    const dot   = document.getElementById('dc-cam-' + cardSuffix + '-dot');
    const badge = document.getElementById('dc-cam-' + cardSuffix + '-badge');
    const metEl = document.getElementById('dc-cam-' + cardSuffix + '-metric');
    const lsEl  = document.getElementById('dc-cam-' + cardSuffix + '-lastseen');
    const st = cam ? cam.status : (cams.length > 0 ? 'offline' : 'offline');
    const cls = st === 'online' ? 'online' : 'offline';
    if (card)  { card.className  = 'dev-card status-' + cls; }
    if (dot)   { dot.className   = 'dev-sdot ' + cls; }
    if (badge) { badge.textContent = st; badge.className = 'badge ' + cls; }
    if (metEl) { metEl.innerHTML  = cam ? (cam.last_motion ? `<span>motion: ${cam.last_motion}</span>` : '<span>no recent motion</span>') : '<span>—</span>'; }
    if (lsEl)  { lsEl.textContent = cam && cam.last_seen ? 'last seen: ' + cam.last_seen : 'last seen: —'; }
  }
  camCard('front', 'front');
  camCard('up',    'upstairs');
  camCard('down',  'downstairs');

  // MyQ Garage
  const myq = s.myq||{};
  const myqDoors = myq.doors||[];
  dcUpdate('myq', myq.status,
    myqDoors.length ? `${myqDoors.length}<span> door${myqDoors.length!==1?'s':''}</span>` : '<span>—</span>',
    myq.last_seen);
  const myqDoorsEl = document.getElementById('dc-myq-doors');
  if (myqDoorsEl) {
    if (myq.status === 'unconfigured') {
      myqDoorsEl.innerHTML = '<div style="font-size:10px;color:var(--text-dim);margin-top:2px">Set MYQ_EMAIL + MYQ_PASSWORD env vars</div>';
    } else {
      myqDoorsEl.innerHTML = myqDoors.map(function(d, i) {
        const st = (d.state||'unknown').toLowerCase();
        const stCls = (st==='open'||st==='opening') ? 'error' : (st==='closed' ? 'online' : 'warning');
        return '<div style="display:flex;align-items:center;gap:5px;margin-top:4px;flex-wrap:wrap">'
          + '<span style="font-size:11px;font-weight:600;color:var(--text);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + (d.name||'Door') + '</span>'
          + '<span class="badge ' + stCls + '" style="font-size:9px;padding:2px 5px">' + st.toUpperCase() + '</span>'
          + '<button class="btn" style="padding:3px 8px;font-size:11px" data-myq-idx="' + i + '" data-myq-action="open" title="Open door">\u25b2</button>'
          + '<button class="btn" style="padding:3px 8px;font-size:11px" data-myq-idx="' + i + '" data-myq-action="close" title="Close door">\u25bc</button>'
          + '</div>';
      }).join('');
      myqDoorsEl.querySelectorAll('[data-myq-action]').forEach(function(btn) {
        var idx = parseInt(btn.getAttribute('data-myq-idx'), 10);
        var action = btn.getAttribute('data-myq-action');
        btn.onclick = function() { myqCmd(myqDoors[idx].serial, action); };
      });
    }
  }

  // Online device count
  const devStatuses = [sd.status, ed.status, td.status, wc.status, pd.status, nd.status, bh.status, myq.status, ge.status];
  const onlineCount = devStatuses.filter(x=>x==='online'||x==='partial'||x==='no_token').length
    + cams.filter(c=>c.status==='online').length;
  const totalCount  = devStatuses.length + 3; // +3 wyze cams
  const countEl = document.getElementById('dev-online-count');
  if (countEl) countEl.textContent = `${onlineCount} / ${totalCount} online`;

  // ── Tesla Energy View ──
  const teBadge = document.getElementById('tesla-energy-badge');
  const teSetup = document.getElementById('tesla-setup-card');
  const teTiles = document.getElementById('tesla-energy-tiles');
  const teRaw   = document.getElementById('tesla-state-raw');

  if (teBadge) {
    teBadge.textContent = td.status || '—';
    teBadge.className   = 'badge ' + statusColor(td.status);
  }

  // Site name
  const teNameEl = document.getElementById('te-site-name');
  if (teNameEl && td.site_name) teNameEl.textContent = td.site_name;

  // Grid state dot + label (always updated regardless of online status)
  const teGridDot    = document.getElementById('te-grid-state-dot');
  const teGridTxt    = document.getElementById('te-grid-state-text');
  const teGridDetail = document.getElementById('te-grid-state-detail');
  if (teGridDot && td.status === 'online') {
    const islanded = td.islanded;
    teGridDot.style.background = islanded ? 'var(--warning)' : 'var(--online)';
    teGridDot.style.boxShadow  = islanded ? '0 0 6px var(--warning)' : '0 0 6px var(--online)';
    if (teGridTxt)    teGridTxt.textContent    = islanded ? 'Islanded' : 'Grid-Tied';
    if (teGridDetail) teGridDetail.textContent = islanded ? 'Operating on backup power' : 'Connected to SRP utility grid';
  }

  const teslaOnline = td.status === 'online';
  if (teSetup) teSetup.style.display = teslaOnline ? 'none' : 'block';
  if (teTiles) teTiles.style.display = teslaOnline ? 'block' : 'none';

  if (teslaOnline) {
    const batW   = td.battery_w || 0;
    const gridW2 = td.grid_w    || 0;
    const soe    = td.soe       != null ? td.soe : 0;
    const solarW = td.solar_w   || 0;

    // Text metrics
    const setT = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setT('te-solar',    Math.round(solarW));
    setT('te-soe',      Math.round(soe));   // hidden span — compat
    setT('te-bat-w',    fmt(Math.abs(batW)) + ' W');
    setT('te-bat-dir',  batW > 50 ? '↓ discharging' : (batW < -50 ? '↑ charging' : '○ idle'));
    setT('te-grid',     Math.round(Math.abs(gridW2)));
    setT('te-grid-dir', gridW2 > 50 ? 'Importing from grid' : (gridW2 < -50 ? 'Exporting to grid' : 'Grid balanced'));
    setT('te-load',     Math.round(td.load_w || 0));
    const tgb = document.getElementById('te-grid-badge');
    if (tgb) { tgb.textContent = td.islanded ? 'islanded' : 'grid-tie'; tgb.className = 'badge ' + (td.islanded ? 'warning' : 'online'); }

    // Battery SOC ring (circumference 2π×50 ≈ 314)
    const socArc  = document.getElementById('te-soc-arc');
    const socText = document.getElementById('te-soc-text');
    if (socArc) {
      socArc.setAttribute('stroke-dashoffset', (314 * (1 - soe / 100)).toFixed(1));
      const socColor = soe > 40 ? '#10b981' : (soe > 20 ? '#f59e0b' : '#ef4444');
      socArc.setAttribute('stroke', socColor);
      if (socText) { socText.textContent = Math.round(soe); socText.setAttribute('fill', socColor); }
    }

    // Solar arc gauge (half-circle arc length ≈ 176, max 10 kW)
    const solarArc  = document.getElementById('te-solar-arc');
    const solarText = document.getElementById('te-solar-text');
    if (solarArc) {
      solarArc.setAttribute('stroke-dashoffset', (176 * (1 - Math.min(solarW, 10000) / 10000)).toFixed(1));
      if (solarText) solarText.textContent = solarW >= 1000 ? (solarW / 1000).toFixed(1) + 'k' : Math.round(solarW);
    }

    // Backup reserve bar
    if (td.backup_reserve_percent != null) {
      const rb  = document.getElementById('te-reserve-bar');
      const rp2 = document.getElementById('te-reserve-pct');
      if (rb)  rb.style.width  = td.backup_reserve_percent + '%';
      if (rp2) rp2.textContent = td.backup_reserve_percent + '%';
    }
  }

  if (teRaw) {
    teRaw.innerHTML = `
      Status: <strong>${td.status || '—'}</strong> &nbsp;|&nbsp;
      SoE: <strong>${td.soe != null ? td.soe + '%' : '—'}</strong> &nbsp;|&nbsp;
      Solar: <strong>${fmt(td.solar_w)}</strong> &nbsp;|&nbsp;
      Battery: <strong>${fmt(td.battery_w)}</strong> &nbsp;|&nbsp;
      Grid: <strong>${fmt(td.grid_w)}</strong> &nbsp;|&nbsp;
      Load: <strong>${fmt(td.load_w)}</strong> &nbsp;|&nbsp;
      Grid state: <strong>${td.grid_state || '—'}</strong> &nbsp;|&nbsp;
      Backup reserve: <strong>${td.backup_reserve_percent != null ? td.backup_reserve_percent + '%' : '—'}</strong>
    `;
  }

  // ── Cybertruck View ──
  const ctConnBadge = document.getElementById('ct-connection-badge');
  const ctWcBadge   = document.getElementById('ct-wc-badge');

  if (ctConnBadge) {
    ctConnBadge.textContent = wc.status || '—';
    ctConnBadge.className   = 'badge ' + statusColor(wc.status);
  }
  if (ctWcBadge) {
    const csMap  = {charging:'online', complete:'partial', standby:'offline', fault:'error', auth_required:'offline'};
    const csNames = {auth_required:'Ready',charging:'Charging',complete:'Complete',standby:'Standby',disconnected:'No Vehicle',fault:'Fault',wait_car:'Waiting',booting:'Booting',powersharing:'Powershare'};
    ctWcBadge.textContent = csNames[wc.charge_status] || wc.charge_status || wc.status || '—';
    ctWcBadge.className = 'badge ' + (csMap[wc.charge_status] || statusColor(wc.status));
  }

  const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  const csLabel = {
    'auth_required':       'Ready — No Vehicle',
    'charging':            'Charging',
    'complete':            'Charge Complete',
    'disconnected':        'No Vehicle',
    'standby':             'Standby',
    'fault':               'Fault',
    'wait_car':            'Waiting for Vehicle',
    'booting':             'Booting',
    'powersharing':        'V2H Powershare',
    'vehicle_powersharing':'V2H Powershare',
  };
  setEl('ct-charge-status', csLabel[wc.charge_status] || wc.charge_status || '—');
  setEl('ct-vehicle',       wc.vehicle_connected ? '🔌 Connected' : 'Not Connected');
  setEl('ct-rate-w',        wc.charging_w != null ? Math.round(wc.charging_w) : '—');
  setEl('ct-rate-a',        wc.current_a  != null ? wc.current_a + ' A' : '— A');
  setEl('ct-session',       wc.session_energy_wh != null ? wc.session_energy_wh : '—');
  setEl('ct-grid-v',        wc.grid_v     != null ? wc.grid_v + ' V' : '— V');
  setEl('ct-temp',          wc.pcba_temp_c != null ? wc.pcba_temp_c + ' °C' : '— °C');
  // Session duration h:mm:ss
  const wcSessS = wc.session_s || 0;
  if (wcSessS > 0) {
    const sh = Math.floor(wcSessS / 3600), sm = Math.floor((wcSessS % 3600) / 60), ssc = wcSessS % 60;
    setEl('ct-session-dur', sh + ':' + String(sm).padStart(2,'0') + ':' + String(ssc).padStart(2,'0'));
  } else {
    setEl('ct-session-dur', '—');
  }

  // ── Cameras ──
  renderCameras(s.cameras || []);

  // ── Nest ──
  renderNest(s.nest || {});

  // ── B-Hyve Sprinklers ──
  renderBhyve(s.bhyve || {});

  // ── GE SmartHQ Appliances ──
  renderAppliances(s.ge_appliances || {});
  // ── Active appliance banner ──
  (function() {
    const banner = document.getElementById('appliance-banner');
    if (!banner) return;
    const apps = (s.ge_appliances || {}).appliances || [];
    const active = apps.filter(a => a.state === 'running' || a.state === 'paused' || a.state === 'end of cycle');
    if (!active.length) { banner.style.display = 'none'; return; }
    banner.style.display = 'flex';
    banner.innerHTML = active.map(a => {
      const icon = a.type && a.type.includes('Dry') ? '🌀' : a.type && a.type.includes('Dish') ? '🍽️' : '🧺';
      const secsLeft = a.seconds_remaining || 0;
      const timeStr = secsLeft > 0 ? ` · ${Math.ceil(secsLeft/60)}m left` : '';
      const cycleStr = a.cycle ? ` · ${a.cycle}` : '';
      const stColor = a.state === 'running' ? '#10b981' : '#f59e0b';
      return `<span onclick="showView('appliances')" style="cursor:pointer;display:inline-flex;align-items:center;gap:6px;padding:3px 10px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.25);border-radius:12px;color:${stColor};font-weight:600">
        <span style="width:6px;height:6px;border-radius:50%;background:${stColor};animation:ge-dot-pulse 1.5s ease-in-out infinite"></span>
        ${icon} ${a.name}${cycleStr}${timeStr}
      </span>`;
    }).join('') + `<span style="color:var(--text-muted);font-size:11px;margin-left:auto">tap to view →</span>`;
  })();

  // ── Settings badges ──
  const settingsTeslaBadge = document.getElementById('settings-tesla-badge');
  if (settingsTeslaBadge) { settingsTeslaBadge.textContent = td.status||'—'; settingsTeslaBadge.className = 'badge ' + statusColor(td.status); }
  const wyzeBadge = document.getElementById('wyze-cfg-badge');
  if (wyzeBadge) { const wyzeCfg = (s.cameras||[]).some(c=>c.type==='wyze'); wyzeBadge.textContent = wyzeCfg ? 'connected' : 'unconfigured'; wyzeBadge.className = 'badge ' + (wyzeCfg ? 'online' : 'offline'); }
  const ringBadge = document.getElementById('ring-cfg-badge');
  if (ringBadge) { const ringCfg = (s.cameras||[]).some(c=>c.type==='ring'); ringBadge.textContent = ringCfg ? 'connected' : 'unconfigured'; ringBadge.className = 'badge ' + (ringCfg ? 'online' : 'offline'); }
  // bhyve badge in settings is handled by renderBhyve() above
  const geCfgBadge = document.getElementById('ge-cfg-badge');
  if (geCfgBadge) { geCfgBadge.textContent = ge.status||'unconfigured'; geCfgBadge.className = 'badge ' + statusColor(ge.status||'unconfigured'); }

  // ── Unified settings cfg-badges ──
  function _cfgBadge(id, status, statsText) {
    const b = document.getElementById('cfg-badge-'+id);
    if (b) { b.textContent = status||'—'; b.className = 'badge ' + statusColor(status); }
    const st = document.getElementById('cfg-stats-'+id);
    if (st && statsText) st.textContent = statsText;
  }
  _cfgBadge('span', sd.status, sd.status==='online' ? `${sd.circuits?.length||0} circuits · ${(sd.grid_power||0).toFixed(0)}W grid` : null);
  _cfgBadge('enphase', ed.status, ed.today_wh > 0 ? `${(ed.today_wh/1000).toFixed(1)} kWh today · ${ed.production_w||0}W now` : (ed.status==='online'?'Online · no production data':'—'));
  _cfgBadge('solaredge', null, null);
  const seBadgeEl = document.getElementById('cfg-badge-solaredge');
  if (seBadgeEl) { const seW = (s.summary||{}).solaredge_solar_w||0; seBadgeEl.textContent = seW > 0 ? 'online' : ed.status==='online' ? 'online' : 'offline'; seBadgeEl.className = 'badge ' + (ed.status==='online'?'online':'offline'); const seSt = document.getElementById('cfg-stats-solaredge'); if(seSt) seSt.textContent = seW > 0 ? `${seW}W now (derived from SPAN − Enphase)` : '—'; }
  const cfgTeslaSt = document.getElementById('cfg-stats-tesla');
  if (cfgTeslaSt) cfgTeslaSt.textContent = td.status==='online' ? `SoE: ${td.soe}% · Solar: ${td.solar_w||0}W · Grid: ${td.grid_w||0}W` : (td.status||'offline');
  _cfgBadge('wallconnector', wc.status, wc.status==='online' ? (wc.vehicle_connected ? `${wc.charge_status==='charging'?wc.charging_w+'W charging':'Vehicle connected · '+wc.charge_status}` : 'No vehicle') : null);
  _cfgBadge('pentair', pd.status, pd.status==='online' ? `Pool ${(pd.pool||{}).temp||'—'}°F · Spa ${(pd.spa||{}).temp||'—'}°F · Pump ${(pd.pump||{}).rpm||'—'} RPM` : 'Check network connection');
  // nest badge already handled by nest-cfg-badge; update cfg-stats
  const nestCfgSt = document.getElementById('cfg-stats-nest');
  if (nestCfgSt) { const _nd = s.nest||{}; const nts = _nd.thermostats||[]; nestCfgSt.textContent = nts.length ? nts.map(t=>t.name+' '+Math.round(t.temp_f||0)+'°F '+((t.hvac_state||'').toLowerCase())).join(' · ') : (_nd.temp_f ? Math.round(_nd.temp_f)+'°F' : '—'); }
  // wyze/ring/bhyve/ge stats
  const wyzeSt = document.getElementById('cfg-stats-wyze');
  if (wyzeSt) { const cams = s.cameras||[]; const wyzeCams = cams.filter(c=>c.type==='wyze'); wyzeSt.textContent = wyzeCams.length ? wyzeCams.map(c=>c.name+' '+c.status).join(' · ') : '—'; }
  const ringSt = document.getElementById('cfg-stats-ring');
  if (ringSt) { const cams = s.cameras||[]; const ringCams = cams.filter(c=>c.type==='ring'); ringSt.textContent = ringCams.length ? ringCams.map(c=>c.name+' '+c.status).join(' · ') : '—'; }
  const bhyveSt = document.getElementById('cfg-stats-bhyve');
  if (bhyveSt) { const bh2 = s.bhyve||{}; const bz = (bh2.zones||[]).length; const br = (bh2.zones||[]).filter(z=>z.is_running).length; bhyveSt.textContent = bz ? `${bz} zones${br?' · '+br+' running':''}` : '—'; }
  const geSt = document.getElementById('cfg-stats-ge');
  if (geSt) { const geA = (ge.appliances||[]).length; const geR = (ge.appliances||[]).filter(a=>a.state==='running').length; geSt.textContent = geA ? `${geA} appliances${geR?' · '+geR+' running':''}` : '—'; }
  const _rokuSt = s.roku || window._lastRoku || [];
  _cfgBadge('roku', _rokuSt.length ? 'online' : 'offline', _rokuSt.length ? _rokuSt.map(t=>t.name).join(', ') : 'No TVs found');
  // Auto-expand credentials when unconfigured
  ['wyze','ring','nest','bhyve','ge'].forEach(d => {
    const badge = document.getElementById(d==='nest'?'nest-cfg-badge':d==='ge'?'ge-cfg-badge':(d+'-cfg-badge'));
    const details = document.getElementById('cfg-creds-'+d);
    if (badge && details && (badge.textContent === 'unconfigured' || badge.textContent === 'offline')) details.open = true;
  });

  // ── Tablet dashboard modes ──
  try { updateMicrogrid(s); } catch(e) { console.warn('Microgrid update error:', e); }
  try { updateTrading(s);   } catch(e) { console.warn('Trading update error:',   e); }
  try { updateBackup(s);    } catch(e) { console.warn('Backup update error:',    e); }
  // Roku: update from SSE state — no separate fetch
  if (s.roku && s.roku.length) { try { renderRoku(s.roku); } catch(e) { console.warn('Roku render error:', e); } }

  // Auto-save energy data to localStorage for persistence across page refreshes
  saveHistToCache();
}

// ╔══════════════════════════════════════════════════════════════════════╗
// ║  SPAN ENERGY VISUALIZATION — Charts                                  ║
// ╚══════════════════════════════════════════════════════════════════════╝

const CIRCUIT_PALETTE = [
  '#00d4ff','#ff6b6b','#ffd93d','#6bcb77','#ff8c42','#c77dff',
  '#4ecdc4','#ff6b9d','#95e1d3','#f38181','#aa96da','#fcbad3',
  '#e8d5b7','#a8d8ea','#fd7272','#9de3d0','#ffb347','#87ceeb',
  '#dda0dd','#90ee90','#f0e68c'
];

const MAX_HIST_5MIN  = 60;   // 5 min at ~5s intervals
const MAX_HIST_60MIN = 720;  // 60 min at ~5s intervals

const circuitColors = new Map();   // name → hex color
const history5      = new Map();   // name → last 60 watts values
const history60     = new Map();   // name → last 720 watts values
const historyLabels = [];          // last 720 time labels (shared x-axis)
const totalHistory5 = [];          // last 60 total-load values

let selectedCircuit    = null;
let spanBarChart       = null;
let spanDonutChart     = null;
let spanTimelineChart  = null;
let spanSparklineChart = null;
let spanHistoryChart   = null;
let chartsReady        = false;

function assignColor(name) {
  if (!circuitColors.has(name)) {
    circuitColors.set(name, CIRCUIT_PALETTE[circuitColors.size % CIRCUIT_PALETTE.length]);
  }
  return circuitColors.get(name);
}

function pushCapped(arr, val, max) {
  arr.push(val);
  if (arr.length > max) arr.shift();
}

// Tiny inline SVG sparkline for circuit tiles (last 10 points)
function miniSparkSVG(hist, color) {
  if (!hist || hist.length < 2) return '';
  const pts = hist.slice(-10);
  const max = Math.max(...pts, 1);
  const coords = pts.map((v, i) => {
    const x = ((i / (pts.length - 1)) * 100).toFixed(1);
    const y = (17 - (v / max) * 16).toFixed(1);
    return `${x},${y}`;
  }).join(' ');
  const poly = `0,18 ${coords} 100,18`;
  return `<svg class="ct-mini-spark" viewBox="0 0 100 18" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">`
       + `<polygon points="${poly}" fill="${color}" opacity="0.2"/>`
       + `<polyline points="${coords}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>`
       + `</svg>`;
}

function initSpanCharts() {
  if (chartsReady || typeof Chart === 'undefined') return;

  Chart.defaults.color          = 'rgba(255,255,255,0.6)';
  Chart.defaults.borderColor    = 'rgba(255,255,255,0.07)';
  Chart.defaults.font.family    = "'Segoe UI', system-ui, sans-serif";
  Chart.defaults.font.size      = 11;

  const grid = { color: 'rgba(255,255,255,0.07)' };
  const wTick = { color: 'rgba(255,255,255,0.45)', maxTicksLimit: 5,
                  callback: v => v >= 1000 ? (v/1000).toFixed(1)+'kW' : v+'W' };
  const baseAnim = { duration: 400 };
  const noLegend = { legend: { display: false } };

  // ── Total Load Timeline ───────────────────────────────────────────────
  spanTimelineChart = new Chart(
    document.getElementById('span-timeline-chart').getContext('2d'), {
    type: 'line',
    data: {
      labels: Array(MAX_HIST_5MIN).fill(''),
      datasets: [{ data: Array(MAX_HIST_5MIN).fill(null),
        borderColor: '#00d4ff', backgroundColor: 'rgba(0,212,255,0.13)',
        fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2 }]
    },
    options: { responsive: true, maintainAspectRatio: false, animation: baseAnim,
      scales: { x: { display: false },
                y: { min: 0, grid, ticks: wTick } },
      plugins: { ...noLegend,
        tooltip: { mode: 'index', intersect: false,
          callbacks: { label: ctx => ` ${Math.round(ctx.raw||0)} W total` } } }
    }
  });

  // ── Power Donut ───────────────────────────────────────────────────────
  spanDonutChart = new Chart(
    document.getElementById('span-donut-chart').getContext('2d'), {
    type: 'doughnut',
    data: { labels: [], datasets: [{ data: [],
      backgroundColor: [], borderColor: '#12121a', borderWidth: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: baseAnim,
      cutout: '62%',
      plugins: {
        legend: { display: true, position: 'right',
          labels: { color: 'rgba(255,255,255,0.65)', font: { size: 10 },
                    boxWidth: 10, padding: 5 } },
        tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${Math.round(ctx.raw)} W` } }
      }
    }
  });

  // ── Live Bar Chart ────────────────────────────────────────────────────
  spanBarChart = new Chart(
    document.getElementById('span-bar-chart').getContext('2d'), {
    type: 'bar',
    data: { labels: [], datasets: [{ data: [],
      backgroundColor: [], borderColor: [], borderWidth: 1.5, borderRadius: 5 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: baseAnim,
      indexAxis: 'y',
      scales: {
        x: { min: 0, grid, ticks: { ...wTick, color: 'rgba(255,255,255,0.4)' } },
        y: { grid: { display: false },
             ticks: { color: 'rgba(255,255,255,0.85)', font: { size: 11 } } }
      },
      onClick: (evt, elements) => {
        if (elements.length) selectCircuit(spanBarChart.data.labels[elements[0].index]);
      },
      plugins: { ...noLegend,
        tooltip: { callbacks: { label: ctx => ` ${Math.round(ctx.raw)} W` } }
      }
    }
  });

  // ── Selected Circuit Sparkline (5 min) ───────────────────────────────
  spanSparklineChart = new Chart(
    document.getElementById('span-sparkline-chart').getContext('2d'), {
    type: 'line',
    data: {
      labels: Array(MAX_HIST_5MIN).fill(''),
      datasets: [{ data: Array(MAX_HIST_5MIN).fill(null),
        borderColor: '#00d4ff', backgroundColor: 'rgba(0,212,255,0.15)',
        fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2 }]
    },
    options: { responsive: true, maintainAspectRatio: false, animation: baseAnim,
      scales: { x: { display: false },
                y: { min: 0, grid, ticks: wTick } },
      plugins: { ...noLegend }
    }
  });

  // ── Circuit History — 60-min multi-line ──────────────────────────────
  spanHistoryChart = new Chart(
    document.getElementById('span-history-chart').getContext('2d'), {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: { responsive: true, maintainAspectRatio: false,
      animation: false,   // skip animation on 60-min chart for performance
      scales: {
        x: { grid,
          ticks: { color: 'rgba(255,255,255,0.4)', maxTicksLimit: 8,
                   maxRotation: 0,
                   callback: function(val, idx) {
                     const lbs = this.chart.data.labels;
                     if (!lbs || !lbs.length) return '';
                     const step = Math.max(1, Math.floor(lbs.length / 7));
                     return idx % step === 0 ? lbs[idx] : '';
                   } } },
        y: { min: 0, grid, ticks: wTick }
      },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true, position: 'bottom',
          labels: { color: 'rgba(255,255,255,0.7)', font: { size: 10 },
                    boxWidth: 12, padding: 8, usePointStyle: true, pointStyleWidth: 10 },
          onClick: function(e, item, legend) {
            const ds = legend.chart.data.datasets[item.datasetIndex];
            ds.hidden = !ds.hidden;
            legend.chart.update();
          }
        },
        tooltip: {
          callbacks: {
            label: ctx => ctx.dataset.hidden
              ? null
              : ` ${ctx.dataset.label}: ${Math.round(ctx.raw ?? 0)} W`
          }
        }
      }
    }
  });

  chartsReady = true;

  // Resize charts when SPAN view becomes visible
  const _sv = window.showView;
  if (typeof _sv === 'function') {
    window._spanChartsShowViewHooked = true;
  }
}

function selectCircuit(name) {
  if (!chartsReady) return;
  selectedCircuit = name;
  const hist  = history5.get(name) || [];
  const color = circuitColors.get(name) || '#00d4ff';
  const vals  = hist.filter(v => v > 0);
  document.getElementById('sk-min').textContent = vals.length ? Math.min(...vals) : '—';
  document.getElementById('sk-max').textContent = vals.length ? Math.max(...vals) : '—';
  document.getElementById('sk-avg').textContent = vals.length
    ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : '—';
  document.getElementById('span-sparkline-title').textContent = name + ' — Last 5 min';
  const padded = Array(MAX_HIST_5MIN - hist.length).fill(null).concat(hist);
  spanSparklineChart.data.datasets[0].data            = padded;
  spanSparklineChart.data.datasets[0].borderColor     = color;
  spanSparklineChart.data.datasets[0].backgroundColor = color + '33';
  document.getElementById('span-sparkline-card').style.display = 'block';
  spanSparklineChart.update();
}

function updateSpanCharts(sd) {
  if (typeof Chart === 'undefined') return;
  if (!chartsReady) initSpanCharts();

  const circuits = sd.circuits || [];
  const active   = circuits.filter(c => c.relay === 'CLOSED');
  if (!circuits.length) return;

  // Assign stable colors to every circuit
  circuits.forEach(c => assignColor(c.name));

  const now = new Date();
  const timeLabel = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const totalW = Math.abs(sd.grid_power) ||
                 active.reduce((s, c) => s + (Math.abs(c.power_w) || 0), 0);

  // Accumulate histories
  circuits.forEach(c => {
    if (!history5.has(c.name))  history5.set(c.name, []);
    if (!history60.has(c.name)) history60.set(c.name, []);
    pushCapped(history5.get(c.name),  Math.abs(c.power_w) || 0, MAX_HIST_5MIN);
    pushCapped(history60.get(c.name), Math.abs(c.power_w) || 0, MAX_HIST_60MIN);
  });
  pushCapped(totalHistory5,  totalW,    MAX_HIST_5MIN);
  pushCapped(historyLabels,  timeLabel, MAX_HIST_60MIN);

  // Reveal charts section
  document.getElementById('span-charts').style.display = 'block';

  // Sorted active circuits by power desc
  const sorted = [...active].sort((a, b) => (Math.abs(b.power_w)||0) - (Math.abs(a.power_w)||0));

  // ── Bar chart ──────────────────────────────────────────────────────
  spanBarChart.data.labels = sorted.map(c => c.name);
  spanBarChart.data.datasets[0].data            = sorted.map(c => Math.abs(c.power_w) || 0);
  spanBarChart.data.datasets[0].backgroundColor = sorted.map(c => circuitColors.get(c.name) + 'aa');
  spanBarChart.data.datasets[0].borderColor     = sorted.map(c => circuitColors.get(c.name));
  const barH = Math.max(260, sorted.length * 30);
  document.getElementById('span-bar-container').style.height = barH + 'px';
  spanBarChart.update();

  // ── Timeline ───────────────────────────────────────────────────────
  const tlData = Array(MAX_HIST_5MIN).fill(null);
  totalHistory5.forEach((v, i) => { tlData[MAX_HIST_5MIN - totalHistory5.length + i] = v; });
  spanTimelineChart.data.datasets[0].data = tlData;
  document.getElementById('span-timeline-now').textContent = fmt(totalW);
  spanTimelineChart.update();

  // ── Donut ──────────────────────────────────────────────────────────
  const allSorted = [...circuits].sort((a, b) => (Math.abs(b.power_w)||0) - (Math.abs(a.power_w)||0));
  const top6      = allSorted.slice(0, 6);
  const otherSum  = allSorted.slice(6).reduce((s, c) => s + (Math.abs(c.power_w) || 0), 0);
  const dLabels   = top6.map(c => c.name);
  const dData     = top6.map(c => Math.abs(c.power_w) || 0);
  const dColors   = top6.map(c => circuitColors.get(c.name));
  if (otherSum > 0) { dLabels.push('Other'); dData.push(otherSum); dColors.push('rgba(255,255,255,0.18)'); }
  spanDonutChart.data.labels                       = dLabels;
  spanDonutChart.data.datasets[0].data             = dData;
  spanDonutChart.data.datasets[0].backgroundColor  = dColors;
  document.getElementById('span-donut-total').textContent = fmt(totalW);
  spanDonutChart.update();

  // ── Sparkline (keep live if circuit selected) ──────────────────────
  if (selectedCircuit && history5.has(selectedCircuit)) selectCircuit(selectedCircuit);

  // ── 60-min History multi-line chart ───────────────────────────────
  const top6Names  = new Set(sorted.slice(0, 6).map(c => c.name));
  const labels60   = [...historyLabels];
  const nPts       = labels60.length;

  // Build dataset map from existing (preserve user-toggled hidden state)
  const existingDs = new Map(spanHistoryChart.data.datasets.map(ds => [ds.label, ds]));
  const newDatasets = [];

  for (const [name, hist] of history60.entries()) {
    const color   = circuitColors.get(name);
    const padded  = Array(Math.max(0, nPts - hist.length)).fill(null).concat(hist.slice(-nPts));
    const existing = existingDs.get(name);
    if (existing) {
      existing.data = padded;
      // Preserve user-toggled visibility; don't reset it
      newDatasets.push(existing);
    } else {
      // New circuit: default hidden unless in top 6
      newDatasets.push({
        label: name, data: padded,
        borderColor: color + '99',   // 60% opacity
        backgroundColor: 'transparent',
        tension: 0.3, pointRadius: 0, borderWidth: 1.5,
        hidden: !top6Names.has(name)
      });
    }
  }

  spanHistoryChart.data.labels   = labels60;
  spanHistoryChart.data.datasets = newDatasets;
  spanHistoryChart.update('none');  // no animation = snappy scrolling
}

// ─────────────────────────────────────────────────────────────────────────────

// ══ Camera helpers ════════════════════════════════════════════════════════════
let _camRefreshTimers = {};
let _camDataCache = {};  // mac → cam data for modal

const _FRONT_SIDE_MAC = 'D03F275A9799';

function _getRtspId(cam) {
  const n = (cam.name || '').toLowerCase();
  if (n.includes('upstairs'))   return 'upstairs-cam';    // via docker-wyze-bridge
  if (n.includes('downstairs')) return 'downstairs-cam';  // via docker-wyze-bridge
  if (n.includes('front'))      return 'front-side-cam';  // via docker-wyze-bridge
  return null;
}

function refreshCameraImg(mac) {
  const cam    = _camDataCache[mac];
  const rtspId = cam ? _getRtspId(cam) : null;
  const img    = document.getElementById('cam-img-' + mac);
  if (img) {
    const src = rtspId
      ? '/api/camera/' + rtspId + '/frame?t=' + Date.now()
      : '/api/camera/' + mac + '/snapshot?t=' + Date.now();
    img.src = src;
    // Also refresh modal if this camera is open
    const mImg = document.getElementById('cam-modal-img');
    if (mImg && mImg.dataset.mac === mac) mImg.src = src;
  }
}

function openCameraModal(mac) {
  const cam = _camDataCache[mac];
  if (!cam) return;
  const modal    = document.getElementById('cam-modal');
  const mImg     = document.getElementById('cam-modal-img');
  const mPh      = document.getElementById('cam-modal-placeholder');
  const mTitle   = document.getElementById('cam-modal-title');
  const mBadge   = document.getElementById('cam-modal-badge');
  const mMeta    = document.getElementById('cam-modal-meta');
  const icon     = cam.type === 'wyze' ? '📷' : '🔔';
  const lastInfo = cam.last_motion
    ? 'Last motion: ' + cam.last_motion
    : (cam.last_seen ? 'Last seen: ' + cam.last_seen : '');

  mTitle.textContent = cam.name;
  mBadge.textContent = cam.type || '?';
  mBadge.className   = 'badge ' + (cam.type === 'wyze' ? 'badge-wyze' : 'badge-ring');
  mMeta.textContent  = lastInfo;

  // Load snapshot or MJPEG stream
  mImg.dataset.mac  = mac;
  mImg.style.display = 'none';
  mPh.style.display  = 'flex';
  mPh.innerHTML      = icon;

  const rtspId = _getRtspId(cam);
  const src = rtspId
    ? '/api/camera/' + rtspId + '/mjpeg'
    : '/api/camera/' + mac + '/snapshot?t=' + Date.now();
  mImg.onload  = () => { mImg.style.display='block'; mPh.style.display='none'; };
  mImg.onerror = () => { mImg.style.display='none'; mPh.style.display='flex'; };
  mImg.src = src;

  modal.classList.add('show');
}

function closeCameraModal() {
  const modal = document.getElementById('cam-modal');
  modal.classList.remove('show');
  const mImg = document.getElementById('cam-modal-img');
  if (mImg) { mImg.src = ''; mImg.dataset.mac = ''; }
}

function renderRoku(devices) {
  window._lastRoku = devices;
  const grid = document.getElementById('roku-grid');
  if (!grid) return;
  if (!devices || devices.length === 0) {
    grid.innerHTML = '<div style="color:#888;font-size:0.9rem;">No Roku devices found on network. Discovery runs every 60s.</div>';
    return;
  }
  const BTN = 'min-height:44px;padding:8px 14px;font-size:1rem;border-radius:6px;border:1px solid #444;background:#2a2a3e;color:#fff;cursor:pointer;';
  const APP_BTN = 'min-height:36px;padding:6px 10px;font-size:0.8rem;border-radius:6px;border:1px solid #555;background:#2a2a3e;color:#ccc;cursor:pointer;';
  grid.innerHTML = devices.map(tv => {
    const on = tv.is_on || tv.power === 'PowerOn';
    const dotColor = on ? '#4caf50' : '#555';
    const stateLabel = tv.play_state && tv.play_state !== 'none' ? tv.play_state : (on ? 'on' : tv.power || 'off');

    // Progress bar
    let progressBar = '';
    const pos = parseInt(tv.position_ms) || 0;
    const dur = parseInt(tv.duration_ms) || 0;
    if (pos > 0 && dur > 0) {
      const pct = Math.min(100, Math.round(pos / dur * 100));
      const posStr = Math.floor(pos/1000/60) + ':' + String(Math.floor(pos/1000%60)).padStart(2,'0');
      const durStr = Math.floor(dur/1000/60) + ':' + String(Math.floor(dur/1000%60)).padStart(2,'0');
      progressBar = `<div style="margin-bottom:0.6rem;">
        <div style="background:#333;border-radius:3px;height:4px;overflow:hidden;">
          <div style="background:#7c4dff;width:${pct}%;height:100%;"></div>
        </div>
        <div style="font-size:0.7rem;color:#888;text-align:right;margin-top:2px;">${posStr} / ${durStr}</div>
      </div>`;
    }

    // D-pad
    const dpad = `<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-bottom:0.6rem;max-width:160px;margin-left:auto;margin-right:auto;">
      <div></div>
      <button onclick="rokuKey('${tv.ip}','Up')" style="${BTN}text-align:center;">▲</button>
      <div></div>
      <button onclick="rokuKey('${tv.ip}','Left')" style="${BTN}text-align:center;">◀</button>
      <button onclick="rokuKey('${tv.ip}','Select')" style="${BTN}text-align:center;background:#3a3a5e;">OK</button>
      <button onclick="rokuKey('${tv.ip}','Right')" style="${BTN}text-align:center;">▶</button>
      <div></div>
      <button onclick="rokuKey('${tv.ip}','Down')" style="${BTN}text-align:center;">▼</button>
      <div></div>
    </div>`;

    // Playback row
    const playback = `<div style="display:flex;gap:6px;margin-bottom:0.6rem;flex-wrap:wrap;justify-content:center;">
      <button onclick="rokuKey('${tv.ip}','Rev')" style="${BTN}" title="Rewind">⏮</button>
      <button onclick="rokuKey('${tv.ip}','Play')" style="${BTN}" title="Play/Pause">⏯</button>
      <button onclick="rokuKey('${tv.ip}','Fwd')" style="${BTN}" title="Forward">⏭</button>
      <button onclick="rokuKey('${tv.ip}','Home')" style="${BTN}" title="Home">🏠</button>
      <button onclick="rokuKey('${tv.ip}','Back')" style="${BTN}" title="Back">⬅</button>
      <button onclick="rokuKey('${tv.ip}','Power')" style="${BTN}border-color:#e53935;color:#e53935;" title="Power">⏻</button>
    </div>`;

    // Volume row
    const volume = `<div style="display:flex;gap:6px;margin-bottom:0.75rem;justify-content:center;">
      <button onclick="rokuKey('${tv.ip}','VolumeDown')" style="${BTN}">🔉</button>
      <button onclick="rokuKey('${tv.ip}','VolumeMute')" style="${BTN}">🔇</button>
      <button onclick="rokuKey('${tv.ip}','VolumeUp')" style="${BTN}">🔊</button>
    </div>`;

    // App launchers
    const apps = [
      ['Netflix','rokuLaunch','12','#e50914'],
      ['YouTube','rokuLaunch','195','#ff0000'],
      ['Hulu','rokuLaunch','2285','#3dbb61'],
      ['Disney+','rokuLaunch','291097','#1a78c2'],
      ['Prime','rokuLaunch','13','#00a8e0'],
      ['Peacock','rokuLaunch','593099','#ff7700'],
      ['Tubi','rokuLaunch','41468','#f97316'],
      ['Spotify','rokuLaunch','22297','#1db954'],
      ['Plex','rokuLaunch','13535','#e5a00d'],
    ].map(([lbl,fn,id,col]) =>
      `<button onclick="${fn}('${tv.ip}','${id}')" style="${APP_BTN}border-color:${col};color:${col};">${lbl}</button>`
    ).join('');

    // Input switchers (keypress-based)
    const inputs = [
      ['HDMI 1','InputHDMI1'],
      ['HDMI 2','InputHDMI2'],
      ['HDMI 3','InputHDMI3'],
      ['Antenna','InputATV'],
    ].map(([lbl,key]) =>
      `<button onclick="rokuKey('${tv.ip}','${key}')" style="${APP_BTN}">${lbl}</button>`
    ).join('');

    return `<div style="background:#1a1a2e;border-radius:12px;padding:1.25rem;min-width:280px;flex:1;max-width:420px;border:1px solid #2a2a4e;">
      <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.4rem;">
        <span style="width:12px;height:12px;border-radius:50%;background:${dotColor};display:inline-block;flex-shrink:0;"></span>
        <strong style="font-size:1.05rem;">${tv.name}</strong>
        <span style="margin-left:auto;font-size:0.75rem;color:#888;">${tv.model}</span>
      </div>
      <div style="font-size:0.82rem;color:#aaa;margin-bottom:0.6rem;">${tv.active_app} · <span style="color:${tv.play_state==='play'?'#4caf50':'#888'}">${stateLabel}</span></div>
      ${progressBar}
      ${dpad}
      ${playback}
      ${volume}
      <div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:0.5rem;">${apps}</div>
      <div style="display:flex;gap:5px;flex-wrap:wrap;">${inputs}</div>
    </div>`;
  }).join('');
}
function rokuKey(ip, key) {
  fetch('/api/roku/' + ip + '/keypress/' + key, {method:'POST'})
    .then(r => r.json()).then(d => { if(!d.ok) console.warn('Roku keypress failed'); });
}
function rokuLaunch(ip, appId) {
  fetch('/api/roku/' + ip + '/launch/' + appId, {method:'POST'})
    .then(r => r.json()).then(d => { if(!d.ok) console.warn('Roku launch failed'); });
}

// Roku data comes from SSE state (s.roku) — no separate polling needed

let _camListCache = [];  // Cache previous camera list to detect changes

function renderCameras(cameras) {
  const grid = document.getElementById('camera-grid');
  const setupCard = document.getElementById('cameras-setup-card');
  if (!grid) return;
  if (!cameras || cameras.length === 0) {
    grid.innerHTML = '';
    if (setupCard) setupCard.style.display = 'block';
    _camListCache = [];
    return;
  }
  if (setupCard) setupCard.style.display = 'none';

  // Update cache for modal
  cameras.forEach(cam => { _camDataCache[cam.mac || cam.type] = cam; });

  // Check if camera list actually changed (by MAC/type IDs)
  const currentIds = cameras.map(c => c.mac || c.type).sort().join(',');
  const cachedIds = _camListCache.map(c => c.mac || c.type).sort().join(',');
  const listChanged = currentIds !== cachedIds;

  // Only rebuild HTML if cameras added/removed
  if (listChanged) {
    grid.innerHTML = cameras.map(cam => {
      const mac        = cam.mac || cam.type;
      const badgeClass = cam.type === 'wyze' ? 'badge-wyze' : 'badge-ring';
      const icon       = cam.type === 'wyze' ? '📷' : '🔔';
      const isOnline   = cam.status === 'online';
      const lastInfo   = cam.last_motion
        ? `Last motion: ${cam.last_motion}`
        : (cam.last_seen ? `Last seen: ${cam.last_seen}` : '');
      const liveDot = isOnline ? '<span class="cam-live-dot" title="Live"></span>' : '';
      const statusBadge = `<span id="cam-status-${mac}" class="badge ${isOnline?'online':'offline'}">${cam.status||'?'}</span>`;
      const rtspId    = _getRtspId(cam);
      const isFront   = mac === _FRONT_SIDE_MAC;

      let thumbHtml, sourceBadge;
      if (rtspId) {
        // Live HLS video via MediaMTX — iframe src set lazily to avoid blocking page load
        thumbHtml = `<iframe id="cam-stream-${mac}" 
             class="camera-thumb" 
             style="border:none;background:#000"
             allow="autoplay"
             sandbox="allow-scripts allow-same-origin"
             data-cam-src="http://${window.location.hostname}:8888/${rtspId}/"></iframe>`;
        sourceBadge = `<span class="badge" style="background:rgba(0,255,128,.15);color:#00ff80;margin-right:6px">🔴 LIVE VIDEO</span>`;
      } else if (isFront) {
        // No RTSP — snapshot with fast refresh every 5s
        thumbHtml = `<img id="cam-img-${mac}" class="camera-thumb"
             src="/api/camera/${mac}/snapshot?t=${Date.now()}"
             onerror="this.style.display='none';document.getElementById('cam-ph-${mac}').style.display='flex'"
             onload="document.getElementById('cam-ph-${mac}').style.display='none';this.style.display='block'"
             alt="${cam.name}">
        <div id="cam-ph-${mac}" class="camera-thumb-placeholder" style="display:none">${icon}<div style="font-size:10px;color:var(--text-dim)">No snapshot</div></div>`;
        sourceBadge = `<span class="badge" style="background:rgba(255,165,0,.15);color:orange;margin-right:6px">Snapshot (no RTSP)</span>`;
      } else {
        thumbHtml = `<img id="cam-img-${mac}" class="camera-thumb"
             src="/api/camera/${mac}/snapshot?t=${Date.now()}"
             onerror="this.style.display='none';document.getElementById('cam-ph-${mac}').style.display='flex'"
             onload="document.getElementById('cam-ph-${mac}').style.display='none';this.style.display='block'"
             alt="${cam.name}">
        <div id="cam-ph-${mac}" class="camera-thumb-placeholder" style="display:flex">${icon}<div style="font-size:10px;color:var(--text-dim)">No snapshot</div></div>`;
        sourceBadge = `<span class="badge ${badgeClass}" style="margin-right:6px">${cam.type||'?'}</span>`;
      }

      return `<div class="camera-card" onclick="openCameraModal('${mac}')">
        ${thumbHtml}
        <div class="camera-info">
          <div class="camera-name" id="cam-name-${mac}">
            <span>${liveDot}${cam.name}</span>
            ${statusBadge}
          </div>
          <div class="camera-meta" id="cam-meta-${mac}">
            ${sourceBadge}${lastInfo}
          </div>
        </div>
      </div>`;
    }).join('');

    _camListCache = cameras;  // Update cache

    // Setup refresh timers for non-streaming cameras; lazy-load HLS iframes after page settles
    cameras.forEach(cam => {
      const mac    = cam.mac || cam.type;
      const rtspId = _getRtspId(cam);
      if (rtspId) {
        // Lazy-load HLS iframe: set src after DOM is ready so page doesn't show loading spinner
        const iframe = document.getElementById('cam-stream-' + mac);
        if (iframe && !iframe.src.includes('8888')) {
          setTimeout(() => { iframe.src = iframe.dataset.camSrc; }, 500);
        }
      } else if (!_camRefreshTimers[mac]) {
        const interval = 30000;  // 30s for snapshots
        _camRefreshTimers[mac] = setInterval(() => refreshCameraImg(mac), interval);
      }
    });

    // Cancel timers for cameras that disappeared
    Object.keys(_camRefreshTimers).forEach(mac => {
      if (!cameras.some(c => (c.mac || c.type) === mac)) {
        clearInterval(_camRefreshTimers[mac]);
        delete _camRefreshTimers[mac];
      }
    });
  } else {
    // List didn't change — just update status badges and metadata (no DOM rebuild)
    cameras.forEach(cam => {
      const mac = cam.mac || cam.type;
      const isOnline = cam.status === 'online';
      const statusBadge = document.getElementById('cam-status-' + mac);
      if (statusBadge) {
        statusBadge.textContent = cam.status || '?';
        statusBadge.className = 'badge ' + (isOnline ? 'online' : 'offline');
      }
      const metaEl = document.getElementById('cam-meta-' + mac);
      if (metaEl) {
        const lastInfo = cam.last_motion ? `Last motion: ${cam.last_motion}` : (cam.last_seen ? `Last seen: ${cam.last_seen}` : '');
        const rtspId = _getRtspId(cam);
        const isFront = mac === _FRONT_SIDE_MAC;
        const badgeClass = cam.type === 'wyze' ? 'badge-wyze' : 'badge-ring';
        let sourceBadge;
        if (rtspId) {
          sourceBadge = `<span class="badge" style="background:rgba(0,255,128,.15);color:#00ff80;margin-right:6px">LIVE</span>`;
        } else if (isFront) {
          sourceBadge = `<span class="badge" style="background:rgba(255,165,0,.15);color:orange;margin-right:6px">Snapshot (no RTSP)</span>`;
        } else {
          sourceBadge = `<span class="badge ${badgeClass}" style="margin-right:6px">${cam.type||'?'}</span>`;
        }
        metaEl.innerHTML = sourceBadge + lastInfo;
      }
    });
  }
}

// ══ Nest helpers ══════════════════════════════════════════════════════════════
let _nestSetpoints = {};  // device_name → {heat_f, cool_f, mode}

function nestAdjust(delta, deviceName, which) {
  // which = 'heat' or 'cool'
  const sp = _nestSetpoints[deviceName] || {heat_f: 68, cool_f: 74, mode: 'HEATCOOL'};
  if (which === 'cool') sp.cool_f = Math.round((sp.cool_f || 74) + delta);
  else sp.heat_f = Math.round((sp.heat_f || 68) + delta);
  // Enforce min gap of 2°F between heat and cool
  if (sp.cool_f - sp.heat_f < 2) {
    if (which === 'cool') sp.heat_f = sp.cool_f - 2;
    else sp.cool_f = sp.heat_f + 2;
  }
  _nestSetpoints[deviceName] = sp;
  const safeId = deviceName.replace(/[^a-z0-9]/gi, '_');
  const heatEl = document.getElementById('nest-sp-heat-' + safeId);
  const coolEl = document.getElementById('nest-sp-cool-' + safeId);
  if (heatEl) heatEl.textContent = sp.heat_f;
  if (coolEl) coolEl.textContent = sp.cool_f;

  const body = sp.mode === 'HEATCOOL'
    ? {device_name: deviceName, cool_f: sp.cool_f, heat_f: sp.heat_f}
    : which === 'cool'
      ? {device_name: deviceName, cool_f: sp.cool_f}
      : {device_name: deviceName, heat_f: sp.heat_f};

  fetch('/api/nest/setpoint', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body)
  }).then(r=>r.json()).then(d => {
    if (d.ok) toast('&#10003; Range ' + sp.heat_f + '&#8211;' + sp.cool_f + '&#xB0;F');
    else toast('&#10007; ' + (d.error||'Error'), 5000);
  }).catch(e => toast('&#10007; ' + e, 5000));
}

function renderNest(nest) {
  const badge        = document.getElementById('nest-badge');
  const cockpitBadge = document.getElementById('nest-cockpit-badge');
  const cfgBadge     = document.getElementById('nest-cfg-badge');
  const setupMsg     = document.getElementById('nest-setup-msg');
  const container    = document.getElementById('nest-cards-container');
  const cockpitContent = document.getElementById('nest-cockpit-content');
  const modeMap = { HEAT: 'online', COOL: 'partial', HEATCOOL: 'warning', OFF: 'offline' };
  const hvacMap = { HEATING: 'online', COOLING: 'partial', OFF: 'offline' };

  if (!nest) return;
  const status = nest.status || 'unconfigured';
  const isOnline = status === 'online';

  if (badge)        { badge.textContent = status;  badge.className = 'badge ' + statusColor(status); }
  if (cockpitBadge) { cockpitBadge.textContent = status; cockpitBadge.className = 'badge ' + statusColor(status); }
  if (cfgBadge)     { cfgBadge.textContent = status;     cfgBadge.className = 'badge ' + statusColor(status); }
  if (setupMsg)     setupMsg.style.display = isOnline ? 'none' : 'block';
  if (container)    container.style.display = isOnline ? 'flex' : 'none';

  if (!isOnline) {
    if (cockpitContent) cockpitContent.innerHTML = `<div style="color:var(--text-dim);font-size:11px">${status} — click to configure</div>`;
    return;
  }

  const thermostats = nest.thermostats || [];

  // Build cockpit summary (all thermostats inline)
  if (cockpitContent) {
    cockpitContent.innerHTML = thermostats.map(t => `
      <div style="display:flex;gap:10px;align-items:center;margin-right:16px">
        <div><div class="sub-val">${t.name}</div><div class="nest-cockpit-temp">${Math.round(t.temp_f)}°</div></div>
        <div><div class="sub-val">Set</div><div style="font-size:15px;font-weight:600">${Math.round(t.cool_setpoint_f||t.heat_setpoint_f||0)}°</div></div>
        <span class="badge ${hvacMap[t.hvac_state]||'offline'}" style="font-size:10px">${t.hvac_state||'OFF'}</span>
      </div>`).join('');
  }

  // Build one card per thermostat
  if (container) {
    container.innerHTML = thermostats.map(t => {
      const safeId   = t.device_name.replace(/[^a-z0-9]/gi, '_');
      if (!_nestSetpoints[t.device_name]) _nestSetpoints[t.device_name] = {
        heat_f: Math.round(t.heat_setpoint_f || 68),
        cool_f: Math.round(t.cool_setpoint_f || 74),
        mode: t.mode
      };
      const sp     = _nestSetpoints[t.device_name];
      // Keep mode fresh from server
      sp.mode = t.mode;
      const devEnc = encodeURIComponent(t.device_name).replace(/'/g, '%27');
      const isRange = t.mode === 'HEATCOOL';
      return `
      <div class="card" style="min-width:280px;flex:1">
        <div class="card-header">
          <span class="card-title">&#x1F321;&#xFE0F; ${t.name}</span>
          <span class="badge ${statusColor(t.status)}">${t.status}</span>
        </div>
        <div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-end;margin-bottom:14px">
          <div>
            <div class="sub-val">Current Temp</div>
            <div class="big-val c-pool" style="font-size:36px">${Math.round(t.temp_f)}<span class="big-unit">&#xB0;F</span></div>
          </div>
          <div>
            <div class="sub-val">Setpoint Range</div>
            <div style="display:flex;flex-direction:column;gap:6px;margin-top:4px">
              ${isRange ? `
              <div style="display:flex;align-items:center;gap:6px">
                <span style="font-size:10px;color:var(--text-dim);width:32px">HEAT</span>
                <button class="btn" onclick="nestAdjust(-1, decodeURIComponent('${devEnc}'), 'heat')" style="font-size:14px;padding:2px 10px">&#8722;</button>
                <span id="nest-sp-heat-${safeId}" style="font-size:20px;font-weight:600;min-width:28px;text-align:center">${sp.heat_f}</span>
                <button class="btn" onclick="nestAdjust(1, decodeURIComponent('${devEnc}'), 'heat')" style="font-size:14px;padding:2px 10px">+</button>
                <span style="font-size:11px;color:var(--text-dim)">&#xB0;F</span>
              </div>` : ''}
              <div style="display:flex;align-items:center;gap:6px">
                <span style="font-size:10px;color:var(--text-dim);width:32px">COOL</span>
                <button class="btn" onclick="nestAdjust(-1, decodeURIComponent('${devEnc}'), 'cool')" style="font-size:14px;padding:2px 10px">&#8722;</button>
                <span id="nest-sp-cool-${safeId}" style="font-size:20px;font-weight:600;min-width:28px;text-align:center">${sp.cool_f}</span>
                <button class="btn" onclick="nestAdjust(1, decodeURIComponent('${devEnc}'), 'cool')" style="font-size:14px;padding:2px 10px">+</button>
                <span style="font-size:11px;color:var(--text-dim)">&#xB0;F</span>
              </div>
            </div>
          </div>
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <div><div class="sub-val">Mode</div><span class="badge ${modeMap[t.mode]||'offline'}">${t.mode||'OFF'}</span></div>
          <div><div class="sub-val">HVAC</div><span class="badge ${hvacMap[t.hvac_state]||'offline'}">${t.hvac_state||'OFF'}</span></div>
          <div><div class="sub-val">Humidity</div><span style="font-size:13px;font-weight:600">${t.humidity}%</span></div>
        </div>
      </div>`;
    }).join('');
  }
}

// ══ B-Hyve Sprinkler helpers ══════════════════════════════════════════════════
let _bhyveModalZoneId = null;
let _bhyveModalDeviceId = null;
let _bhyveModalDur = 10;
let _bhyveZoneCountdowns = {};   // zoneKey → {remaining, interval}
let _bhyveState = null;

function bhyveZoneKey(deviceId, zoneId) { return deviceId + ':' + zoneId; }

function selectDur(btn, min) {
  document.querySelectorAll('.dur-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
  _bhyveModalDur = min;
}

function openBhyveModal(deviceId, zoneId, zoneName) {
  _bhyveModalDeviceId = deviceId;
  _bhyveModalZoneId   = zoneId;
  _bhyveModalDur      = 10;
  document.getElementById('bhyve-modal-title').textContent = '▶ Run: ' + zoneName;
  document.querySelectorAll('.dur-btn').forEach((b,i) => b.classList.toggle('selected', i===1));
  document.getElementById('bhyve-modal').classList.add('show');
}

function closeBhyveModal() {
  document.getElementById('bhyve-modal').classList.remove('show');
}

function confirmBhyveRun() {
  if (!_bhyveModalDeviceId) return;
  closeBhyveModal();
  fetch('/api/bhyve/run', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({device_id: _bhyveModalDeviceId, zone_id: _bhyveModalZoneId, minutes: _bhyveModalDur})
  }).then(r=>r.json()).then(d => {
    if (d.ok) toast('✓ Zone started for ' + _bhyveModalDur + ' min');
    else toast('✗ ' + (d.error||'Error'), 5000);
  }).catch(e => toast('✗ ' + e, 5000));
}

function bhyveStop(deviceId) {
  fetch('/api/bhyve/stop', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({device_id: deviceId})
  }).then(r=>r.json()).then(d => {
    if (d.ok) toast('✓ Sprinkler stopped');
    else toast('✗ ' + (d.error||'Error'), 5000);
  }).catch(e => toast('✗ ' + e, 5000));
}

function bhyveRunAll() {
  if (!_bhyveState || !_bhyveState.zones || !_bhyveState.zones.length) return;
  const zone = _bhyveState.zones[0];
  openBhyveModal(zone.device_id, zone.zone_id, 'All Zones (sequential)');
}

function saveBhyveQuick() {
  const email = document.getElementById('bhyve-quick-email').value.trim();
  const pw    = document.getElementById('bhyve-quick-password').value.trim();
  const statusEl = document.getElementById('bhyve-quick-status');
  if (!email || !pw) { toast('Enter email and password'); return; }
  statusEl.textContent = 'Saving…';
  fetch('/api/settings/bhyve', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password:pw})})
    .then(r=>r.json()).then(d => {
      statusEl.textContent = d.ok ? '✓ Saved — polling…' : ('✗ ' + (d.error||'Error'));
      statusEl.style.color = d.ok ? 'var(--online)' : 'var(--error)';
      if (d.ok) toast('✓ B-Hyve credentials saved');
    }).catch(e => { statusEl.textContent = '✗ ' + e; statusEl.style.color = 'var(--error)'; });
}

function startZoneCountdown(key, remainingSecs) {
  if (_bhyveZoneCountdowns[key]) {
    clearInterval(_bhyveZoneCountdowns[key].interval);
  }
  let rem = Math.max(0, remainingSecs);
  const update = () => {
    const el = document.getElementById('countdown-' + key);
    if (!el) { clearInterval(_bhyveZoneCountdowns[key]?.interval); return; }
    const m = Math.floor(rem / 60);
    const s = rem % 60;
    el.textContent = m + ':' + String(s).padStart(2,'0');
    if (rem <= 0) clearInterval(_bhyveZoneCountdowns[key]?.interval);
    else rem--;
  };
  update();
  _bhyveZoneCountdowns[key] = { remaining: rem, interval: setInterval(update, 1000) };
}

function renderBhyve(bhyve) {
  if (!bhyve) return;
  _bhyveState = bhyve;
  const status = bhyve.status || 'unconfigured';
  const badge = document.getElementById('bhyve-badge');
  const cfgBadge = document.getElementById('bhyve-cfg-badge');
  if (badge)    { badge.textContent = status; badge.className = 'badge ' + statusColor(status); }
  if (cfgBadge) { cfgBadge.textContent = status; cfgBadge.className = 'badge ' + statusColor(status); }

  const setupCard   = document.getElementById('bhyve-setup-card');
  const devInfo     = document.getElementById('bhyve-device-info');
  const zonesSection = document.getElementById('bhyve-zones-section');

  const isOnline = status === 'online';
  if (setupCard)    setupCard.style.display    = isOnline ? 'none' : 'block';
  if (devInfo)      devInfo.style.display      = isOnline ? 'block' : 'none';
  if (zonesSection) zonesSection.style.display = isOnline ? 'block' : 'none';

  if (!isOnline) return;

  // Render devices
  const devList = document.getElementById('bhyve-devices-list');
  if (devList) {
    devList.innerHTML = (bhyve.devices || []).map(d => `
      <div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--border)">
        <span style="font-size:18px">💧</span>
        <div style="flex:1">
          <div style="font-weight:700;font-size:13px">${d.name||'Controller'}</div>
          <div style="font-size:10px;color:var(--text-dim)">FW ${d.firmware||'?'} · ${d.type||'sprinkler'} · Mode: ${d.run_mode||'?'}</div>
        </div>
        <span class="badge ${d.connected ? 'online' : 'offline'}">${d.connected ? 'connected' : 'offline'}</span>
      </div>
    `).join('') || '<div style="color:var(--text-dim);font-size:11px">No devices found</div>';
  }

  // Render zones
  const zoneGrid = document.getElementById('bhyve-zone-grid');
  if (!zoneGrid) return;
  const zones = bhyve.zones || [];
  if (!zones.length) {
    zoneGrid.innerHTML = '<div style="color:var(--text-dim);font-size:12px">No zones found — check credentials</div>';
    return;
  }

  zoneGrid.innerHTML = zones.map(z => {
    const key = bhyveZoneKey(z.device_id, z.zone_id);
    const isRunning = z.is_running;
    const statusBadge = isRunning
      ? '<span class="badge badge-running">RUNNING</span>'
      : (z.next_run ? '<span class="badge badge-scheduled">SCHEDULED</span>' : '<span class="badge offline">IDLE</span>');
    const countdownHtml = isRunning
      ? `<div class="zone-countdown" id="countdown-${key}">—:—</div>`
      : '';
    const nextHtml = z.next_run
      ? `<div class="zone-next">Next: ${z.next_run}</div>`
      : '<div class="zone-next">No schedule</div>';
    const stopBtn = isRunning
      ? `<button class="btn-stop" onclick="bhyveStop('${z.device_id}')">⏹ Stop</button>`
      : '';
    return `
      <div class="zone-tile ${isRunning ? 'running' : ''}">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
          <div class="zone-name">${z.name}</div>
          ${statusBadge}
        </div>
        ${countdownHtml}
        ${nextHtml}
        <div class="zone-btns">
          <button class="btn-run" onclick="openBhyveModal('${z.device_id}',${z.zone_id},'${z.name.replace(/'/g,"\\'")}')">▶ Run</button>
          ${stopBtn}
        </div>
      </div>`;
  }).join('');

  // Start countdowns for running zones
  zones.filter(z => z.is_running).forEach(z => {
    const key = bhyveZoneKey(z.device_id, z.zone_id);
    startZoneCountdown(key, z.remaining_s || 0);
  });
  // Stop timers for zones that stopped running
  Object.keys(_bhyveZoneCountdowns).forEach(key => {
    const stillRunning = zones.some(z => z.is_running && bhyveZoneKey(z.device_id, z.zone_id) === key);
    if (!stillRunning && _bhyveZoneCountdowns[key]) {
      clearInterval(_bhyveZoneCountdowns[key].interval);
      delete _bhyveZoneCountdowns[key];
    }
  });
}

// ══ GE SmartHQ Appliances ══════════════════════════════════════════════════════
const GE_STATE_LABELS = {
  'idle': 'Idle', 'running': 'Running', 'paused': 'Paused',
  'end of cycle': 'End of Cycle', 'delay start': 'Delay Start',
  'disconnected': 'Disconnected', 'standby': 'Standby',
  'downloading': 'Downloading', 'remote start': 'Remote Start',
  'Door Open': '🚪 Door Open', 'Online': 'Online',
};
const GE_STATE_COLORS = {
  'running': '#10b981', 'end of cycle': '#f59e0b',
  'paused': '#f59e0b', 'delay start': '#f59e0b',
  'idle': 'var(--text-dim)', 'standby': 'var(--text-dim)',
  'disconnected': 'var(--offline)', 'downloading': 'var(--solar)',
  'remote start': '#6366f1',
  'Door Open': '#f59e0b', 'Online': '#10b981',
};
// Appliance types that support cycle-stop command
const GE_CONTROLLABLE_TYPES = new Set(['Washer','Clothes Washer','Dryer','Clothes Dryer','WashDryer','Dishwasher']);

function _geStateAge(changedAt) {
  if (!changedAt) return '';
  const secs = Math.floor(Date.now() / 1000 - changedAt);
  if (secs < 5) return 'just now';
  if (secs < 60) return secs + 's in state';
  if (secs < 3600) return Math.floor(secs / 60) + 'm in state';
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
  return h + 'h ' + (m > 0 ? m + 'm ' : '') + 'in state';
}

function _geLastSeen(ts) {
  if (!ts) return '';
  const secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 10) return 'just now';
  if (secs < 60) return secs + 's ago';
  if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
  return Math.floor(secs / 3600) + 'h ago';
}

function _geSecs2Str(secs) {
  if (!secs || secs <= 0) return '';
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return h > 0 ? h + 'h ' + m + 'm' : m + 'm';
}

function geForceRefresh() {
  const btn = document.getElementById('ge-refresh-btn');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }
  fetch('/api/ge/refresh', {method:'POST'})
    .then(r => r.json())
    .then(d => { if (d.ok) toast('GE: refresh queued'); })
    .catch(() => {})
    .finally(() => {
      setTimeout(() => {
        if (btn) { btn.disabled = false; btn.textContent = '\u21bb Refresh'; }
      }, 3000);
    });
}

function geApplCommand(aid, appType, action) {
  // Map action → ERD attribute + value (v1 attribute endpoint)
  // ERD 0x0317 = operation state: 00=stop, 02=pause, 03=resume, 07=remote-start
  const cmds = {
    'stop_washer':    {attribute: '0x0317', value: '00'},
    'stop_dryer':     {attribute: '0x0317', value: '00'},
    'stop_dish':      {attribute: '0x0317', value: '00'},
    'pause_washer':   {attribute: '0x0317', value: '02'},
    'pause_dryer':    {attribute: '0x0317', value: '02'},
    'pause_dish':     {attribute: '0x0317', value: '02'},
    'resume_washer':  {attribute: '0x0317', value: '03'},
    'resume_dryer':   {attribute: '0x0317', value: '03'},
    'resume_dish':    {attribute: '0x0317', value: '03'},
    'remote_start':   {attribute: '0x0317', value: '07'},
  };
  const cmd = cmds[action];
  if (!cmd) { toast('Unknown command: ' + action); return; }
  const btn = event && event.target;
  if (btn) btn.disabled = true;
  fetch('/api/ge/appliance/' + encodeURIComponent(aid) + '/command', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(cmd)
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      toast(appType + ': ' + action.replace(/_/g,' ') + ' sent');
    } else {
      const detail = d.detail || d.error || 'Unknown error';
      toast('Command failed: ' + detail.slice(0, 80));
      if (btn) btn.disabled = false;
    }
  }).catch(e => { toast('Command error: ' + e); if (btn) btn.disabled = false; });
}

function geFridgeToggle(did, controlType, enable) {
  // Send v2 Digital Twin service toggle for fridge controls
  const svcMap = {
    'turbo_cool': {
      serviceType:       'cloud.smarthq.service.toggle',
      domainType:        'cloud.smarthq.domain.turbo',
      serviceDeviceType: 'cloud.smarthq.device.freshfood',
    },
    'turbo_freeze': {
      serviceType:       'cloud.smarthq.service.toggle',
      domainType:        'cloud.smarthq.domain.turbo',
      serviceDeviceType: 'cloud.smarthq.device.freezer',
    },
    'icemaker': {
      serviceType:       'cloud.smarthq.service.toggle',
      domainType:        'cloud.smarthq.domain.power',
      serviceDeviceType: 'cloud.smarthq.device.icemaker.freezer',
    },
  };
  const svc = svcMap[controlType];
  if (!svc) { toast('Unknown fridge control: ' + controlType); return; }
  fetch('/api/ge/appliance/' + encodeURIComponent(did) + '/v2service', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(Object.assign({}, svc, {state: {on: enable}}))
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      toast(controlType.replace(/_/g,' ') + ' ' + (enable ? 'on' : 'off'));
      setTimeout(() => fetch('/api/ge/refresh', {method:'POST'}), 2500);
    } else {
      toast('Fridge control failed: ' + (d.detail || d.error || 'err').slice(0, 80));
    }
  }).catch(e => toast('Fridge control error: ' + e));
}

function renderAppliances(ge) {
  if (!ge) return;
  const status = ge.status || 'unconfigured';
  const appliances = ge.appliances || [];

  // Header card badge
  const badge = document.getElementById('ge-badge');
  if (badge) { badge.textContent = status; badge.className = 'badge ' + statusColor(status); }
  const uncfgMsg   = document.getElementById('ge-unconfigured-msg');
  const errMsg     = document.getElementById('ge-error-msg');
  const statusLine = document.getElementById('ge-status-line');
  if (uncfgMsg)   uncfgMsg.style.display   = status === 'unconfigured' ? '' : 'none';
  if (errMsg)     errMsg.style.display     = status === 'error' ? '' : 'none';
  if (statusLine) statusLine.style.display = status === 'online' ? '' : 'none';

  // Summary strip
  const strip = document.getElementById('ge-summary-strip');
  if (strip) strip.style.display = status === 'online' ? 'block' : 'none';
  if (status === 'online') {
    const running = appliances.filter(a => a.state === 'running');
    const totalW  = running.reduce((s, a) => s + (a.est_watts || 0), 0);
    const totalCycles = appliances.reduce((s, a) => s + (a.cycles_today || 0), 0);
    const $e = id => document.getElementById(id);
    if ($e('ge-sum-total'))   $e('ge-sum-total').textContent   = appliances.length;
    if ($e('ge-sum-running')) $e('ge-sum-running').textContent = running.length;
    if ($e('ge-sum-watts'))   $e('ge-sum-watts').textContent   = totalW >= 1000 ? (totalW/1000).toFixed(1)+' kW' : totalW+' W';
    if ($e('ge-sum-cycles'))  $e('ge-sum-cycles').textContent  = totalCycles;
    if ($e('ge-sum-lastseen')) $e('ge-sum-lastseen').textContent = ge.last_seen ? 'Updated ' + _geLastSeen(ge.last_seen) : '';
  }

  // Count chip
  const countEl = document.getElementById('ge-online-count');
  if (countEl && status === 'online') {
    const nRun = appliances.filter(a => a.state === 'running').length;
    countEl.textContent = appliances.length + ' appliance' + (appliances.length !== 1 ? 's' : '') +
      (nRun ? ' \xb7 ' + nRun + ' running' : '');
  } else if (countEl) countEl.textContent = '';

  const grid = document.getElementById('ge-appliance-grid');
  if (!grid) return;
  if (!appliances.length) {
    grid.innerHTML = status === 'online'
      ? '<div style="color:var(--text-dim);font-size:13px;grid-column:1/-1">No appliances found on this account.</div>'
      : '';
    return;
  }

  // Sort: running > paused/eoc > active-states > idle > disconnected
  const stOrd = {'running':0,'paused':1,'end of cycle':1,'delay start':2,'remote start':2,
                  'downloading':2,'Door Open':3,'Online':4,'idle':4,'standby':4,'disconnected':5};
  const sorted = [...appliances].sort((a,b) => (stOrd[a.state]??4) - (stOrd[b.state]??4));
  const nowSec = Date.now() / 1000;
  grid.innerHTML = sorted.map(a => _geRenderCard(a, nowSec)).join('');
}

function _geRenderCard(a, nowSec) {
  const stLabel    = GE_STATE_LABELS[a.state] || a.state || 'Unknown';
  const stColor    = GE_STATE_COLORS[a.state] || 'var(--text-dim)';
  const isRunning  = a.state === 'running';
  const isPaused   = a.state === 'paused';
  const isEOC      = a.state === 'end of cycle';
  const isDoorOpen = a.state === 'Door Open';
  const isOffline  = a.state === 'disconnected';
  const isActive   = isRunning || isPaused || isEOC;
  const isLaundry  = GE_CONTROLLABLE_TYPES.has(a.type);
  const isFridge   = a.type === 'Refrigerator' || a.type === 'Freezer';
  const typeKey    = a.type.includes('Dish') ? 'dish' : (a.type.includes('Dry') ? 'dryer' : 'washer');

  // Visual treatment
  let borderCol = 'var(--border)', cardBg = '';
  if      (isRunning)              { borderCol = 'rgba(16,185,129,0.45)'; cardBg = 'rgba(16,185,129,0.025)'; }
  else if (isPaused || isEOC)      { borderCol = 'rgba(245,158,11,0.45)'; cardBg = 'rgba(245,158,11,0.025)'; }
  else if (isDoorOpen)             { borderCol = 'rgba(245,158,11,0.3)'; }
  const dotCls    = isRunning ? 'online' : (isPaused||isEOC||isDoorOpen ? 'warning' : (isOffline ? 'offline' : 'dim'));
  const runClass  = isRunning ? ' ge-card-running' : '';
  const iconGlow  = isRunning ? 'filter:drop-shadow(0 0 10px rgba(16,185,129,0.55))' : '';

  // Status badge (pulse dot when running)
  const dotAnim = isRunning ? 'animation:ge-dot-pulse 1.5s ease-in-out infinite' : '';
  const stBadge = `<span style="display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;background:${stColor}1a;color:${stColor};border:1px solid ${stColor}33">
    <span class="dev-sdot ${dotCls}" style="width:5px;height:5px;margin:0;${dotAnim}"></span>${stLabel}
  </span>`;

  // State age
  const ageStr = isActive ? _geStateAge(a.state_changed_at) : '';

  // ── Progress bar ──────────────────────────────────────────────────────────
  let progressHtml = '';
  const secsLeft = a.seconds_remaining || 0;
  if (isRunning) {
    if (secsLeft > 0 && a.cycle_started > 0) {
      const elapsed = nowSec - a.cycle_started;
      const total   = elapsed + secsLeft;
      const pct     = total > 0 ? Math.min(99, Math.round(elapsed / total * 100)) : 0;
      const remLbl  = _geSecs2Str(secsLeft);
      progressHtml = `<div style="margin:8px 0 2px">
  <div class="ge-progress-bar"><div class="ge-progress-fill" style="width:${pct}%"></div></div>
  <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-dim);margin-top:2px">
    <span>${pct}% complete</span><span>${remLbl} remaining</span>
  </div>
</div>`;
    } else if (secsLeft > 0) {
      const remLbl = _geSecs2Str(secsLeft);
      progressHtml = `<div style="margin:8px 0 2px">
  <div class="ge-progress-bar"><div class="ge-progress-indet"></div></div>
  <div style="font-size:10px;color:var(--text-dim);margin-top:2px;text-align:right">${remLbl} remaining</div>
</div>`;
    } else {
      progressHtml = `<div style="margin:8px 0 4px"><div class="ge-progress-bar"><div class="ge-progress-indet"></div></div></div>`;
    }
  }

  // ── Cycle label ───────────────────────────────────────────────────────────
  let cycleHtml = '';
  if (a.cycle && isActive) {
    cycleHtml = `<div style="font-size:12px;font-weight:600;color:var(--text);margin-top:4px">${a.cycle}</div>`;
  }

  // ── Temp (fridge) ─────────────────────────────────────────────────────────
  let tempHtml = '';
  if (a.temp) {
    // Split multi-part fridge temp into visual chips
    const parts = a.temp.split(' | ');
    if (parts.length > 1) {
      const chips = parts.map(p => {
        const isFreezer = p.toLowerCase().includes('freezer');
        const c = isFreezer ? '#38bdf8' : '#10b981';
        return `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;background:${c}12;border:1px solid ${c}33;border-radius:10px;font-size:11px;font-weight:600;color:${c}">${p}</span>`;
      }).join('');
      tempHtml = `<div style="display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 4px">${chips}</div>`;
    } else {
      tempHtml = `<div style="font-size:12px;color:#38bdf8;margin:6px 0 2px">&#10052; ${a.temp}</div>`;
    }
  }

  // ── Energy estimate ───────────────────────────────────────────────────────
  let energyHtml = '';
  if (isRunning && a.est_watts > 0) {
    const wStr = a.est_watts >= 1000 ? (a.est_watts/1000).toFixed(1)+' kW' : a.est_watts+' W';
    energyHtml = `<div style="display:inline-flex;align-items:center;gap:6px;padding:4px 12px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.22);border-radius:12px;font-size:11px;color:#10b981;margin:4px 0">
  &#9889; ~${wStr} <span style="color:var(--text-dim);font-weight:400">est. draw</span>
</div>`;
  }

  // ── Cycle stats (idle only) ───────────────────────────────────────────────
  let statsHtml = '';
  if (!isRunning && !isOffline && (a.cycles_today > 0 || a.last_cycle_end > 0)) {
    const parts = [];
    if (a.cycles_today > 0) parts.push(`${a.cycles_today} cycle${a.cycles_today !== 1 ? 's' : ''} today`);
    if (a.daily_runtime_mins > 0) parts.push(`${a.daily_runtime_mins}m runtime`);
    if (a.last_cycle_end > 0) {
      const ago = nowSec - a.last_cycle_end;
      const agoStr = ago < 60 ? 'just now' : (ago < 3600 ? Math.floor(ago/60)+'m ago' : Math.floor(ago/3600)+'h ago');
      parts.push('Last: ' + agoStr);
    }
    if (parts.length) {
      statsHtml = `<div style="font-size:11px;color:var(--text-dim);margin:6px 0 2px;padding:5px 10px;background:rgba(167,139,250,0.06);border:1px solid rgba(167,139,250,0.15);border-radius:6px">
  &#128260; ${parts.join(' \xb7 ')}
</div>`;
    }
  }

  // ── Alert attrs ───────────────────────────────────────────────────────────
  const attrs = a.attrs || [];
  const _isAlert    = x => !!(x.label && x.label.includes('Alert'));
  const alertAttrs  = attrs.filter(_isAlert);
  const normalAttrs = attrs.filter(x => !_isAlert(x));

  let alertHtml = '';
  if (alertAttrs.length) {
    alertHtml = '<div style="margin:6px 0">' + alertAttrs.map(at =>
      `<div style="display:flex;align-items:center;gap:6px;padding:5px 10px;background:rgba(239,68,68,0.09);border:1px solid rgba(239,68,68,0.22);border-radius:6px;font-size:11px;color:#ef4444;margin:3px 0">${at.value}</div>`
    ).join('') + '</div>';
  }

  // ── Attribute display ─────────────────────────────────────────────────────
  let attrHtml = '';
  if (normalAttrs.length) {
    if (isActive) {
      // Pill style for running/paused
      attrHtml = '<div style="display:flex;flex-wrap:wrap;margin:6px 0 2px">' +
        normalAttrs.map(at => {
          const val = at.unit ? `${at.value}\u202F${at.unit}` : at.value;
          return `<span class="ge-attr-pill"><span>${at.label}</span>\u00a0<span class="ge-attr-val">${val}</span></span>`;
        }).join('') + '</div>';
    } else {
      // 2-col grid for idle
      attrHtml = '<div style="border-top:1px solid var(--border);margin-top:8px;padding-top:7px;display:grid;grid-template-columns:1fr 1fr;gap:1px 12px">' +
        normalAttrs.slice(0, 10).map(at => {
          const val = at.unit ? `${at.value}\u202F${at.unit}` : at.value;
          return `<div style="font-size:11px;padding:2px 0;color:var(--text-dim)">${at.label}: <span style="color:var(--text)">${val}</span></div>`;
        }).join('') + '</div>';
    }
  }

  // ── Controls ──────────────────────────────────────────────────────────────
  let ctrlHtml = '';
  const ctrlWrap = 'display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;padding-top:8px;border-top:1px solid var(--border)';
  if (!isOffline && isLaundry) {
    if (isRunning) {
      ctrlHtml = `<div style="${ctrlWrap}">
  <button class="ge-ctrl-btn pause" onclick="geApplCommand('${a.id}','${a.type}','pause_${typeKey}')">&#9646;&#9646; Pause</button>
  <button class="ge-ctrl-btn stop"  onclick="geApplCommand('${a.id}','${a.type}','stop_${typeKey}')">&#9632; Cancel</button>
</div>`;
    } else if (isPaused) {
      ctrlHtml = `<div style="${ctrlWrap}">
  <button class="ge-ctrl-btn resume" onclick="geApplCommand('${a.id}','${a.type}','resume_${typeKey}')">&#9654; Resume</button>
  <button class="ge-ctrl-btn stop"   onclick="geApplCommand('${a.id}','${a.type}','stop_${typeKey}')">&#9632; Cancel</button>
</div>`;
    } else if (isEOC) {
      ctrlHtml = `<div style="${ctrlWrap}">
  <button class="ge-ctrl-btn stop" style="flex:1" onclick="geApplCommand('${a.id}','${a.type}','stop_${typeKey}')">&#9989; Dismiss / Clear</button>
</div>`;
    } else if (a.remote_enabled && (a.state === 'idle' || a.state === 'remote start')) {
      ctrlHtml = `<div style="${ctrlWrap}">
  <button class="ge-ctrl-btn start" style="flex:1" onclick="geApplCommand('${a.id}','${a.type}','remote_start')">&#9654; Remote Start</button>
</div>`;
    }
  } else if (isFridge && !isOffline) {
    // Fridge quick controls — Turbo Cool / Turbo Freeze / Ice Maker
    const hasTurboCool   = normalAttrs.some(x => x.label === 'Turbo Cool'  && x.value === 'On');
    const hasTurboFreeze = normalAttrs.some(x => x.label === 'Turbo Freeze' && x.value === 'On');
    const iceMakerAttr   = normalAttrs.find(x => x.label === 'Ice Maker');
    const iceMakerOn     = iceMakerAttr ? iceMakerAttr.value === 'On' : null;
    const btns = [];
    btns.push(`<button class="ge-ctrl-btn fridge ${hasTurboCool?'resume':''}" onclick="geFridgeToggle('${a.id}','turbo_cool',${!hasTurboCool})">&#10052; Turbo Cool ${hasTurboCool?'Off':'On'}</button>`);
    btns.push(`<button class="ge-ctrl-btn fridge ${hasTurboFreeze?'resume':''}" onclick="geFridgeToggle('${a.id}','turbo_freeze',${!hasTurboFreeze})">&#10052;&#65038; Turbo Freeze ${hasTurboFreeze?'Off':'On'}</button>`);
    if (iceMakerOn !== null) {
      btns.push(`<button class="ge-ctrl-btn fridge ${iceMakerOn?'resume':''}" onclick="geFridgeToggle('${a.id}','icemaker',${!iceMakerOn})">&#129398; Ice Maker ${iceMakerOn?'Off':'On'}</button>`);
    }
    ctrlHtml = `<div style="${ctrlWrap}">${btns.join('')}</div>`;
  }

  // ── Model footer ──────────────────────────────────────────────────────────
  const modelStr    = [a.brand, a.model].filter(Boolean).join(' ');
  const modelFooter = modelStr ? `<div style="font-size:10px;color:var(--text-dim);margin-top:8px;opacity:.45">${modelStr}</div>` : '';

  return `<div class="card${runClass}" style="padding:14px;position:relative;border-color:${borderCol};${cardBg?'background:'+cardBg:''}transition:border-color 0.3s">
  <div style="display:flex;align-items:flex-start;gap:12px;margin-bottom:6px">
    <span style="font-size:32px;line-height:1;margin-top:2px;${iconGlow}">${a.icon || '&#127968;'}</span>
    <div style="flex:1;min-width:0">
      <div style="font-size:14px;font-weight:700;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${a.name}</div>
      <div style="font-size:11px;color:var(--text-dim);margin-top:1px">${a.type || 'Appliance'}</div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0">
      ${stBadge}
      ${ageStr ? `<span style="font-size:10px;color:var(--text-dim)">${ageStr}</span>` : ''}
    </div>
  </div>
  ${cycleHtml}
  ${progressHtml}
  ${tempHtml}
  ${energyHtml}
  ${statsHtml}
  ${alertHtml}
  ${attrHtml}
  ${ctrlHtml}
  ${modelFooter}
</div>`;
}

// ══ Device IP editing ═════════════════════════════════════════════════════════
function editDeviceIp(device) {
  const currentIp = document.getElementById('cfg-ip-'+device)?.textContent?.trim() || '';
  const input = document.getElementById('cfg-ip-input-'+device);
  if (input) input.value = currentIp;
  const editDiv = document.getElementById('cfg-edit-'+device);
  if (editDiv) { editDiv.style.display = 'flex'; editDiv.style.gap = '8px'; editDiv.style.alignItems = 'center'; }
}
function cancelDeviceIp(device) {
  const editDiv = document.getElementById('cfg-edit-'+device);
  if (editDiv) editDiv.style.display = 'none';
}
function saveDeviceIp(device) {
  const input = document.getElementById('cfg-ip-input-'+device);
  const status = document.getElementById('cfg-ip-status-'+device);
  if (!input) return;
  const ip = input.value.trim();
  if (status) status.textContent = 'Saving...';
  fetch('/api/config/device-ip', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({device, ip})
  }).then(r=>r.json()).then(d => {
    if (d.ok) {
      const ipDisplay = document.getElementById('cfg-ip-'+device);
      if (ipDisplay) ipDisplay.textContent = ip;
      cancelDeviceIp(device);
      toast('✓ IP updated — will take effect on next poll');
    } else {
      if (status) status.textContent = '✗ ' + (d.error || 'Error');
    }
  }).catch(e => { if (status) status.textContent = '✗ ' + e; });
}

// ══ Settings save functions ════════════════════════════════════════════════════
function saveWyze() {
  const body = {
    api_key:  document.getElementById('wyze-api-key').value.trim(),
    key_id:   document.getElementById('wyze-key-id').value.trim(),
    email:    document.getElementById('wyze-email').value.trim(),
    password: document.getElementById('wyze-password').value.trim(),
  };
  const statusEl = document.getElementById('wyze-save-status');
  statusEl.textContent = 'Saving…';
  fetch('/api/settings/wyze', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(r=>r.json()).then(d => {
      statusEl.textContent = d.ok ? '✓ Saved' : ('✗ ' + (d.error||'Error'));
      statusEl.style.color = d.ok ? 'var(--online)' : 'var(--error)';
      if (d.ok) toast('✓ Wyze credentials saved');
    }).catch(e => { statusEl.textContent = '✗ ' + e; statusEl.style.color = 'var(--error)'; });
}

function saveRing() {
  const body = {
    email:    document.getElementById('ring-email').value.trim(),
    password: document.getElementById('ring-password').value.trim(),
  };
  const statusEl = document.getElementById('ring-save-status');
  statusEl.textContent = 'Saving…';
  fetch('/api/settings/ring', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(r=>r.json()).then(d => {
      statusEl.textContent = d.ok ? '✓ Saved' : ('✗ ' + (d.error||'Error'));
      statusEl.style.color = d.ok ? 'var(--online)' : 'var(--error)';
      if (d.ok) toast('✓ Ring credentials saved');
    }).catch(e => { statusEl.textContent = '✗ ' + e; statusEl.style.color = 'var(--error)'; });
}

function saveNest() {
  const token = document.getElementById('nest-token-input').value.trim();
  const statusEl = document.getElementById('nest-save-status');
  statusEl.textContent = 'Saving…';
  fetch('/api/settings/nest', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})})
    .then(r=>r.json()).then(d => {
      statusEl.textContent = d.ok ? '✓ Saved' : ('✗ ' + (d.error||'Error'));
      statusEl.style.color = d.ok ? 'var(--online)' : 'var(--error)';
      if (d.ok) toast('✓ Nest token saved');
    }).catch(e => { statusEl.textContent = '✗ ' + e; statusEl.style.color = 'var(--error)'; });
}

function saveBhyve() {
  const email = document.getElementById('bhyve-email').value.trim();
  const pw    = document.getElementById('bhyve-password').value.trim();
  const statusEl = document.getElementById('bhyve-save-status');
  statusEl.textContent = 'Saving…';
  fetch('/api/settings/bhyve', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password:pw})})
    .then(r=>r.json()).then(d => {
      statusEl.textContent = d.ok ? '✓ Saved' : ('✗ ' + (d.error||'Error'));
      statusEl.style.color = d.ok ? 'var(--online)' : 'var(--error)';
      if (d.ok) toast('✓ B-Hyve credentials saved');
    }).catch(e => { statusEl.textContent = '✗ ' + e; statusEl.style.color = 'var(--error)'; });
}

function saveGE() {
  const clientId     = document.getElementById('ge-client-id').value.trim();
  const clientSecret = document.getElementById('ge-client-secret').value.trim();
  const refreshToken = document.getElementById('ge-refresh-token').value.trim();
  const statusEl = document.getElementById('ge-save-status');
  statusEl.textContent = 'Saving\u2026';
  fetch('/api/settings/ge', {method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({client_id:clientId,client_secret:clientSecret,refresh_token:refreshToken})})
    .then(r=>r.json()).then(d => {
      statusEl.textContent = d.ok ? '\u2713 Saved' : ('\u2717 ' + (d.error||'Error'));
      statusEl.style.color = d.ok ? 'var(--online)' : 'var(--error)';
      if (d.ok) toast('\u2713 GE SmartHQ credentials saved');
    }).catch(e => { statusEl.textContent = '\u2717 ' + e; statusEl.style.color = 'var(--error)'; });
}

function saveTeslaPasswordFromSettings() {
  const pw = document.getElementById('settings-tesla-pw').value.trim();
  if (!pw) { toast('Enter a password first'); return; }
  const statusEl = document.getElementById('settings-tesla-status');
  statusEl.textContent = 'Saving…';
  fetch('/api/tesla/set_password', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})})
    .then(r=>r.json()).then(d => {
      statusEl.textContent = d.ok ? ('✓ Connected — ' + d.status) : ('✗ ' + (d.error||'Error'));
      statusEl.style.color = d.ok ? 'var(--online)' : 'var(--error)';
      if (d.ok) toast('✓ Tesla password saved');
    }).catch(e => { statusEl.textContent = '✗ ' + e; statusEl.style.color = 'var(--error)'; });
}

// ─────────────────────────────────────────────────────────────────────────────

// ═══════════════════════════════════════════════════════════════════════════
// TABLET DASHBOARD MODES — Microgrid, Trading, Backup
// ═══════════════════════════════════════════════════════════════════════════

// ── SRP Rate Period ──────────────────────────────────────────────────────────
function getSRPRatePeriod() {
  const now = new Date(); const h = now.getHours();
  const dow = now.getDay(); const month = now.getMonth();
  const isWeekday = dow >= 1 && dow <= 5;
  // SRP E-27 has THREE seasons:
  // Winter: Nov-Apr (months 10,11,0,1,2,3)
  // Summer: May,Jun,Sep,Oct (months 4,5,8,9)
  // Summer Peak: Jul,Aug (months 6,7) — same hours, higher rates
  const isWinter = (month >= 10 || month <= 3); // Nov-Apr
  const isSummerPeak = (month === 6 || month === 7); // Jul-Aug
  const isSummer = (month === 4 || month === 5 || month === 8 || month === 9); // May,Jun,Sep,Oct
  
  if (isWeekday) {
    if (isWinter) {
      // Winter on-peak: 05:00-09:00 AND 17:00-21:00
      if ((h >= 5 && h < 9) || (h >= 17 && h < 21)) return { label:'On-Peak', cls:'peak', rate:0.23 };
    } else if (isSummer || isSummerPeak) {
      // Summer & Summer Peak on-peak: 14:00-20:00
      if (h >= 14 && h < 20) return { label:'On-Peak', cls:'peak', rate:0.23 };
    }
  }
  // Weekends, holidays, and all off-peak hours
  return { label:'Off-Peak', cls:'off-peak', rate:0.10 };
}

// ── MODE 1: Particle Animation ────────────────────────────────────────────────
let mcParticles = [];
let mcFlowPaths = [];
let mcAnimFrame = null;

function mcNodePositions(W, H) {
  const cx = W/2, cy = H/2;
  return {
    enphase:   {x: 28,   y: cy - 120},
    solaredge: {x: 28,   y: cy},
    srpGrid:   {x: 28,   y: cy + 120},
    core:      {x: cx,   y: cy},
    home:      {x: W-28, y: cy - 90},
    pool:      {x: W-28, y: cy + 40},
    truck:     {x: W-28, y: cy + 160},
  };
}

function mcBezierPt(p0, p1, p2, t) {
  const m = 1-t;
  return { x: m*m*p0.x + 2*m*t*p1.x + t*t*p2.x, y: m*m*p0.y + 2*m*t*p1.y + t*t*p2.y };
}

function mcCtrl(from, to) {
  return { x:(from.x*0.3 + to.x*0.3 + (from.x+to.x)/2*0.4), y:(from.y*0.3 + to.y*0.3 + (from.y+to.y)/2*0.4) };
}

function mcUpdateFlowPaths(s) {
  const sum = s.summary || {}, wc = s.wall_connector || {}, span = s.span || {};
  const circuits = span.circuits || [];
  const enphW  = (sum.enphase_solar_w || 0)/1000;
  const seW    = (sum.solaredge_solar_w || 0)/1000;
  const gridW  = (sum.srp_grid_w || 0)/1000;   // signed: + import
  const homeW  = (sum.load_w || 0)/1000;
  const ctRaw  = (wc.charging_w || 0)/1000;
  const ctV2H  = sum.ct_v2h || false;
  const poolCirc = circuits.find(c => (c.name||'').toLowerCase().includes('pool'));
  const poolW  = poolCirc ? Math.abs(poolCirc.power_w||0)/1000 : 0;
  const evW    = ctV2H ? 0 : Math.abs(ctRaw);
  const truckW = ctV2H ? Math.abs(ctRaw) : 0;
  mcFlowPaths = [
    {from:'enphase',   to:'core',    kw:enphW,              color:'#FFD700', active:enphW>0.05},
    {from:'solaredge', to:'core',    kw:seW,                color:'#FFC200', active:seW>0.05},
    {from:'srpGrid',   to:'core',    kw:gridW>0?gridW:0,    color:'#3B82F6', active:gridW>0.05},
    {from:'core',      to:'srpGrid', kw:gridW<0?-gridW:0,   color:'#1D4ED8', active:gridW<-0.05},
    {from:'truck',     to:'core',    kw:truckW,             color:'#00FFFF', active:truckW>0.05},
    {from:'core',      to:'truck',   kw:evW,                color:'#22d3ee', active:evW>0.05},
    {from:'core',      to:'home',    kw:homeW,              color:'#9B59B6', active:homeW>0.05},
    {from:'core',      to:'pool',    kw:poolW,              color:'#06b6d4', active:poolW>0.05},
  ];
}

function mcDrawFrame() {
  const canvas = document.getElementById('mc-canvas');
  const viewEl = document.getElementById('csub-microgrid');
  if (!canvas || !viewEl) {
    mcAnimFrame = requestAnimationFrame(mcDrawFrame); return;
  }
  const W = canvas.parentElement.clientWidth;
  const H = canvas.parentElement.clientHeight;
  if (!W || !H) { mcAnimFrame = requestAnimationFrame(mcDrawFrame); return; }
  if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);
  const nodes = mcNodePositions(W, H);

  // Draw flow paths + spawn particles
  mcFlowPaths.forEach(path => {
    const f = nodes[path.from], t2 = nodes[path.to];
    if (!f || !t2) return;
    const cp = mcCtrl(f, t2);
    ctx.beginPath(); ctx.moveTo(f.x, f.y); ctx.quadraticCurveTo(cp.x, cp.y, t2.x, t2.y);
    ctx.strokeStyle = path.color; ctx.lineWidth = Math.max(3, path.kw * 6);
    ctx.globalAlpha = path.active ? 0.35 : 0.08; ctx.setLineDash([]); ctx.stroke(); ctx.globalAlpha = 1;
    // Spawn
    if (path.active && mcParticles.length < 180 && Math.random() < Math.min(0.6, path.kw * 0.18)) {
      mcParticles.push({path, t:Math.random()*0.3, speed: 0.005 + path.kw * 0.002});
    }
  });

  // Update + draw particles
  const live = [];
  mcParticles.forEach(p => {
    p.t += p.speed;
    if (p.t > 1) return;
    const f = nodes[p.path.from], t2 = nodes[p.path.to];
    if (!f || !t2) return;
    const cp = mcCtrl(f, t2);
    const pos = mcBezierPt(f, cp, t2, p.t);
    const grad = ctx.createRadialGradient(pos.x, pos.y, 0, pos.x, pos.y, 6);
    grad.addColorStop(0, p.path.color); grad.addColorStop(1, 'transparent');
    ctx.beginPath(); ctx.arc(pos.x, pos.y, 7, 0, Math.PI*2);
    ctx.fillStyle = grad; ctx.globalAlpha = 0.75; ctx.fill(); ctx.globalAlpha = 1;
    ctx.beginPath(); ctx.arc(pos.x, pos.y, 3, 0, Math.PI*2);
    ctx.fillStyle = p.path.color; ctx.fill();
    live.push(p);
  });
  mcParticles = live;
  mcAnimFrame = requestAnimationFrame(mcDrawFrame);
}

// Module-level demand tracking for microgrid mode
let mcDemandSamples = [];
let mcSessionPeak   = 0;

function updateMicrogrid(s) {
  const sum = s.summary || {}, wc = s.wall_connector || {}, tesla = s.tesla || {}, span = s.span || {};
  const circuits = span.circuits || [];
  const enphKW  = (sum.enphase_solar_w   || 0) / 1000;
  const seKW    = (sum.solaredge_solar_w  || 0) / 1000;
  const gridW   = sum.srp_grid_w || 0;
  const homeW   = sum.load_w     || 0;
  const ctRaw   = wc.charging_w  || 0;
  const ctV2H   = sum.ct_v2h     || false;
  const totalSW = (sum.solar_w   || 0);
  const poolCirc = circuits.find(c => (c.name||'').toLowerCase().includes('pool'));
  const poolKW  = poolCirc ? Math.abs(poolCirc.power_w||0)/1000 : 0;
  const evKW    = ctV2H ? 0 : Math.abs(ctRaw)/1000;
  const truckDischargeKW = ctV2H ? Math.abs(ctRaw)/1000 : 0;
  const loadW   = homeW + Math.abs(ctRaw);
  const netW    = totalSW - loadW;
  const rp      = getSRPRatePeriod();
  const BLENDED_RATE = 0.181;  // weighted avg all-in rate (incl. demand charges) — do not change
  const totalLoadKW = loadW / 1000;
  const exportingKW = gridW < -50 ? Math.abs(gridW) / 1000 : 0;
  const netGridKW   = gridW > 50  ? gridW / 1000 : 0;
  // Exporting → negative cost (credit at same blended rate); importing → positive cost
  const costHr  = exportingKW > 0
    ? (-(exportingKW * BLENDED_RATE)).toFixed(2)
    : (netGridKW > 0 ? (netGridKW * BLENDED_RATE) : (totalLoadKW * BLENDED_RATE)).toFixed(2);
  const solarPct= loadW > 0 ? Math.min(100, Math.round(totalSW/loadW*100)) : 0;
  const islanded = tesla.islanded || false;

  // 15-min demand tracking
  const nowMs = Date.now();
  mcDemandSamples.push({t: nowMs, w: loadW});
  mcDemandSamples = mcDemandSamples.filter(sp => nowMs - sp.t <= 15*60*1000);
  const demand15W = mcDemandSamples.length > 0
    ? mcDemandSamples.reduce((a,b) => a+b.w, 0) / mcDemandSamples.length
    : loadW;
  if (loadW > mcSessionPeak) mcSessionPeak = loadW;

  // Truck card label
  let truckMode = 'Idle';
  let truckDispKW = evKW;
  if (ctV2H)                      { truckMode = 'Powershare (V2H)'; truckDispKW = truckDischargeKW; }
  else if (evKW > 0.1)             { truckMode = 'Charging'; }
  else if (!wc.vehicle_connected)  { truckMode = 'Away'; }

  const setText = (id, v) => { const el = document.getElementById(id); if(el) el.textContent = v; };
  const setHTML = (id, v) => { const el = document.getElementById(id); if(el) el.innerHTML  = v; };

  // LEFT column — combined solar card
  setText('mc-solar-total-kw', (enphKW + seKW).toFixed(2));
  setText('mc-enphase-sub',    enphKW.toFixed(2) + ' kW');
  setText('mc-solaredge-sub',  seKW.toFixed(2) + ' kW');

  // Grid card
  setText('mc-grid-kw',        (Math.abs(gridW)/1000).toFixed(2));
  setText('mc-grid-direction',  gridW > 50 ? '▼ Importing' : gridW < -50 ? '▲ Exporting' : 'Balanced');

  // Hero card
  const netEl = document.getElementById('mc-net-kw');
  if(netEl){ netEl.textContent = (Math.abs(netW)/1000).toFixed(2); netEl.style.color = netW>=0?'#10b981':'#ef4444'; }
  setText('mc-net-direction',   (netW>=0?'▲ Exporting':'▼ Importing') + ' kW');
  setText('mc-home-kw',         (homeW/1000).toFixed(2) + ' kW');
  const costEl = document.getElementById('mc-cost-hr');
  if(costEl) {
    const isCredit = parseFloat(costHr) < 0;
    costEl.textContent = isCredit ? '-$' + Math.abs(parseFloat(costHr)).toFixed(2) + '/hr ↺' : '$' + costHr + '/hr';
    costEl.style.color = isCredit ? '#10b981' : '#f59e0b';
  }
  setText('mc-solar-pct',       solarPct + '%');
  setText('mc-demand-15m',      (demand15W/1000).toFixed(2) + ' kW');
  setText('mc-session-peak',    (mcSessionPeak/1000).toFixed(2) + ' kW');

  // RIGHT column
  setText('mc-home-load-kw',    (homeW/1000).toFixed(2));
  setText('mc-pool-kw',         poolKW.toFixed(2));
  setText('mc-pool-status',     poolCirc ? poolCirc.relay : '—');
  setText('mc-truck-kw',        truckDispKW.toFixed(2));
  setText('mc-truck-mode',      truckMode);

  // Live Power Flow page — Cybertruck metric card
  const ctLmBadge = document.getElementById('ct-lm-badge');
  const ctLmSoc   = document.getElementById('ct-lm-soc');
  const ctLmSub   = document.getElementById('ct-lm-sub');
  if (ctLmBadge) { ctLmBadge.textContent = wc.vehicle_connected ? (evKW > 0.1 ? 'charging' : 'connected') : 'away'; }
  if (ctLmSoc)   { ctLmSoc.textContent = evKW > 0.05 ? (evKW*1000).toFixed(0)+'' : '—'; document.getElementById('ct-lm-soc').nextElementSibling.textContent = evKW > 0.05 ? 'W' : ''; }
  if (ctLmSub)   { ctLmSub.textContent = evKW > 0.05 ? 'Charging · '+evKW.toFixed(2)+' kW' : truckMode; }

  // Top 3 circuits mini chart in Home Panel card
  const top5 = circuits.filter(c => Math.abs(c.power_w||0) > 10)
    .sort((a,b) => Math.abs(b.power_w||0) - Math.abs(a.power_w||0)).slice(0,3);
  const maxCircW = Math.max(...top5.map(c => Math.abs(c.power_w||0)), 1);
  const circHtml = top5.map(c => {
    const w = Math.abs(c.power_w||0);
    const pct = (w/maxCircW*100).toFixed(0);
    const nm = (c.name||c.id||'').replace(/</g,'&lt;');
    const kw = (w/1000).toFixed(2);
    return `<div style='margin-bottom:5px'>
      <div style='display:flex;justify-content:space-between;margin-bottom:2px'>
        <span style='opacity:0.7;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:110px'>${nm}</span>
        <span style='color:#9B59B6;font-weight:700'>${kw} kW</span>
      </div>
      <div style='height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden'>
        <div style='height:100%;width:${pct}%;background:#9B59B6;border-radius:2px;transition:width 0.5s'></div>
      </div></div>`;
  }).join('');
  setHTML("mc-home-circuits", circHtml);

  // Banner live totals
  const gridDir = gridW > 50 ? "▼" : gridW < -50 ? "▲" : "—";
  setText("mc-banner-solar",    "☀ " + (totalSW/1000).toFixed(2) + " kW");
  setText("mc-banner-load",     "🏠 " + (loadW/1000).toFixed(2) + " kW");
  setText("mc-banner-grid",     "⚡ " + gridDir + " " + (Math.abs(gridW)/1000).toFixed(2) + " kW");
  const bannerCostEl = document.getElementById('mc-banner-cost');
  if(bannerCostEl) {
    const isCr = parseFloat(costHr) < 0;
    bannerCostEl.textContent = isCr ? '-$' + Math.abs(parseFloat(costHr)).toFixed(2) + '/hr ↺' : '$' + costHr + '/hr';
    bannerCostEl.style.color = isCr ? '#10b981' : '#f59e0b';
  }
  setText("mc-banner-coverage", solarPct + "% ☀");

  const rateEl = document.getElementById("mc-rate");
  if(rateEl){ rateEl.textContent = rp.label; rateEl.className = "sb-rate " + rp.cls; }
  const now = new Date();
  setText("mc-time", now.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}));
  const gsEl = document.getElementById("mc-grid-status"), ibEl = document.getElementById("mc-island-badge");
  if(gsEl){ gsEl.textContent = islanded?"Islanded":"Grid ✓"; gsEl.className = "sb-grid " + (islanded?"islanded":"up"); }
  if(ibEl) ibEl.style.display = islanded ? "inline-flex" : "none";

  // Card glow
  const setGlow = (id, cls, extra) => {
    const el = document.getElementById(id);
    if(el) el.className = "glass-card" + (cls ? " " + cls : "") + (extra ? ";" + extra : "");
  };
  const solarCardEl = document.getElementById("mc-solar-card");
  if(solarCardEl) solarCardEl.className = (enphKW+seKW) > 0.1 ? "glass-card glow-solar" : "glass-card";
  const gridCardEl = document.getElementById("mc-grid-card");
  if(gridCardEl) { gridCardEl.className = "glass-card"; gridCardEl.style.borderColor = "rgba(59,130,246," + (Math.max(0, gridW) > 100 ? "0.6" : "0.3") + ")"; }
  const homeCardEl = document.getElementById("mc-home-card");
  if(homeCardEl) homeCardEl.className = "glass-card" + (homeW > 500 ? " glow-load" : "") + " " + ""; // keep flex style via inline
  const truckCardEl = document.getElementById("mc-truck-card");
  if(truckCardEl) truckCardEl.className = ctV2H ? "glass-card glow-truck" : "glass-card";

  mcUpdateFlowPaths(s);

  // Sparklines for Mode 1 cards
  pushHist(mcSolarHist,  totalSW/1000);
  pushHist(mcGridHist,   Math.abs(gridW)/1000);
  pushHist(mcHomeHist,   homeW/1000);
  pushHist(mcPoolHist,   poolKW);
  pushHist(mcTruckHist,  truckDispKW);
  drawSparkline('mc-solar-spark', mcSolarHist, '#FFD700');
  drawSparkline('mc-grid-spark',  mcGridHist,  '#3B82F6');
  drawSparkline('mc-home-spark',  mcHomeHist,  '#9B59B6');
  drawSparkline('mc-pool-spark',  mcPoolHist,  '#06b6d4');
  drawSparkline('mc-truck-spark', mcTruckHist, '#00FFFF');
}

// ── MODE 2: Trading Desk ─────────────────────────────────────────────────────
const SPARK_LEN = 72;
const tdEnphHist   = new Array(SPARK_LEN).fill(0);
const tdSEHist     = new Array(SPARK_LEN).fill(0);
const tdDemandHist = new Array(SPARK_LEN).fill(0);
let   tdPeak24h    = 0;
const mcSolarHist  = new Array(SPARK_LEN).fill(0);
const mcGridHist   = new Array(SPARK_LEN).fill(0);
const mcHomeHist   = new Array(SPARK_LEN).fill(0);
const mcPoolHist   = new Array(SPARK_LEN).fill(0);
const mcTruckHist  = new Array(SPARK_LEN).fill(0);

// Cache loading moved to BEFORE SSE connection (see below)

function pushHist(arr, v) { arr.push(v); if(arr.length > SPARK_LEN) arr.shift(); }

// ── Energy History Cache (localStorage) ────────────────────────────────────
function saveHistToCache() {
  try {
    const cache = {
      tdEnphHist, tdSEHist, tdDemandHist, tdPeak24h,
      mcSolarHist, mcGridHist, mcHomeHist, mcPoolHist, mcTruckHist,
      mcDemandSamples, mcSessionPeak,
      biEventLog, biLastIsland, biPeak24h
    };
    localStorage.setItem('jarvis_energy_cache', JSON.stringify(cache));
  } catch(e) {
    console.warn('Cache save failed:', e);
  }
}

function loadHistFromCache() {
  try {
    const cached = localStorage.getItem('jarvis_energy_cache');
    if (!cached) return false;
    const data = JSON.parse(cached);
    // Restore trading mode
    if (data.tdEnphHist)   { tdEnphHist.length = 0; tdEnphHist.push(...data.tdEnphHist); }
    if (data.tdSEHist)     { tdSEHist.length = 0; tdSEHist.push(...data.tdSEHist); }
    if (data.tdDemandHist) { tdDemandHist.length = 0; tdDemandHist.push(...data.tdDemandHist); }
    if (data.tdPeak24h !== undefined) tdPeak24h = data.tdPeak24h;
    // Restore microgrid mode
    if (data.mcSolarHist)  { mcSolarHist.length = 0; mcSolarHist.push(...data.mcSolarHist); }
    if (data.mcGridHist)   { mcGridHist.length = 0; mcGridHist.push(...data.mcGridHist); }
    if (data.mcHomeHist)   { mcHomeHist.length = 0; mcHomeHist.push(...data.mcHomeHist); }
    if (data.mcPoolHist)   { mcPoolHist.length = 0; mcPoolHist.push(...data.mcPoolHist); }
    if (data.mcTruckHist)  { mcTruckHist.length = 0; mcTruckHist.push(...data.mcTruckHist); }
    if (data.mcDemandSamples !== undefined) {
      mcDemandSamples.length = 0;
      mcDemandSamples.push(...data.mcDemandSamples);
    }
    if (data.mcSessionPeak !== undefined) mcSessionPeak = data.mcSessionPeak;
    // Restore backup mode
    if (data.biEventLog !== undefined) {
      biEventLog.length = 0;
      biEventLog.push(...data.biEventLog);
    }
    if (data.biLastIsland !== undefined) biLastIsland = data.biLastIsland;
    if (data.biPeak24h !== undefined) biPeak24h = data.biPeak24h;
    return true;
  } catch(e) {
    console.warn('Cache load failed:', e);
    return false;
  }
}

function drawSparkline(id, data, color) {
  const canvas = document.getElementById(id); if(!canvas) return;
  const W = canvas.parentElement ? canvas.parentElement.clientWidth : 200;
  const H = 34; canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0,0,W,H);
  const max = Math.max(...data, 0.01);
  ctx.beginPath();
  data.forEach((v,i) => {
    const x = (i/(data.length-1))*W, y = H - (v/max)*H*0.88;
    i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
  });
  ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
  const last = ctx.getLineDash ? data[data.length-1] : 0;
  ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
  const g = ctx.createLinearGradient(0,0,0,H);
  const rgb = color.replace('#','');
  const r=parseInt(rgb.slice(0,2),16),gv=parseInt(rgb.slice(2,4),16),b=parseInt(rgb.slice(4,6),16);
  g.addColorStop(0, `rgba(${r},${gv},${b},0.3)`); g.addColorStop(1, 'transparent');
  ctx.fillStyle = g; ctx.fill();
}

function drawSankey(s) {
  const canvas = document.getElementById('td-sankey-canvas'); if(!canvas) return;
  const W = canvas.parentElement ? canvas.parentElement.clientWidth : 0;
  const H = canvas.parentElement ? canvas.parentElement.clientHeight : 0;
  if(!W || !H) return;
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d'); ctx.clearRect(0,0,W,H);
  const sum = s.summary || {}, wc = s.wall_connector || {};
  const enW  = sum.enphase_solar_w   || 0;
  const seW  = sum.solaredge_solar_w || 0;
  const giW  = Math.max(0,  sum.srp_grid_w || 0);
  const geW  = Math.max(0, -(sum.srp_grid_w || 0));
  const homeW = sum.load_w || 0;
  const ctW  = Math.abs(wc.charging_w || 0);
  const poolW = sum.pool_w || 0;
  // Always show SRP Grid (import/export) — grayed out when idle
  const allSources = [
    {label:'Enphase', w:enW, c:'#FFD700'},
    {label:'SolarEdge', w:seW, c:'#FFC200'},
    {label:'SRP Grid', w:giW, c:'#3B82F6', alwaysShow:true},
  ];
  const allSinks = [
    {label:'Home',       w:homeW, c:'#9B59B6'},
    {label:'Pool',       w:poolW, c:'#06b6d4'},
    {label:'EV Charge',  w:ctW,   c:'#22d3ee'},
    {label:'Grid Export',w:geW,   c:'#1D4ED8', alwaysShow:true},
  ];
  const sources = allSources.filter(x=>x.w>10||x.alwaysShow);
  const sinks   = allSinks.filter(x=>x.w>10||x.alwaysShow);
  if(!sources.length && !sinks.length) {
    ctx.fillStyle='rgba(255,255,255,0.15)'; ctx.font='16px system-ui'; ctx.textAlign='center';
    ctx.fillText('No significant flows', W/2, H/2); return;
  }
  const hpad=40, vpad=20, nw=14, total=Math.max(sources.reduce((a,x)=>a+x.w,0), 1);
  const maxH = H - vpad*2;
  let sy=vpad;
  sources.forEach(src => {
    src._h = src.w > 0 ? Math.max(4,(src.w/total)*maxH) : 4; src._y = sy;
    const alpha = src.w > 0 ? 0.75 : 0.22;
    ctx.fillStyle=src.c; ctx.globalAlpha=alpha; ctx.fillRect(hpad, sy, nw, src._h);
    ctx.globalAlpha=1;
    ctx.fillStyle = src.w > 0 ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.25)';
    ctx.font='bold 16px system-ui'; ctx.textAlign='left';
    ctx.fillText(src.label, hpad+nw+4, sy+src._h/2+5);
    sy += src._h + 5;
  });
  let dy=vpad;
  sinks.forEach(snk => {
    snk._h = snk.w > 0 ? Math.max(4,(snk.w/total)*maxH) : 4; snk._y = dy;
    const alpha = snk.w > 0 ? 0.75 : 0.22;
    ctx.fillStyle=snk.c; ctx.globalAlpha=alpha; ctx.fillRect(W-hpad-nw, dy, nw, snk._h);
    ctx.globalAlpha=1;
    ctx.fillStyle = snk.w > 0 ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.25)';
    ctx.font='bold 16px system-ui'; ctx.textAlign='right';
    ctx.fillText(snk.label, W-hpad-nw-4, dy+snk._h/2+5);
    dy += snk._h + 5;
  });
  const x0=hpad+nw, x1=W-hpad-nw, cpx=(x0+x1)/2;
  sources.forEach(src => {
    if(src.w <= 0) return;
    sinks.forEach(snk => {
      if(snk.w <= 0) return;
      const fw = Math.min(src._h, snk._h) * 0.6; if(fw < 1) return;
      ctx.beginPath(); ctx.moveTo(x0, src._y+src._h/2);
      ctx.bezierCurveTo(cpx, src._y+src._h/2, cpx, snk._y+snk._h/2, x1, snk._y+snk._h/2);
      const g = ctx.createLinearGradient(x0,0,x1,0);
      g.addColorStop(0, src.c); g.addColorStop(1, snk.c);
      ctx.strokeStyle=g; ctx.lineWidth=Math.max(1, fw*0.35); ctx.globalAlpha=0.3; ctx.stroke(); ctx.globalAlpha=1;
    });
  });
}

function updateCircuitBars(s, extraCircuits) {
  const el = document.getElementById('td-circuit-bars'); if(!el) return;
  const circuits = ((s.span||{}).circuits||[]);
  const allCircuits = extraCircuits ? [...circuits, ...extraCircuits] : circuits;
  const sorted = [...allCircuits].filter(c=>Math.abs(c.power_w||0)>0)
    .sort((a,b)=>Math.abs(b.power_w)-Math.abs(a.power_w)).slice(0,12);
  const maxW = Math.max(...sorted.map(c=>Math.abs(c.power_w||0)), 1);
  el.innerHTML = sorted.map(c => {
    const w=Math.abs(c.power_w||0), pct=(w/maxW*100).toFixed(0);
    const isTruck = c._isTruck || false;
    const canShed = !isTruck && c.relay && c.relay !== 'CLOSED_COMMITTED' && w > 100;
    const nameStyle = isTruck ? ' style="color:#00FFFF"' : '';
    const valStyle  = isTruck ? ' style="color:#00FFFF"' : '';
    const fillStyle = isTruck ? 'background:#00FFFF;' : '';
    return `<div class="circuit-bar-row">
      <div class="circuit-bar-label"${nameStyle} title="${c.name||c.id}">${c.name||c.id}</div>
      <div class="circuit-bar-track"><div class="circuit-bar-fill" style="${fillStyle}width:${pct}%"></div></div>
      <div class="circuit-bar-val"${valStyle}>${(w/1000).toFixed(2)}k</div>
      ${c.relay==='OPEN' ? `<button class="shed-btn" onclick="restoreSpanCircuit('${c.id}','${c.name}')" style="border-color:rgba(74,222,128,.5);background:rgba(74,222,128,.1);color:#4ade80;">Restore</button>` : canShed ? `<button class="shed-btn" onclick="shedSpanCircuit('${c.id}')">Shed</button>` : '<div style="width:36px"></div>'}
    </div>`;
  }).join('');
}

function updateTrading(s) {
  const sum = s.summary||{}, wc = s.wall_connector||{};
  const enW = sum.enphase_solar_w||0, seW = sum.solaredge_solar_w||0;
  const totalSW = enW + seW;
  const loadW   = (sum.load_w||0) + Math.abs(wc.charging_w||0);
  const gridW   = sum.srp_grid_w || 0;
  if(loadW > tdPeak24h) tdPeak24h = loadW;
  pushHist(tdEnphHist,   enW/1000);
  pushHist(tdSEHist,     seW/1000);
  pushHist(tdDemandHist, loadW/1000);

  const RATE     = 0.181;  // weighted avg all-in rate (incl. demand charges) — do not change
  const loadKW   = loadW / 1000;
  const solarKW  = totalSW / 1000;
  const exportingKW2 = gridW < -50 ? Math.abs(gridW) / 1000 : 0;
  const netGridKW2   = gridW > 50  ? gridW / 1000 : 0;
  const costHr   = exportingKW2 > 0
    ? (-(exportingKW2 * RATE)).toFixed(2)
    : (netGridKW2 > 0 ? (netGridKW2 * RATE) : (loadKW * RATE)).toFixed(2);
  const coverage = loadKW > 0 ? Math.min(100, Math.round(solarKW/loadKW*100)) : 0;
  const gridDir  = gridW > 50 ? "▼ " : gridW < -50 ? "▲ " : "";
  const gridLabel= gridDir + (Math.abs(gridW)/1000).toFixed(2) + " kW";

  const setText=(id,v)=>{const e=document.getElementById(id);if(e)e.innerHTML=v;};
  const setTxt =(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v;};
  setText('td-enphase-kw',       (enW/1000).toFixed(2)+'<span style="font-size:0.8rem;opacity:0.4"> kW</span>');
  setText('td-solaredge-kw',     (seW/1000).toFixed(2)+'<span style="font-size:0.8rem;opacity:0.4"> kW</span>');
  setText('td-total-solar-kw',   (totalSW/1000).toFixed(2)+'<span style="font-size:0.8rem;opacity:0.4"> kW</span>');
  const capEl = document.getElementById('td-solar-capacity-pct');
  if(capEl) capEl.textContent = (totalSW/11800*100).toFixed(0) + '% of 11.8 kW capacity';
  setText('td-demand-15m',       (loadW/1000).toFixed(2)+'<span style="font-size:0.8rem;opacity:0.4"> kW</span>');
  setText('td-peak-proj',        (tdPeak24h/1000).toFixed(2)+'<span style="font-size:0.8rem;opacity:0.4"> kW</span>');
  const demBar = document.getElementById('td-demand-bar');
  if(demBar) demBar.style.width = Math.min(100, loadW/15000*100).toFixed(0) + '%';
  const lu = document.getElementById('td-last-update');
  if(lu) lu.textContent = new Date().toLocaleTimeString();
  const now2 = new Date();
  const rp2 = getSRPRatePeriod();
  setTxt('td-time', now2.toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit', hour12:true}));
  const tdRateEl = document.getElementById('td-rate');
  if(tdRateEl) { tdRateEl.textContent = rp2.label; tdRateEl.className = 'sb-rate ' + rp2.cls; }

  // Cost/hr and solar coverage in demand strip
  const isTdCredit = parseFloat(costHr) < 0;
  const costLabel  = isTdCredit ? '-$' + Math.abs(parseFloat(costHr)).toFixed(2) + '/hr ↺' : '$' + costHr + '/hr';
  const costColor  = isTdCredit ? '#10b981' : '#f59e0b';
  const tdCostEl   = document.getElementById('td-cost-hr');
  if(tdCostEl) { tdCostEl.textContent = costLabel; tdCostEl.style.color = costColor; }
  const tdTotCostEl = document.getElementById('td-total-cost');
  if(tdTotCostEl) { tdTotCostEl.textContent = costLabel; tdTotCostEl.style.color = costColor; }
  setTxt('td-solar-coverage', coverage + '%');

  // Totals bar
  setTxt('td-total-solar',    (totalSW/1000).toFixed(2) + ' kW');
  setTxt('td-total-load',     (loadW/1000).toFixed(2) + ' kW');
  setTxt('td-total-grid',     gridLabel);
  setTxt('td-total-coverage', coverage + '%');

  drawSparkline('td-enphase-spark',  tdEnphHist,   '#FFD700');
  drawSparkline('td-solaredge-spark',tdSEHist,     '#FFC200');
  drawSparkline('td-demand-chart',   tdDemandHist, '#9B59B6');
  drawSankey(s);

  // Cybertruck circuit entry
  const ctRawW  = Math.abs(wc.charging_w || 0);
  const ctV2H2  = sum.ct_v2h || false;
  const extraCircuits = [{
    name: ctV2H2 ? "Cybertruck (Powershare)" : "Cybertruck (Charging)",
    power_w: ctRawW,
    _isTruck: true
  }];
  updateCircuitBars(s, extraCircuits);
}

// ── MODE 3: Backup Intelligence ───────────────────────────────────────────────
const BI_TRUCK_KWH = 95;
let biEventLog  = [];
let biLastIsland= false;
let biPeak24h   = 0;

function drawSoCRing(id, pct) {
  const canvas = document.getElementById(id); if(!canvas) return;
  const W=canvas.width, H=canvas.height, cx=W/2, cy=H/2, r=Math.min(W,H)/2-8;
  const ctx=canvas.getContext('2d'); ctx.clearRect(0,0,W,H);
  ctx.beginPath(); ctx.arc(cx,cy,r,-Math.PI/2,Math.PI*1.5);
  ctx.strokeStyle='rgba(255,255,255,0.1)'; ctx.lineWidth=10; ctx.stroke();
  if(pct <= 0) return;
  const end = -Math.PI/2 + (pct/100)*Math.PI*2;
  ctx.beginPath(); ctx.arc(cx,cy,r,-Math.PI/2,end);
  ctx.strokeStyle = pct>50?'#00FFFF':pct>20?'#f59e0b':'#ef4444';
  ctx.lineWidth=10; ctx.lineCap='round'; ctx.stroke();
}

function biAddEvent(msg, type) {
  const t = new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  biEventLog.unshift({t,msg,type});
  if(biEventLog.length>20) biEventLog.pop();
  const el = document.getElementById('bi-event-log');
  if(el) el.innerHTML = biEventLog.slice(0,10).map(e=>{
    const cls = e.type==='island'?'ev-type':e.type==='solar'?'ev-solar':'';
    return `<div><span class="ev-time">${e.t}</span><span class="${cls}">${e.msg}</span></div>`;
  }).join('');
}

function updateBackup(s) {
  const sum=s.summary||{}, wc=s.wall_connector||{}, tesla=s.tesla||{};
  const span=s.span||{}, circuits=span.circuits||[];
  const islanded = tesla.islanded || false;
  if(islanded&&!biLastIsland) biAddEvent('Grid outage detected — Island mode active','island');
  if(!islanded&&biLastIsland) biAddEvent('Grid restored — connected','info');
  biLastIsland = islanded;
  const ctW   = Math.abs(wc.charging_w||0);
  const ctV2H = sum.ct_v2h||false;
  const loadW = (sum.load_w||0) + ctW;
  if(loadW > biPeak24h) biPeak24h = loadW;
  const soe = tesla.status==='online' ? (tesla.soe||0) : null;
  const truckSoC = soe; // No direct Cybertruck SoC yet — using site SoE as proxy
  const poolCirc = circuits.find(c=>(c.name||'').toLowerCase().includes('pool'));
  const ac2Circ  = circuits.find(c=>{const n=(c.name||'').toLowerCase();return n.includes('ac')&&(n.includes('2')||n.includes('cond'));});
  const evCirc   = circuits.find(c=>{const n=(c.name||'').toLowerCase();return n.includes('wall')||n.includes('charger')||n.includes('ev');});
  const poolW = poolCirc ? Math.abs(poolCirc.power_w||0) : 0;
  const ac2W  = ac2Circ  ? Math.abs(ac2Circ.power_w||0) : 0;

  function calcHr(soc, kw) { if(!soc||kw<=0) return '—'; return (BI_TRUCK_KWH*(soc/100)/kw).toFixed(1); }
  const curKW  = loadW/1000, peakKW = biPeak24h/1000, critKW = 1.5;

  // SoC ring + readout
  if(truckSoC !== null) {
    document.getElementById('bi-soc-pct').innerHTML = Math.round(truckSoC)+'<span style="font-size:1rem;opacity:0.4">%</span>';
    drawSoCRing('bi-soc-ring', truckSoC);
  }

  // Runtime
  const setText=(id,v)=>{const e=document.getElementById(id);if(e)e.innerHTML=v;};
  const sfx = '<span style="font-size:0.8rem;opacity:0.4"> h</span>';
  setText('bi-rt-critical', calcHr(truckSoC,critKW)+sfx);
  setText('bi-rt-current',  calcHr(truckSoC,curKW)+sfx);
  setText('bi-rt-peak',     calcHr(truckSoC,peakKW)+sfx);
  const cll=document.getElementById('bi-current-load-label'); if(cll) cll.textContent=curKW.toFixed(2)+' kW live';
  const pll=document.getElementById('bi-peak-load-label');    if(pll) pll.textContent=peakKW.toFixed(2)+' kW peak';
  const rtHr = calcHr(truckSoC, curKW);
  setText('bi-runtime-hr', rtHr + '<span style="font-size:0.8rem;opacity:0.4"> hrs</span>');
  setText('bi-discharge-kw', (ctV2H?(ctW/1000).toFixed(2):'0.00') + '<span style="font-size:0.8rem;opacity:0.4"> kW</span>');

  // Readiness
  const rb = document.getElementById('bi-readiness-badge');
  if(rb) {
    if (wc.vehicle_connected===false)     { rb.textContent='Not Home';  rb.className='badge offline'; }
    else if(truckSoC!==null&&truckSoC<20) { rb.textContent='Low SoC';   rb.className='badge warning'; }
    else if(ctW>100&&!ctV2H)              { rb.textContent='Charging';  rb.className='badge partial'; }
    else if(truckSoC!==null)              { rb.textContent='Ready';     rb.className='badge online';  }
    else                                   { rb.textContent='No Data';  rb.className='badge offline'; }
  }

  // Priority kW
  const p=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v;};
  p('bi-pool-kw', (poolW/1000).toFixed(2)+' kW');
  p('bi-ev-kw',   (ctW/1000).toFixed(2)+' kW');
  p('bi-ac2-kw',  (ac2W/1000).toFixed(2)+' kW');

  // Shed/restore button visibility — reflect live relay state
  const spanCircuits = ((window._lastState||s).span||{}).circuits||[];
  function _updateShedRow(type, keywords) {
    const c = spanCircuits.find(c => keywords.some(k => (c.name||'').toLowerCase().includes(k)));
    if (!c) return;
    const isOff = c.relay === 'OPEN';
    const badge = document.getElementById('shed-badge-'+type);
    const shedBtn = document.getElementById('shed-btn-'+type);
    const restoreBtn = document.getElementById('restore-btn-'+type);
    if (badge) badge.style.display = isOff ? 'inline' : 'none';
    if (shedBtn) shedBtn.style.display = isOff ? 'none' : 'inline-block';
    if (restoreBtn) restoreBtn.style.display = isOff ? 'inline-block' : 'none';
  }
  _updateShedRow('pool', ['pool']);
  _updateShedRow('ev',   ['wall', 'charger', 'ev']);
  _updateShedRow('ac2',  ['ac']);


  // Island styling
  const mc=document.getElementById('bi-main-card'), ib=document.getElementById('bi-island-badge');
  if(mc) { mc.className = islanded ? 'glass-card island-glow' : 'glass-card'; }
  if(ib) ib.style.display = islanded ? 'inline-flex' : 'none';

  const lu=document.getElementById('bi-last-update'); if(lu) lu.textContent=new Date().toLocaleTimeString();
}

// ── Shed helpers ────────────────────────────────────────────────────────────
function shedSpanCircuit(id) {
  if(!SPAN_TOKEN_CONFIGURED) { toast('SPAN token not configured'); return; }
  fetch('/api/span/circuit/'+id, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({relayState:'OPEN'})
  }).then(r=>r.json()).then(d=>toast(d.ok?('✓ Shed: '+id):('✗ '+(d.error||'Error')))).catch(e=>toast('✗ '+e));
}
function restoreSpanCircuit(id, label) {
  if(!SPAN_TOKEN_CONFIGURED) { toast('SPAN token not configured'); return; }
  fetch('/api/span/circuit/'+id, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({relayState:'CLOSED'})
  }).then(r=>r.json()).then(d=>toast(d.ok?('✓ Restored: '+(label||id)):('✗ '+(d.error||'Error')))).catch(e=>toast('✗ '+e));
}
function restoreCircuit(type) {
  const circuits = ((window._lastState||{}).span||{}).circuits||[];
  let target = null;
  if(type==='pool') target=circuits.find(c=>(c.name||'').toLowerCase().includes('pool'));
  if(type==='ev')   target=circuits.find(c=>{const n=(c.name||'').toLowerCase();return n.includes('wall')||n.includes('charger')||n.includes('ev');});
  if(type==='ac2')  target=circuits.find(c=>{const n=(c.name||'').toLowerCase();return n.includes('ac')&&(n.includes('2')||n.includes('cond'));});
  if(target) restoreSpanCircuit(target.id, target.name);
  else toast('Circuit not found in SPAN data');
}
function shedCircuit(type) {
  const circuits = ((window._lastState||{}).span||{}).circuits||[];
  let target = null;
  if(type==='pool') target=circuits.find(c=>(c.name||'').toLowerCase().includes('pool'));
  if(type==='ev')   target=circuits.find(c=>{const n=(c.name||'').toLowerCase();return n.includes('wall')||n.includes('charger')||n.includes('ev');});
  if(type==='ac2')  target=circuits.find(c=>{const n=(c.name||'').toLowerCase();return n.includes('ac')&&(n.includes('2')||n.includes('cond'));});
  if(target) shedSpanCircuit(target.id);
  else toast('Circuit not found in SPAN data');
}
function myqCmd(serial, action) {
  fetch('/api/myq/door/'+encodeURIComponent(serial)+'/'+action, {method:'POST'})
    .then(r=>r.json())
    .then(d=>toast(d.ok ? ('🚗 Garage ' + action + ' sent') : ('✗ MyQ: ' + (d.error||'Error'))))
    .catch(e=>toast('✗ MyQ: ' + e));
}

// Keyboard arrow keys for cockpit panel scrolling
document.addEventListener('keydown', function(e) {
  var cockpitEl = document.getElementById('view-cockpit');
  if (!cockpitEl || cockpitEl.style.display === 'none') return;
  var panelsEl = document.getElementById('cockpit-panels');
  if (!panelsEl) return;
  var idx = Math.round(panelsEl.scrollLeft / (panelsEl.offsetWidth || 1));
  idx = Math.max(0, Math.min(idx, _cockpitSubs.length - 1));
  if (e.key === 'ArrowRight' && idx < _cockpitSubs.length - 1) setCockpitSub(_cockpitSubs[idx + 1]);
  if (e.key === 'ArrowLeft' && idx > 0) setCockpitSub(_cockpitSubs[idx - 1]);
});

// Flag for SPAN token (set by Python template)
const SPAN_TOKEN_CONFIGURED = {{ 'true' if config_span_token else 'false' }};

// Load cached energy data BEFORE SSE starts (critical for persistence)
if (typeof window !== 'undefined') {
  const cacheLoaded = loadHistFromCache();
  if (cacheLoaded) console.log('[Cache] Restored energy history from localStorage');
}

// SSE connection (AFTER cache load)
const evtSrc = new EventSource('/api/stream');
evtSrc.onmessage = e => { try { renderState(JSON.parse(e.data)); } catch(err) { console.error(err); } };
evtSrc.onerror = () => console.warn('SSE disconnected — retrying...');

// ── Ring Doorbell SSE, Popup & Page Refresh ──────────────────────────────────
let _ringSSE = null;
let _ringPopupCountdownTimer = null;
let _ringPopupImgTimer = null;
let _ringViewRefreshTimer = null;
let _ringRecentEvts = [];

function _connectRingSSE() {
  if (_ringSSE) { try { _ringSSE.close(); } catch(e){} }
  _ringSSE = new EventSource('/api/ring/events');
  _ringSSE.onmessage = function(e) {
    try {
      const evt = JSON.parse(e.data);
      _ringRecentEvts.unshift(evt);
      if (_ringRecentEvts.length > 30) _ringRecentEvts.pop();
      _renderRingEventsList();
      if (evt.type === 'ding') {
        showDoorbellPopup(evt);
        const el = document.getElementById('ring-last-ding');
        if (el) el.textContent = new Date(evt.ts * 1000).toLocaleTimeString();
      } else if (evt.type === 'motion') {
        const el = document.getElementById('ring-last-motion');
        if (el) el.textContent = new Date(evt.ts * 1000).toLocaleTimeString();
      }
    } catch(err) { console.error('Ring SSE parse error', err); }
  };
  _ringSSE.onerror = function() { setTimeout(_connectRingSSE, 10000); };
}

function showDoorbellPopup(evt) {
  const popup = document.getElementById('ring-popup');
  if (!popup) return;
  clearTimeout(_ringPopupCountdownTimer);
  clearInterval(_ringPopupImgTimer);
  // Fill popup content
  const timeEl = document.getElementById('ring-popup-time');
  if (timeEl) timeEl.textContent = new Date(evt.ts * 1000).toLocaleString();
  const devEl = document.getElementById('ring-popup-device');
  if (devEl) devEl.textContent = evt.device || 'Front Door';
  const cdEl = document.getElementById('ring-popup-countdown');
  // Doorbell chime via Web Audio API
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [[523,0],[659,0.28],[784,0.56],[659,0.84]].forEach(([freq, t]) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.35, ctx.currentTime + t);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.45);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + t);
      osc.stop(ctx.currentTime + t + 0.5);
    });
  } catch(e) {}
  // Show popup
  popup.style.display = 'flex';
  // Refresh camera image every 30s while open (Ring cloud rate)
  _ringPopupImgTimer = setInterval(() => { /* snapshot removed */ }, 30000);
  // Countdown auto-dismiss
  let remaining = 60;
  function _tick() {
    if (cdEl) cdEl.textContent = 'Auto-dismiss in ' + remaining + 's';
    if (remaining <= 0) { dismissDoorbellPopup(); return; }
    remaining--;
    _ringPopupCountdownTimer = setTimeout(_tick, 1000);
  }
  _tick();
}

function dismissDoorbellPopup() {
  const popup = document.getElementById('ring-popup');
  if (popup) popup.style.display = 'none';
  clearTimeout(_ringPopupCountdownTimer);
  clearInterval(_ringPopupImgTimer);
}

function _renderRingEventsList() {
  const el = document.getElementById('ring-events-list');
  if (!el) return;
  if (!_ringRecentEvts.length) {
    el.innerHTML = '<div style="color:rgba(255,255,255,0.3);font-size:12px;padding:8px">No recent events</div>';
    return;
  }
  el.innerHTML = _ringRecentEvts.slice(0, 20).map(e => {
    const icon  = e.type === 'ding' ? '&#128276;' : '&#128065;';
    const label = e.type === 'ding' ? 'Doorbell' : 'Motion';
    const t     = new Date(e.ts * 1000).toLocaleString();
    const dev   = e.device || 'Front Door';
    return '<div style="display:flex;gap:10px;align-items:center;padding:6px 8px;background:rgba(255,255,255,0.03);border-radius:6px">'
      + '<span style="font-size:1.1rem">' + icon + '</span>'
      + '<span style="font-weight:600;min-width:64px">' + label + '</span>'
      + '<span style="color:rgba(255,255,255,0.5);font-size:12px">' + dev + '</span>'
      + '<span style="margin-left:auto;font-size:12px;color:rgba(255,255,255,0.4)">' + t + '</span>'
      + '</div>';
  }).join('');
}

// Ring view: try to load snapshot; refresh every 30s (Ring cloud API rate)
function _startRingViewRefresh() {
  if (_ringViewRefreshTimer) return;
  _ringViewRefreshTimer = setInterval(() => {
    const i = document.getElementById('ring-live-img');
    if (!i) return;
    
    const ageEl = document.getElementById('ring-snap-age');
    if (ageEl) ageEl.textContent = 'Snapshot \u00b7 ' + new Date().toLocaleTimeString();
  }, 30000);
}
function _stopRingViewRefresh() {
  clearInterval(_ringViewRefreshTimer);
  _ringViewRefreshTimer = null;
}

// Patch showView to start/stop ring camera refresh and update events list
const _origShowView = showView;
showView = function(v) {
  _origShowView(v);
  if (v === 'ring') { _startRingViewRefresh(); _renderRingEventsList(); }
  else _stopRingViewRefresh();
};

// Start Ring SSE on page load
_connectRingSSE();

// ── fitCockpit: constrain cockpit panels to available viewport height ──
function fitCockpit() {
  var header = document.querySelector('header');
  var vc     = document.getElementById('view-cockpit');
  if (!header || !vc) return;
  var avail = window.innerHeight - header.offsetHeight;
  vc.style.height    = avail + 'px';
  vc.style.maxHeight = avail + 'px';
}
window.addEventListener('resize', fitCockpit);

// Initial load — start on Energy Cockpit
showView('energy');
fetch('/api/state').then(r=>r.json()).then(renderState).catch(console.error);
// Run after layout settles
fitCockpit();
setTimeout(fitCockpit, 50);
setTimeout(fitCockpit, 200);

// Weather fetch — Queen Creek, AZ (refresh every 10 min)
(function fetchWeather() {
  fetch("https://wttr.in/Queen+Creek,AZ?format=j1")
    .then(r => r.json())
    .then(d => {
      const cur = d.current_condition && d.current_condition[0];
      if(cur) {
        const tempF = cur.temp_F || "--";
        const desc  = (cur.weatherDesc && cur.weatherDesc[0] && cur.weatherDesc[0].value) || "";
        const txt   = tempF + "°F " + desc;
        const el = document.getElementById("mc-weather");
        if(el) el.textContent = txt;
        const tdW = document.getElementById("td-weather");
        if(tdW) tdW.textContent = txt;
      }
    })
    .catch(() => {
      const el = document.getElementById("mc-weather");
      if(el) el.textContent = "Queen Creek, AZ";
      const tdW = document.getElementById("td-weather");
      if(tdW) tdW.textContent = "Queen Creek, AZ";
    });
  setTimeout(fetchWeather, 10*60*1000);
})();

// Start particle animation loop (runs continuously, draws only when microgrid mode active)
mcDrawFrame();

// ── Cockpit Swipe Panels ─────────────────────────────────────────────
var _cockpitSubs = ['microgrid', 'live', 'trading', 'backup'];

function _setCockpitDot(sub) {
  document.querySelectorAll('.ck-dot').forEach(function(d) {
    d.classList.toggle('active', d.dataset.sub === sub);
  });
}

function setCockpitSub(sub) {
  var idx = _cockpitSubs.indexOf(sub);
  if (idx < 0) idx = 0;
  var panelsEl = document.getElementById('cockpit-panels');
  if (panelsEl) {
    if (panelsEl.offsetWidth > 0) {
      panelsEl.scrollTo({ left: idx * panelsEl.offsetWidth, behavior: 'smooth' });
    } else {
      // Not laid out yet — set directly after layout
      setTimeout(function() {
        if (panelsEl.offsetWidth > 0) panelsEl.scrollLeft = idx * panelsEl.offsetWidth;
      }, 80);
    }
  }
  _setCockpitDot(sub);
  // Sync sub-rail active state
  document.querySelectorAll('#sr-energy .sub-rail-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.sub === 'ck-' + sub);
  });
  localStorage.setItem('jarvis-cockpit-sub-v3', sub);
}

// Update dots on scroll (IntersectionObserver-free: just use scroll event)
(function() {
  var panelsEl = document.getElementById('cockpit-panels');
  if (!panelsEl) return;
  var _scrollTimer;
  panelsEl.addEventListener('scroll', function() {
    clearTimeout(_scrollTimer);
    _scrollTimer = setTimeout(function() {
      var idx = Math.round(panelsEl.scrollLeft / (panelsEl.offsetWidth || 1));
      idx = Math.max(0, Math.min(idx, _cockpitSubs.length - 1));
      var sub = _cockpitSubs[idx];
      _setCockpitDot(sub);
      localStorage.setItem('jarvis-cockpit-sub-v3', sub);
    }, 80);
  }, { passive: true });
})();

// Init: restore last sub or default to microgrid
(function() {
  var _initSub = localStorage.getItem('jarvis-cockpit-sub-v3') || 'microgrid';
  // Mark the matching sub-rail button active
  document.querySelectorAll('#sr-energy .sub-rail-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.sub === 'ck-' + _initSub);
  });
  _setCockpitDot(_initSub);
  // Scroll to saved position after a short delay (panels may not be laid out yet)
  setTimeout(function() {
    var panelsEl = document.getElementById('cockpit-panels');
    var idx = _cockpitSubs.indexOf(_initSub);
    if (idx < 0) idx = 0;
    if (panelsEl && panelsEl.offsetWidth > 0) {
      panelsEl.scrollLeft = idx * panelsEl.offsetWidth;
    }
  }, 100);
})();
</script>
</body>
</html>
"""


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STARTUP                                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Inject SPAN_TOKEN config flag into template
DASHBOARD_HTML = DASHBOARD_HTML.replace(
    "{{ 'true' if config_span_token else 'false' }}",
    "true" if SPAN_TOKEN else "false"
)


if __name__ == "__main__":
    log.info("Starting Jarvis Home Energy OS on port %d", DASHBOARD_PORT)
    log.info("Devices configured:")
    log.info("  SPAN    : %s (token=%s)", SPAN_HOST, "yes" if SPAN_TOKEN else "NO")
    log.info("  Enphase : %s (token=%s)", ENPHASE_HOST, "yes" if ENPHASE_TOKEN else "NO")
    log.info("  Pentair : %s:%d", PENTAIR_HOST, PENTAIR_PORT)
    log.info("  Tesla   : %s", TESLA_HOST or "not configured")

    # Initialize energy analytics database
    init_db()

    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()

    # Wyze camera RTSP frame cache threads (all 3 cams via wyze-bridge)
    _start_rtsp_threads()
    log.info("RTSP camera capture threads started for: %s", list(_RTSP_CAM_URLS.keys()))

    # Ring doorbell background threads (snapshot + event polling)
    if _ring_token_data:
        # snapshot poller removed — Ring's snapshot API is blocked, always 204
        threading.Thread(target=_ring_event_poller, daemon=True, name="ring-events").start()
        log.info("Ring background threads started")

    log.info("Discovering Roku devices via SSDP ...")
    import threading as _threading
    def _roku_startup():
        global ROKU_IPS
        ROKU_IPS = _discover_roku_devices()
        log.info("Roku discovery complete: %d device(s) found: %s", len(ROKU_IPS), ROKU_IPS)
        # Start background re-discovery loop
        _threading.Thread(target=_roku_rediscover_loop, daemon=True).start()
    _threading.Thread(target=_roku_startup, daemon=True).start()

    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False, threaded=True)
