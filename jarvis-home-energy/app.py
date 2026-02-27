#!/usr/bin/env python3
"""
Jarvis Home Energy OS — Unified Home Energy Dashboard
Covers: SPAN Panel · Enphase Solar · Pentair Pool · Tesla Energy Gateway 3V · Tesla Wall Connector Gen 3
"""

import json
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
from flask import Flask, Response, jsonify, render_template_string, request, stream_with_context

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

app = Flask(__name__)

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

# Ring — cached token data (persisted across calls to avoid repeated re-auth)
# ring_doorbell 0.9.x is fully async; we wrap with a fresh event loop
_ring_token_data = {}
_ring_next_retry = 0
_ring_lock = threading.Lock()


def _ring_token_updater(token_data):
    global _ring_token_data
    _ring_token_data = token_data


def _run_async(coro):
    """Run an async coroutine synchronously in a fresh event loop (thread-safe)."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _ring_build(update=True):
    """Authenticate with Ring and optionally fetch device data."""
    from ring_doorbell import Ring, Auth
    auth = Auth("JarvisHomeEnergy/1.0", _ring_token_data or None, _ring_token_updater)
    if not _ring_token_data:
        await auth.async_fetch_token(RING_EMAIL, RING_PASSWORD)
    ring = Ring(auth)
    await ring.async_create_session()
    if update:
        await ring.async_update_data()
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
                    "H0001": "Gas Heater",
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

    # Ring — fully async in ring_doorbell 0.9.x; use cached token + backoff
    # DISABLED: Ring requires interactive 2FA to get initial token. Re-enable once
    # authenticated interactively and token cached. Until then this spams Rob with texts.
    global _ring_next_retry
    if False and RING_EMAIL and RING_PASSWORD and time.time() >= _ring_next_retry:
        try:
            ring_cameras = _run_async(_ring_poll_cameras_async())
            cameras.extend(ring_cameras)
            _ring_next_retry = 0
            log.info("Ring poll OK — %d devices", len(ring_cameras))
        except Exception as e:
            log.warning("Ring poll error: %s — backing off 5 min", e)
            _ring_next_retry = time.time() + 300

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
    token = data.get("orbit_session_token") or data.get("session_token")
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
    """Send a command to B-Hyve via WebSocket (websockets 11+)."""
    import asyncio
    import json as _json
    tok = token or _bhyve_token

    async def _send():
        import websockets
        ws_url = "wss://api.orbitbhyve.com/v1/events"
        # websockets >=11: additional_headers replaces extra_headers
        connect_kwargs = {
            "ping_interval": None,
            "open_timeout": 10,
        }
        try:
            # websockets >= 11 uses additional_headers
            async with websockets.connect(
                ws_url,
                additional_headers={"Orbit-Session-Token": tok or ""},
                **connect_kwargs,
            ) as ws:
                hello = _json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                log.debug("B-Hyve WS hello: %s", hello)
                await ws.send(_json.dumps(payload))
                try:
                    ack = _json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    log.debug("B-Hyve WS ack: %s", ack)
                except asyncio.TimeoutError:
                    pass
        except TypeError:
            # Fallback for older websockets API using extra_headers
            async with websockets.connect(
                ws_url,
                extra_headers={"Orbit-Session-Token": tok or ""},
                **connect_kwargs,
            ) as ws:
                hello = _json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                log.debug("B-Hyve WS hello: %s", hello)
                await ws.send(_json.dumps(payload))
                try:
                    ack = _json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    log.debug("B-Hyve WS ack: %s", ack)
                except asyncio.TimeoutError:
                    pass

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

        for dev in devices_raw:
            dev_id = dev.get("id", "")
            dev_name = dev.get("name", "Unknown Device")
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
                if state.get("on"): attrs.append({"label": "Ice Bin", "value": "Full", "unit": ""})
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
                r3 = urllib.request.Request(f"{GE_API_BASE}/v2/device/{did}/alert", headers=hdr)
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
            alert_attrs = []
            _now = _time.time()
            for al in dev_alerts:
                atype = al.get("alertType","").replace("cloud.smarthq.alert.","")
                # Only show alerts triggered in the last 24 hours
                last_time_str = al.get("lastAlertTime","")
                if last_time_str:
                    try:
                        import datetime as _dt
                        lt = _dt.datetime.fromisoformat(last_time_str.replace("Z","+00:00")).timestamp()
                        if (_now - lt) > 86400:
                            continue  # skip stale alerts
                    except Exception:
                        pass
                label = _GE_ALERT_LABELS.get(atype, None)
                if label is None:
                    # Skip generic notification subscriptions (endofcycle, ota, pausedcycle etc)
                    _skip = {"endofcycle","ota","pausedcycle","cyclefeedback","selfclean",
                             "endofcycle.minutesleft","endofcycle.minutesafter","damp",
                             "tank.detergent.low","tank.detergent.empty"}
                    atype_key = atype.lower().replace(".","").replace(" ","")
                    if any(s in atype_key for s in ["endofcycle","otaupdate","pausedcycle","cyclefeedback",
                                                     "selfclean","minutesleft","minutesafter","tankdetergent"]):
                        continue
                    label = "⚠️ " + atype.replace("."," ").title()
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
    global _camera_poll_counter, _ge_poll_counter
    log.info("Polling loop started (interval=%ds, parallel)", POLL_INTERVAL_SECONDS)
    _camera_poll_counter = 11  # trigger camera poll on first tick
    _ge_poll_counter = 11      # trigger GE appliance poll on first tick
    _nest_poll_counter = 11    # trigger Nest poll on first tick (every 60s — SDM API rate limit)
    _roku_poll_counter = 5     # trigger Roku poll every 30s (6 ticks × 5s)
    while True:
        # Cameras: poll every 60s (every 12 ticks at 5s) — Wyze login is rate-limited
        _camera_poll_counter += 1
        # GE SmartHQ: poll every 30s
        _ge_poll_counter += 1
        # Nest SDM: poll every 60s — Google rate-limits at >1 req/min per device
        _nest_poll_counter += 1
        # Roku: poll every 30s — local network, lightweight
        _roku_poll_counter += 1
        poll_fns = [poll_pentair, poll_span, poll_enphase, poll_tesla, poll_wall_connector, poll_bhyve, poll_myq]
        if _nest_poll_counter >= 12:
            poll_fns.append(poll_nest)
            _nest_poll_counter = 0
        if _camera_poll_counter >= 12:
            poll_fns.append(poll_cameras)
            _camera_poll_counter = 0
        if _ge_poll_counter >= 6:
            poll_fns.append(poll_ge_appliances)
            _ge_poll_counter = 0
        if _roku_poll_counter >= 6:
            poll_fns.append(poll_roku)
            _roku_poll_counter = 0
        # Run all device polls concurrently — Pentair can take 45s, don't let it block solar/SPAN
        with concurrent.futures.ThreadPoolExecutor(max_workers=9) as ex:
            futs = [ex.submit(f) for f in poll_fns]
            concurrent.futures.wait(futs, timeout=60)
        try:
            _update_summary()
        except Exception as _sum_err:
            log.error("_update_summary() crashed: %s", _sum_err, exc_info=True)
        _broadcast_sse()
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
    return render_template_string(DASHBOARD_HTML)


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
            if not RING_EMAIL:
                return '', 204
            device_id = cam_id[5:]
            img_bytes = _run_async(_ring_get_snapshot_async(device_id))
            if img_bytes:
                return Response(img_bytes, mimetype='image/jpeg')
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


# ── RTSP camera frame cache (background ffmpeg threads) ───────────────────────
_RTSP_CAM_URLS = {
    "upstairs":   "rtsp://Camera:Feed@192.168.68.51/live",
    "downstairs": "rtsp://Camera:Feed@192.168.68.82/live",
    "front-side-cam": "rtsp://127.0.0.1:8554/front-side-cam",  # via docker-wyze-bridge
}
_rtsp_frame_cache: dict = {}   # cam_id → latest JPEG bytes
_rtsp_capture_threads: dict = {}

def _rtsp_capture_loop(cam_id: str, rtsp_url: str):
    """Background thread: keep ffmpeg alive, update frame cache on every keyframe."""
    import subprocess as _sp
    import os as _os
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
                '-q:v', '4',   # quality
                '-r', '0.2',   # 1 frame/5s — reduces CPU ~90% vs 2fps; plenty for dashboard tiles
                'pipe:1',
            ]
            # bufsize=0: unbuffered so os.read returns as soon as any bytes arrive
            proc = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.DEVNULL, bufsize=0)
            buf = b''
            while True:
                # os.read returns as soon as ANY data is available (no blocking until full)
                chunk = _os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                buf += chunk
                # Parse JPEG frames by SOI/EOI markers
                while True:
                    s = buf.find(b'\xff\xd8')
                    if s == -1:
                        buf = buf[-4:]
                        break
                    e = buf.find(b'\xff\xd9', s + 2)
                    if e == -1:
                        break
                    _rtsp_frame_cache[cam_id] = buf[s:e + 2]
                    buf = buf[e + 2:]
            proc.wait()
            log.info("RTSP ffmpeg exited for %s, reconnecting in 3s", cam_id)
        except Exception as exc:
            log.warning("RTSP capture error for %s: %s", cam_id, exc)
        time.sleep(3)   # brief pause before reconnect

def _rtsp_watchdog():
    """Watchdog thread: every 30s respawn any dead RTSP capture threads."""
    while True:
        time.sleep(30)
        for cam_id, rtsp_url in _RTSP_CAM_URLS.items():
            t = _rtsp_capture_threads.get(cam_id)
            if t is None or not t.is_alive():
                log.warning("RTSP watchdog: thread dead for %s, respawning", cam_id)
                nt = threading.Thread(target=_rtsp_capture_loop, args=(cam_id, rtsp_url),
                                      daemon=True, name=f"rtsp-{cam_id}")
                nt.start()
                _rtsp_capture_threads[cam_id] = nt

def _start_rtsp_threads():
    """Start background RTSP capture threads (called once on app startup)."""
    for cam_id, rtsp_url in _RTSP_CAM_URLS.items():
        if cam_id not in _rtsp_capture_threads:
            t = threading.Thread(target=_rtsp_capture_loop, args=(cam_id, rtsp_url),
                                 daemon=True, name=f"rtsp-{cam_id}")
            t.start()
            _rtsp_capture_threads[cam_id] = t
            log.info("Started RTSP capture thread: %s", cam_id)
    # Watchdog: respawn dead threads every 30s
    wd = threading.Thread(target=_rtsp_watchdog, daemon=True, name="rtsp-watchdog")
    wd.start()
    log.info("Started RTSP watchdog thread")

@app.route("/api/camera/<cam_id>/frame")
def camera_frame(cam_id):
    """Return the latest cached JPEG frame for an RTSP camera."""
    frame = _rtsp_frame_cache.get(cam_id)
    if not frame:
        return '', 204   # not ready yet — browser will retry
    resp = Response(frame, mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'no-cache, no-store'
    return resp


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
            "event": "change_mode",
            "device_id": device_id,
            "mode": "auto",
            "stations": [],
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


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DASHBOARD HTML                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
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
  body { background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; min-height: 100vh; }

  /* Nav */
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0; position: sticky; top: 0; z-index: 100; }
  .header-top { display: flex; align-items: center; gap: 20px; padding: 0 20px; height: 52px; }
  .logo { font-size: 16px; font-weight: 700; letter-spacing: .05em; color: var(--solar); }
  .logo span { color: var(--text-dim); }
  .nav-hamburger { display: none; background: none; border: 1px solid #444; color: var(--text); font-size: 1.4rem; padding: 4px 10px; border-radius: 6px; cursor: pointer; margin-left: auto; }
  nav { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px 20px 8px; }
  nav button { background: transparent; border: none; color: var(--text-dim); cursor: pointer; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-family: inherit; transition: all .15s; min-height: 36px; }
  nav button.active, nav button:hover { background: var(--surface2); color: var(--text); }
  .status-bar { display: flex; gap: 14px; align-items: center; }
  @media (max-width: 768px) {
    .nav-hamburger { display: block; }
    nav { display: none; flex-direction: column; align-items: stretch; padding: 0.5rem 1rem 1rem; }
    nav.open { display: flex; }
    nav button { width: 100%; text-align: left; min-height: 44px; font-size: 1rem; padding: 10px 14px; }
    .status-bar { display: none; }
    body { padding: 0; }
    #main-content, [id$="-view"], .view { padding: 0.75rem; }
    .card, .panel, .metric-card, .roku-card { min-width: unset !important; width: 100% !important; max-width: 100% !important; }
    table { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    main { padding: 0.5rem; }
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; }
  .dot.online { background: var(--online); box-shadow: 0 0 6px var(--online); }
  .dot.error { background: var(--error); }
  .dot.offline { background: var(--offline); }
  .dot.warning { background: var(--warning); }
  .ts { color: var(--text-dim); font-size: 11px; }

  /* Views */
  main { padding: 16px 20px; }
  .view { display: none; }
  .view.active { display: block; }
  /* Sub-nav buttons */
  .sub-nav-btn { padding: 6px 14px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.12); background: transparent; color: #aaa; cursor: pointer; font-size: 0.9rem; min-height: 36px; transition: all 0.15s; }
  .sub-nav-btn.active { background: rgba(99,102,241,0.2); border-color: rgba(99,102,241,0.4); color: #fff; }
  .sub-nav-btn:hover { background: rgba(255,255,255,0.08); color: #fff; }
  /* Cockpit is a flex column so sub-panels fill remaining height */
  #view-cockpit { display: none; flex-direction: column; }
  #view-cockpit.active { display: flex; flex-direction: column; }
  #view-cockpit .tablet-view { flex: 1; min-height: 0; height: auto; }

  /* Grid */
  .grid { display: grid; gap: 12px; }
  .grid-4 { grid-template-columns: repeat(4, 1fr); }
  .grid-3 { grid-template-columns: repeat(3, 1fr); }
  .grid-2 { grid-template-columns: repeat(2, 1fr); }
  @media (max-width: 900px) { .grid-4, .grid-3 { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 600px) { .grid-4, .grid-3, .grid-2 { grid-template-columns: 1fr; } }

  /* Card */
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
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
  .pc-hero-card { background: rgba(255,120,0,0.07); border: 1.5px solid rgba(255,120,0,0.22); border-radius: 14px; padding: 20px 16px; display: flex; flex-direction: column; align-items: center; gap: 4px; transition: border-color .3s, box-shadow .3s; }
  .pc-hero-card.spa-on { border-color: rgba(255,120,0,0.75); box-shadow: 0 0 30px rgba(255,120,0,0.25); }
  .pc-section-lbl { font-size: 10px; font-weight: 700; letter-spacing: 2px; color: rgba(255,255,255,0.35); text-transform: uppercase; }
  .pc-hero-temp { font-size: 76px; font-weight: 800; color: #FF7820; line-height: 1; margin: 8px 0 2px; }
  .pc-hero-setpt { font-size: 13px; color: rgba(255,255,255,0.45); }
  .pc-hero-actions { display: flex; gap: 10px; margin-top: 18px; width: 100%; }
  .pc-action-btn { flex: 1; padding: 15px 0; border-radius: 10px; border: none; font-size: 15px; font-weight: 700; letter-spacing: 0.5px; cursor: pointer; font-family: inherit; transition: filter .15s, background .15s; }
  .pc-btn-on  { background: linear-gradient(135deg,#FF7820,#FF4500); color: #fff; }
  .pc-btn-on:hover  { filter: brightness(1.15); }
  .pc-btn-off { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.18); color: rgba(255,255,255,0.65); }
  .pc-btn-off:hover { background: rgba(255,255,255,0.12); }
  .pc-right { display: grid; grid-template-columns: repeat(2,1fr); gap: 10px; align-content: start; }
  @media (max-width: 500px) { .pc-right { grid-template-columns: 1fr; } }
  .pc-stat-card { background: var(--surface2); border: 1px solid var(--border); border-radius: 12px; padding: 14px; }
  .pc-stat-hdr  { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .pc-stat-temp { font-size: 34px; font-weight: 700; color: var(--pool); margin: 4px 0; }
  .pc-stat-sub  { font-size: 11px; color: var(--text-dim); margin-top: 3px; }
  .pc-pump-big  { font-size: 30px; font-weight: 700; color: var(--pool); }
  .pc-pump-unit { font-size: 12px; color: var(--text-dim); }
  .pc-pump-row  { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
  .pc-circ-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(118px,1fr)); gap: 8px; }
  .pc-circ-tile { background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 11px 9px; text-align: center; transition: border-color .2s, background .2s; }
  .pc-circ-tile.circ-on { border-color: rgba(6,182,212,0.45); background: rgba(6,182,212,0.06); }
  .pc-circ-nm   { font-size: 11px; font-weight: 600; color: var(--text); margin-bottom: 5px; }
  .pc-circ-st   { font-size: 10px; font-weight: 700; letter-spacing: 1px; }
  .pc-circ-tile.circ-on .pc-circ-st { color: var(--online); }
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
  .camera-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; cursor: pointer; transition: border-color .2s; }
  .camera-card:hover { border-color: rgba(255,255,255,.25); }
  .camera-thumb { width: 100%; aspect-ratio: 16/9; object-fit: cover; background: var(--surface2); display: block; }
  .camera-thumb-placeholder { width: 100%; aspect-ratio: 16/9; background: var(--surface2); display: flex; align-items: center; justify-content: center; color: var(--text-dim); font-size: 32px; flex-direction: column; gap: 4px; }
  .camera-info { padding: 10px 12px; }
  .camera-name { font-weight: 700; font-size: 13px; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .camera-meta { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
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
  .tablet-view { height: calc(100vh - 52px); overflow: hidden; background: #0a0e1a; padding: 0; display: flex; flex-direction: column; }
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
  .mc-layout { display: grid; grid-template-columns: 200px 1fr 200px; gap: 10px; flex: 1; padding: 10px; min-height: 0; }
  .mc-left, .mc-right { display: flex; flex-direction: column; gap: 8px; justify-content: center; overflow: hidden; }
  .mc-center { position: relative; min-height: 0; }
  .mc-center canvas { position: absolute; inset: 0; width: 100%; height: 100%; border-radius: 16px; display: block; }
  .mc-overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: none; }
  .mc-hero { pointer-events: auto; text-align: center; min-width: 200px; max-width: 260px; }
  /* Mode 2 — Trading */
  .td-layout { display: flex; flex-direction: column; flex: 1; min-height: 0; }
  .td-top { display: grid; grid-template-columns: 190px 1fr 230px; gap: 10px; padding: 10px 12px 6px; flex: 1; min-height: 0; overflow: hidden; }
  .td-bottom { padding: 0 12px 10px; flex-shrink: 0; }
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

  /* ── Cockpit Sub-Nav ────────────────────────────────────────────────── */
  .csub-btn {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    padding: 7px 18px;
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.07);
    background: rgba(255,255,255,0.03);
    cursor: pointer;
    transition: all 0.2s ease;
    min-width: 100px;
    user-select: none;
    color: rgba(255,255,255,0.35);
  }
  .csub-btn:hover { background: rgba(255,255,255,0.07); color: rgba(255,255,255,0.7); }
  .csub-btn.active { background: rgba(255,255,255,0.06); color: #fff; }
  .csub-btn .csub-icon { font-size: 1rem; line-height: 1; }
  .csub-btn .csub-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.07em; font-weight: 700; opacity: 0.7; transition: opacity 0.2s; }
  .csub-btn.active .csub-label { opacity: 1; }
  .csub-btn .csub-dot { width: 6px; height: 6px; border-radius: 50%; border: 1.5px solid currentColor; background: transparent; transition: all 0.2s ease; }
  .csub-btn.active .csub-dot { background: currentColor; box-shadow: 0 0 6px currentColor; }
  .csub-btn.active[data-csub='live']      { color: #10b981; border-color: rgba(16,185,129,0.25); box-shadow: 0 0 10px rgba(16,185,129,0.07); }
  .csub-btn.active[data-csub='microgrid'] { color: #FFD700; border-color: rgba(255,215,0,0.25);  box-shadow: 0 0 10px rgba(255,215,0,0.07);  }
  .csub-btn.active[data-csub='trading']   { color: #3B82F6; border-color: rgba(59,130,246,0.25); box-shadow: 0 0 10px rgba(59,130,246,0.07); }
  .csub-btn.active[data-csub='backup']    { color: #00FFFF; border-color: rgba(0,255,255,0.25);  box-shadow: 0 0 10px rgba(0,255,255,0.07);  }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head>
<body>

<header>
  <div class="header-top">
    <div class="logo">🏠 <span>Jarvis Home</span></div>
    <div class="status-bar">
      <div id="span-dot" class="dot offline" title="SPAN Panel"></div>
      <div id="enphase-dot" class="dot offline" title="Enphase"></div>
      <div id="pentair-dot" class="dot offline" title="Pentair"></div>
      <div id="tesla-dot" class="dot offline" title="Tesla Gateway"></div>
      <div id="wc-dot" class="dot offline" title="Wall Connector"></div>
      <span class="ts" id="ts">—</span>
    </div>
    <button class="nav-hamburger" onclick="toggleNav()" aria-label="Menu">☰</button>
  </div>
  <nav id="nav-links">
    <button class="active" onclick="showView('energy')">⚡ Energy</button>
    <button onclick="showView('pool')">🏊 Pool</button>
    <button onclick="showView('thermostat')">🌡️ Thermostat</button>
    <button onclick="showView('sprinklers')">💧 Sprinklers</button>
    <button onclick="showView('entertainment')">📺 Entertainment</button>
    <button onclick="showView('cameras')">📷 Cameras</button>
    <button onclick="showView('appliances')">🏠 Appliances</button>
    <button onclick="showView('settings')">⚙️ Settings</button>
  </nav>
</header>

<!-- ── Active Appliance Banner (always visible when something is running) ── -->
<div id="appliance-banner" style="display:none;background:rgba(16,185,129,0.08);border-bottom:1px solid rgba(16,185,129,0.2);padding:6px 16px;font-size:12px;display:flex;align-items:center;gap:12px;flex-wrap:wrap"></div>

<main>

<!-- ═══ HOME DASHBOARD ═══════════════════════════════════════════════════════ -->


<!-- ═══ ENERGY WRAPPER ════════════════════════════════════════════════════════ -->
<div id="view-energy" class="view active">
  <div class="sub-nav" style="display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.08);flex-wrap:wrap;">
    <button class="sub-nav-btn active" onclick="showEnergySub('cockpit')">⚡ Cockpit</button>
    <button class="sub-nav-btn" onclick="showEnergySub('solar')">☀️ Solar</button>
    <button class="sub-nav-btn" onclick="showEnergySub('span')">🔌 SPAN</button>
    <button class="sub-nav-btn" onclick="showEnergySub('tesla-energy')"><svg width="14" height="14" viewBox="0 0 342 512" fill="currentColor" style="vertical-align:middle;margin-right:3px"><path d="M0 58.8L171 512 342 58.8c-45.8 17-100.3 26.4-171 26.4S45.8 75.8 0 58.8zM171 0c59.9 0 114.4 8.2 152.4 21.2L342 0H0l18.6 21.2C56.6 8.2 111.1 0 171 0z"/></svg>Tesla</button>
    <button class="sub-nav-btn" onclick="showEnergySub('cybertruck')"><svg width="26" height="14" viewBox="0 0 130 60" fill="none" style="vertical-align:middle;margin-right:3px"><g stroke="currentColor" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"><polygon points="8,48 14,22 32,10 72,8 96,18 118,20 122,48" fill="rgba(180,180,200,0.15)"/><line x1="32" y1="10" x2="35" y2="30"/><line x1="72" y1="8" x2="72" y2="20"/><line x1="96" y1="18" x2="96" y2="30"/><line x1="8" y1="48" x2="122" y2="48"/></g><circle cx="32" cy="48" r="9" fill="rgba(40,40,50,0.9)" stroke="currentColor" stroke-width="2.5"/><circle cx="32" cy="48" r="4" fill="rgba(200,200,210,0.6)"/><circle cx="95" cy="48" r="9" fill="rgba(40,40,50,0.9)" stroke="currentColor" stroke-width="2.5"/><circle cx="95" cy="48" r="4" fill="rgba(200,200,210,0.6)"/></svg>Cybertruck</button>
  </div>
</div>

<!-- ═══ CLIMATE WRAPPER (legacy, hidden) ════════════════════════════════════ -->
<div id="view-climate" class="view" style="display:none">
  <div class="sub-nav" style="display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.08);flex-wrap:wrap;">
    <button class="sub-nav-btn active" onclick="showClimateSub('home-control')">🌡️ Thermostat</button>
    <button class="sub-nav-btn" onclick="showClimateSub('sprinklers')">💧 Sprinklers</button>
  </div>
</div>

<!-- ═══ ENTERTAINMENT WRAPPER ════════════════════════════════════════════════ -->
<div id="view-entertainment" class="view">
  <div class="sub-nav" style="display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.08);flex-wrap:wrap;">
    <button class="sub-nav-btn active" onclick="showEntertainmentSub('roku')">📺 Roku TVs</button>
  </div>
</div>

<!-- ═══ ENERGY COCKPIT ═══════════════════════════════════════════════════════ -->
<div id="view-cockpit" class="view" style="display:none">

<div id="cockpit-subnav" style="display:flex;justify-content:center;gap:12px;padding:10px 16px;background:rgba(0,0,0,0.3);border-bottom:1px solid rgba(255,255,255,0.06);flex-shrink:0">
  <button class="csub-btn" data-csub="live" onclick="setCockpitSub('live')">
    <span class="csub-icon">⚡</span>
    <span class="csub-label">Live Power Flow</span>
    <span class="csub-dot"></span>
  </button>
  <button class="csub-btn" data-csub="microgrid" onclick="setCockpitSub('microgrid')">
    <span class="csub-icon">🔆</span>
    <span class="csub-label">Microgrid</span>
    <span class="csub-dot"></span>
  </button>
  <button class="csub-btn" data-csub="trading" onclick="setCockpitSub('trading')">
    <span class="csub-icon">📊</span>
    <span class="csub-label">Trading</span>
    <span class="csub-dot"></span>
  </button>
  <button class="csub-btn" data-csub="backup" onclick="setCockpitSub('backup')">
    <span class="csub-icon">🔋</span>
    <span class="csub-label">Backup</span>
    <span class="csub-dot"></span>
  </button>
</div>

<div id="csub-live" style="display:none">

  <!-- Animated Power Flow -->
  <div class="card" style="padding:0;overflow:hidden;margin-bottom:16px">
    <div style="padding:12px 16px 4px;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:13px;font-weight:600;color:var(--text)">&#x26A1; Live Power Flow</span>
      <span style="font-size:11px;color:var(--text-dim)" id="flow-total-label">Total load: &#x2014; W</span>
    </div>
    <svg id="power-flow-svg" viewBox="0 0 700 440" preserveAspectRatio="xMidYMid meet"
         style="width:100%;max-height:440px;display:block">

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

  <!-- Metric Cards -->
  <div class="grid grid-4" style="margin-bottom:12px">
    <div class="card energy-solar">
      <div class="card-header">
        <span class="card-title">Solar Production</span>
        <span class="badge online" id="enphase-badge">online</span>
      </div>
      <div class="big-val c-solar" id="solar-w">—</div>
      <span class="big-unit">W</span>
      <div class="sub-val" id="solar-sub">Enphase IQ · 192.168.68.63</div>
    </div>

    <div class="card energy-battery">
      <div class="card-header">
        <span class="card-title">Battery</span>
        <span class="badge offline" id="tesla-badge">unconfigured</span>
      </div>
      <div class="big-val c-battery" id="battery-soe">—</div>
      <span class="big-unit">%</span>
      <div class="sub-val" id="battery-sub">Tesla Gateway · not found</div>
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
  <div class="row">
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
      <div class="sub-val" id="pool-status-line" style="margin-top:8px">—</div>
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

<div id="csub-microgrid" class="tablet-view" style="display:none">
  <div class="tab-status-bar" style="min-height:48px;gap:16px">
    <span class="sb-time" id="mc-time" style="font-size:1.4rem;font-weight:800">--:--</span>
    <span class="sb-rate off-peak" id="mc-rate" style="font-size:1.4rem">Off-Peak</span>
    <span id="mc-weather" style="opacity:0.7;font-size:1.4rem">Queen Creek, AZ</span>
    <span style="flex:1"></span>
    <span id="mc-banner-solar" style="color:#FFD700;font-weight:700;font-size:1.4rem">☀ — kW</span>
    <span id="mc-banner-load" style="color:#9B59B6;font-weight:700;font-size:1.4rem">🏠 — kW</span>
    <span id="mc-banner-grid" style="color:#3B82F6;font-weight:700;font-size:1.4rem">⚡ — kW</span>
    <span id="mc-banner-cost" style="color:#10b981;font-weight:700;font-size:1.4rem">$—/hr</span>
    <span id="mc-banner-coverage" style="color:#FFD700;font-weight:700;font-size:1.4rem">—% ☀</span>
    <span class="sb-grid up" id="mc-grid-status" style="font-size:1.4rem">Grid ✓</span>
    <span id="mc-island-badge" class="island-badge" style="display:none;font-size:1.4rem">⚡ ISLANDED</span>
  </div>
  <div class="mc-layout">
    <!-- LEFT — Sources -->
    <div class="mc-left">
      <div class="glass-card" id="mc-solar-card" style="border-color:rgba(255,215,0,0.3)">
        <span class="label-sm">Solar Production</span>
        <div class="hero-num" id="mc-solar-total-kw" style="color:#FFD700">--</div>
        <div style="font-size:0.85rem;color:rgba(255,255,255,0.4)">kW total</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 8px;margin-top:10px;font-size:0.78rem">
          <div style="opacity:0.55">Enphase</div><div style="opacity:0.55">SolarEdge</div>
          <div id="mc-enphase-sub" style="color:#FFD700;font-weight:600">--</div>
          <div id="mc-solaredge-sub" style="color:#FFC200;font-weight:600">--</div>
        </div>
        <canvas id="mc-solar-spark" class="sparkline" style="margin-top:8px"></canvas>
      </div>
      <div class="glass-card" id="mc-grid-card" style="border-color:rgba(59,130,246,0.3)">
        <span class="label-sm">SRP Grid</span>
        <div class="hero-num" id="mc-grid-kw" style="color:#3B82F6">—</div>
        <div style="font-size:0.85rem;color:rgba(255,255,255,0.4)">kW</div>
        <div id="mc-grid-direction" style="font-size:10px;opacity:0.5;margin-top:4px">—</div>
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
      <div class="glass-card" id="mc-home-card" style="flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column">
        <span class="label-sm">Home Panel</span>
        <div class="hero-num" id="mc-home-load-kw" style="color:#9B59B6">—</div>
        <div style="font-size:0.85rem;color:rgba(255,255,255,0.4)">kW total</div>
        <canvas id="mc-home-spark" class="sparkline" style="margin-top:8px;flex-shrink:0"></canvas>
        <div id="mc-home-circuits" style="margin-top:8px;font-size:0.75rem;overflow:hidden;flex:1"></div>
      </div>
      <div class="glass-card" id="mc-pool-card">
        <span class="label-sm">Pool Sub-Panel</span>
        <div class="hero-num" id="mc-pool-kw" style="color:#06b6d4">—</div>
        <div style="font-size:0.85rem;color:rgba(255,255,255,0.4)">kW</div>
        <div id="mc-pool-status" style="font-size:10px;opacity:0.5;margin-top:4px">—</div>
        <canvas id="mc-pool-spark" class="sparkline" style="margin-top:8px"></canvas>
      </div>
      <div class="glass-card" id="mc-truck-card" style="border-color:rgba(0,255,255,0.3)">
        <span class="label-sm">Cybertruck</span>
        <div class="hero-num" id="mc-truck-kw" style="color:#00FFFF">—</div>
        <div style="font-size:0.85rem;color:rgba(255,255,255,0.4)">kW</div>
        <div id="mc-truck-mode" style="font-size:10px;opacity:0.5;margin-top:4px">Idle</div>
        <canvas id="mc-truck-spark" class="sparkline" style="margin-top:8px"></canvas>
      </div>
    </div>
  </div>
</div><!-- /csub-microgrid -->

<div id="csub-trading" class="tablet-view" style="display:none">
  <div class="tab-status-bar" style="font-size:1.4rem;padding:6px 14px;gap:16px;min-height:48px;flex-wrap:wrap">
    <span id="td-time" style="font-weight:800">--:--</span>
    <span class="sb-rate off-peak" id="td-rate" style="font-size:1.1rem;padding:3px 8px">Off-Peak</span>
    <span id="td-weather" style="opacity:0.85">☀ --</span>
    <span style="flex:1"></span>
    <span style="font-size:0.85rem;opacity:0.45" id="td-last-update">--</span>
  </div>
  <div id="td-totals-bar" style="display:flex;gap:24px;padding:8px 16px;background:rgba(255,255,255,0.03);border-bottom:1px solid rgba(255,255,255,0.06);flex-shrink:0;flex-wrap:wrap;align-items:center">
    <div style="text-align:center"><div class="label-sm">Total Solar</div><div id="td-total-solar" style="color:#FFD700;font-size:1.2rem;font-weight:800">--</div></div>
    <div style="text-align:center"><div class="label-sm">Home Load</div><div id="td-total-load" style="color:#9B59B6;font-size:1.2rem;font-weight:800">--</div></div>
    <div style="text-align:center"><div class="label-sm">SRP Grid</div><div id="td-total-grid" style="color:#3B82F6;font-size:1.2rem;font-weight:800">--</div></div>
    <div style="text-align:center"><div class="label-sm">Solar Coverage</div><div id="td-total-coverage" style="color:#10b981;font-size:1.2rem;font-weight:800">--</div></div>
    <div style="text-align:center"><div class="label-sm">Cost/hr</div><div id="td-total-cost" style="color:#10b981;font-size:1.2rem;font-weight:800">--</div></div>
    <div style="text-align:center"><div class="label-sm">$/kWh</div><div style="color:#10b981;font-size:1.2rem;font-weight:800">$0.18</div></div>
  </div>
  <div class="td-layout">
    <div class="td-top">
      <!-- LEFT — Solar Production -->
      <div class="td-col">
        <div class="glass-card" style="flex-shrink:0">
          <span class="label-sm">Enphase Production</span>
          <div class="value-md" id="td-enphase-kw" style="color:#FFD700;font-size:2.4rem">— <span style="font-size:0.8rem;opacity:0.4">kW</span></div>
          <canvas class="sparkline" id="td-enphase-spark"></canvas>
        </div>
        <div class="glass-card" style="flex-shrink:0">
          <span class="label-sm">SolarEdge Production</span>
          <div class="value-md" id="td-solaredge-kw" style="color:#FFC200;font-size:2.4rem">— <span style="font-size:0.8rem;opacity:0.4">kW</span></div>
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
      <div class="glass-card" style="padding:10px 14px">
        <div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap">
          <div>
            <span class="label-sm">15-min Demand</span>
            <div class="value-md" id="td-demand-15m" style="font-size:2.2rem">— <span style="font-size:0.8rem;opacity:0.4">kW</span></div>
          </div>
          <div>
            <span class="label-sm">Session Peak</span>
            <div class="value-md" id="td-peak-proj" style="font-size:2.2rem">— <span style="font-size:0.8rem;opacity:0.4">kW</span></div>
          </div>
          <div style="text-align:center">
            <span class="label-sm">Cost/hr</span>
            <div id="td-cost-hr" style="color:#10b981;font-size:2.2rem;font-weight:700">--</div>
          </div>
          <div style="text-align:center">
            <span class="label-sm">Solar Coverage</span>
            <div id="td-solar-coverage" style="color:#FFD700;font-size:2.2rem;font-weight:700">--</div>
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

<div id="csub-backup" class="tablet-view" style="display:none">
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
      <span class="badge" id="pc-spa-badge" style="margin-top:4px">—</span>
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
      <div class="pc-stat-card">
        <div class="pc-stat-hdr">
          <span class="pc-section-lbl">POOL</span>
          <span class="badge" id="pool-body-badge">—</span>
        </div>
        <div class="pc-stat-temp" id="pc-pool-temp">—°F</div>
        <div class="pc-stat-sub" id="pc-pool-setpoint">Setpoint: —</div>
        <div class="pc-stat-sub" id="pc-pool-heat">Heat: —</div>
        <div style="margin-top:10px;display:flex;gap:6px">
          <button class="btn primary" onclick="pentairSet('C0006',{STATUS:'ON'})">Pool ON</button>
          <button class="btn danger"  onclick="pentairSet('C0006',{STATUS:'OFF'})">Pool OFF</button>
        </div>
      </div>

      <!-- VSF Pump -->
      <div class="pc-stat-card">
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
      <div class="pc-stat-card">
        <div class="pc-stat-hdr">
          <span class="pc-section-lbl">GAS HEATER</span>
          <span class="badge" id="pc-heater-badge">—</span>
        </div>
        <div class="pc-stat-sub" id="pc-heater-status">Status: —</div>
        <div style="margin-top:10px;display:flex;gap:6px">
          <button class="btn primary" onclick="pentairSet('H0001',{STATUS:'ON'})">Enable</button>
          <button class="btn danger"  onclick="pentairSet('H0001',{STATUS:'OFF'})">Disable</button>
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
      <div class="device-detail">Vehicle telemetry via Fleet API — Phase 2</div>
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

  <div class="section-title" style="margin-top:16px">Vehicle Telemetry</div>
  <div class="card" style="border-color:var(--border)">
    <div class="card-header">
      <span class="card-title">Cybertruck Fleet Data</span>
      <span class="badge warning">Phase 2</span>
    </div>
    <div style="color:var(--text-dim);font-size:11px;margin-bottom:16px">
      Fleet API integration — requires Tesla Fleet API credentials (Phase 2)
    </div>
    <div class="grid grid-4">
      <div class="card" style="opacity:.4;pointer-events:none;background:var(--surface2)">
        <div class="card-title" style="margin-bottom:8px">Battery SOC</div>
        <div class="big-val" style="color:var(--battery)">—</div><span class="big-unit">%</span>
        <div class="sub-val">Fleet API · Phase 2</div>
      </div>
      <div class="card" style="opacity:.4;pointer-events:none;background:var(--surface2)">
        <div class="card-title" style="margin-bottom:8px">Range</div>
        <div class="big-val" style="color:var(--text-dim)">—</div><span class="big-unit">mi</span>
        <div class="sub-val">Fleet API · Phase 2</div>
      </div>
      <div class="card" style="opacity:.4;pointer-events:none;background:var(--surface2)">
        <div class="card-title" style="margin-bottom:8px">Charge Limit</div>
        <div class="big-val" style="color:var(--text-dim)">—</div><span class="big-unit">%</span>
        <div class="sub-val">Fleet API · Phase 2</div>
      </div>
      <div class="card" style="opacity:.4;pointer-events:none;background:var(--surface2)">
        <div class="card-title" style="margin-bottom:8px">Plug Status</div>
        <div class="big-val" style="color:var(--text-dim);font-size:18px">—</div>
        <div class="sub-val">Fleet API · Phase 2</div>
      </div>
    </div>
  </div>

</div><!-- /cybertruck -->


<!-- ═══ CAMERAS ══════════════════════════════════════════════════════════════ -->
<div id="view-cameras" class="view">
  <div class="section-title">Security Cameras</div>
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
  <div id="camera-grid" class="grid grid-2" style="margin-bottom:16px"></div>
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

<script>
const views = ['energy','climate','pool','entertainment','cameras','appliances','settings','devices','cockpit','solar','span','tesla-energy','cybertruck','home-control','sprinklers','roku'];
const _energySubs = ['cockpit','solar','span','tesla-energy','cybertruck'];
const _climateSubs = ['home-control','sprinklers'];
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
  document.querySelectorAll('#view-energy .sub-nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('onclick') && btn.getAttribute('onclick').includes("'"+name+"'"));
  });
  if (name === 'cockpit') {
    var savedSub = localStorage.getItem('jarvis-cockpit-sub') || 'microgrid';
    setTimeout(function() { setCockpitSub(savedSub); }, 0);
  }
}

function showClimateSub(name) {
  _curClimateSub = name;
  _climateSubs.forEach(s => {
    const el = document.getElementById('view-'+s);
    if (el) el.style.display = (s === name) ? 'block' : 'none';
  });
  document.querySelectorAll('#view-climate .sub-nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('onclick') && btn.getAttribute('onclick').includes("'"+name+"'"));
  });
}

function showEntertainmentSub(name) {
  const el = document.getElementById('view-roku');
  if (el) el.style.display = 'block';
  document.querySelectorAll('#view-entertainment .sub-nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('onclick') && btn.getAttribute('onclick').includes("'"+name+"'"));
  });
}
function toggleNav() {
  const nav = document.getElementById('nav-links');
  nav.classList.toggle('open');
}
// Close nav when a view is selected (mobile UX)
document.addEventListener('click', function(e) {
  if (e.target.closest('#nav-links') && e.target.tagName === 'BUTTON') {
    const nav = document.getElementById('nav-links');
    if (window.innerWidth <= 768) nav.classList.remove('open');
  }
});

function showView(v) {
  // Hide all top-level views
  views.forEach(id => {
    const el = document.getElementById('view-'+id);
    if (el) el.style.display = 'none';
  });
  // Also hide energy/climate subs
  _energySubs.forEach(s => { const el = document.getElementById('view-'+s); if(el) el.style.display='none'; });
  _climateSubs.forEach(s => { const el = document.getElementById('view-'+s); if(el) el.style.display='none'; });
  const rokuEl = document.getElementById('view-roku');
  if (rokuEl) rokuEl.style.display = 'none';

  // Show requested view
  const target = document.getElementById('view-'+v);
  if (target) target.style.display = 'block';

  // Handle grouped views
  if (v === 'energy') showEnergySub(_curEnergySub);
  if (v === 'climate') showClimateSub(_curClimateSub || 'home-control');
  if (v === 'thermostat') { const el = document.getElementById('view-home-control'); if(el) el.style.display='block'; }
  if (v === 'sprinklers') { const el = document.getElementById('view-sprinklers'); if(el) el.style.display='block'; }
  if (v === 'entertainment') {
    showEntertainmentSub('roku');
    // Use already-loaded SSE state — no separate fetch
    const _rk = (window._lastState||{}).roku || window._lastRoku || [];
    if (_rk.length) try { renderRoku(_rk); } catch(e) {}
  }

  // Update nav active state
  document.querySelectorAll('#nav-links button').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('onclick') && btn.getAttribute('onclick').includes("'"+v+"'"));
  });
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
  document.getElementById('battery-soe').textContent = td.soe != null ? Math.round(td.soe) : '—';
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
  document.getElementById('tesla-badge').textContent = td.status||'—';
  document.getElementById('tesla-badge').className = 'badge ' + statusColor(td.status);
  document.getElementById('pentair-badge').textContent = pd.status||'—';
  document.getElementById('pentair-badge').className = 'badge ' + statusColor(pd.status);

  // Pool summary in cockpit
  const pump = (pd.pool && pd) ? pd.pump||{} : {};
  const pool = pd.pool||{};
  document.getElementById('pool-temp').textContent = pool.temp || '—';
  document.getElementById('pump-rpm').textContent  = pump.rpm != null ? pump.rpm : '—';
  document.getElementById('pump-w').textContent    = pump.power_w != null ? pump.power_w : '—';
  document.getElementById('pool-status-line').textContent =
    `Pool: ${pool.status||'?'} · Spa: ${(pd.spa||{}).status||'?'} · Heater: ${(pd.heater||{}).status||'?'}`;

  // Solar sub
  document.getElementById('solar-sub').textContent =
    ed.status==='online'||ed.status==='partial' ? `Enphase D8.3.5167 · ${ed.serial||'202324023651'}` : 'Enphase · needs token';
  document.getElementById('battery-sub').textContent = td.status==='online' ? 'Tesla Gateway 3V · online' : 'Tesla Gateway 3V · offline';

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
  const pcSpaBadge = document.getElementById('pc-spa-badge');
  if (pcSpaBadge) { pcSpaBadge.textContent = spa.status||'?'; pcSpaBadge.className = 'badge ' + (spaOn?'online':'offline'); }
  const pcSpaTemp = document.getElementById('pc-spa-temp');
  if (pcSpaTemp) pcSpaTemp.innerHTML = spa.temp ? spa.temp+'<sup>°F</sup>' : '—<sup>°F</sup>';
  const pcSpaSp = document.getElementById('pc-spa-setpoint');
  if (pcSpaSp) pcSpaSp.textContent = `Target: ${spa.setpoint_lo||'?'} °F`;

  // Pump card
  const pumpOn = pump.status && pump.status !== 'OFF' && pump.status !== '?';
  const pcPumpBadge = document.getElementById('pc-pump-badge');
  if (pcPumpBadge) { pcPumpBadge.textContent = pump.status||'?'; pcPumpBadge.className = 'badge ' + (pumpOn?'online':'offline'); }
  const pcPumpRpm = document.getElementById('pc-pump-rpm');
  if (pcPumpRpm) pcPumpRpm.textContent = pump.rpm != null ? pump.rpm : '—';
  const pcPumpGpm = document.getElementById('pc-pump-gpm-val');
  if (pcPumpGpm) pcPumpGpm.textContent = pump.gpm != null ? pump.gpm : '—';
  const pcPumpW = document.getElementById('pc-pump-w-val');
  if (pcPumpW) pcPumpW.textContent = pump.power_w != null ? pump.power_w : '—';

  // Heater card
  const heaterSt = (pd.heater||{}).status||'—';
  const heaterOn = heaterSt === 'ON';
  const pcHeaterBadge = document.getElementById('pc-heater-badge');
  if (pcHeaterBadge) { pcHeaterBadge.textContent = heaterSt; pcHeaterBadge.className = 'badge ' + (heaterOn?'online':'offline'); }
  const pcHeaterSt = document.getElementById('pc-heater-status');
  if (pcHeaterSt) pcHeaterSt.textContent = `Status: ${heaterSt}`;

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
    ctWcBadge.textContent = wc.charge_status || wc.status || '—';
    const csMap = {charging:'online', complete:'partial', standby:'offline', fault:'error'};
    ctWcBadge.className = 'badge ' + (csMap[wc.charge_status] || statusColor(wc.status));
  }

  const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  setEl('ct-charge-status', wc.charge_status || '—');
  setEl('ct-vehicle',       wc.vehicle_connected ? '🔌 connected' : '— disconnected');
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
  if (n.includes('upstairs'))   return 'upstairs';
  if (n.includes('downstairs')) return 'downstairs';
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


function renderCameras(cameras) {
  const grid = document.getElementById('camera-grid');
  const setupCard = document.getElementById('cameras-setup-card');
  if (!grid) return;
  if (!cameras || cameras.length === 0) {
    grid.innerHTML = '';
    if (setupCard) setupCard.style.display = 'block';
    return;
  }
  if (setupCard) setupCard.style.display = 'none';

  // Update cache for modal
  cameras.forEach(cam => { _camDataCache[cam.mac || cam.type] = cam; });

  // Build HTML for each camera
  grid.innerHTML = cameras.map(cam => {
    const mac        = cam.mac || cam.type;
    const badgeClass = cam.type === 'wyze' ? 'badge-wyze' : 'badge-ring';
    const icon       = cam.type === 'wyze' ? '📷' : '🔔';
    const isOnline   = cam.status === 'online';
    const lastInfo   = cam.last_motion
      ? `Last motion: ${cam.last_motion}`
      : (cam.last_seen ? `Last seen: ${cam.last_seen}` : '');
    const liveDot = isOnline ? '<span class="cam-live-dot" title="Live"></span>' : '';
    const statusBadge = `<span class="badge ${isOnline?'online':'offline'}">${cam.status||'?'}</span>`;
    const rtspId    = _getRtspId(cam);
    const isFront   = mac === _FRONT_SIDE_MAC;

    let thumbHtml, sourceBadge;
    if (rtspId) {
      // RTSP — poll /frame every 500ms (single JPEG per request, no multipart needed)
      thumbHtml = `<img id="cam-img-${mac}" class="camera-thumb"
           src="/api/camera/${rtspId}/frame?t=${Date.now()}"
           onerror="this.style.display='none';document.getElementById('cam-ph-${mac}').style.display='flex'"
           onload="document.getElementById('cam-ph-${mac}').style.display='none';this.style.display='block'"
           alt="${cam.name}">
      <div id="cam-ph-${mac}" class="camera-thumb-placeholder" style="display:flex">${icon}<div style="font-size:10px;color:var(--text-dim)">Connecting…</div></div>`;
      sourceBadge = `<span class="badge" style="background:rgba(0,255,128,.15);color:#00ff80;margin-right:6px">LIVE</span>`;
    } else if (isFront) {
      // No RTSP — snapshot with fast refresh every 5 s
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
        <div class="camera-name">
          <span>${liveDot}${cam.name}</span>
          ${statusBadge}
        </div>
        <div class="camera-meta">
          ${sourceBadge}${lastInfo}
        </div>
      </div>
    </div>`;
  }).join('');

  // Auto-refresh intervals: 500ms for RTSP, 5s for front-side snapshot, 30s otherwise
  cameras.forEach(cam => {
    const mac    = cam.mac || cam.type;
    const rtspId = _getRtspId(cam);
    if (!_camRefreshTimers[mac]) {
      const interval = rtspId ? 500 : (mac === _FRONT_SIDE_MAC ? 5000 : 30000);
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
}

// ══ Nest helpers ══════════════════════════════════════════════════════════════
let _nestSetpoints = {};  // device_name → current cool setpoint

function nestAdjust(delta, deviceName) {
  if (!_nestSetpoints[deviceName]) _nestSetpoints[deviceName] = 70;
  _nestSetpoints[deviceName] += delta;
  const sp = _nestSetpoints[deviceName];
  const safeId = deviceName.replace(/[^a-z0-9]/gi, '_');
  const el = document.getElementById('nest-sp-' + safeId);
  if (el) el.textContent = sp;
  fetch('/api/nest/setpoint', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({device_name: deviceName, cool_f: sp})
  }).then(r=>r.json()).then(d => {
    if (d.ok) toast('✓ ' + sp + '°F → ' + deviceName.split('/').pop().slice(0,8));
    else toast('✗ ' + (d.error||'Error'), 5000);
  }).catch(e => toast('✗ ' + e, 5000));
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
      const spVal    = t.cool_setpoint_f || t.heat_setpoint_f || 70;
      if (!_nestSetpoints[t.device_name]) _nestSetpoints[t.device_name] = Math.round(spVal);
      const devEnc   = encodeURIComponent(t.device_name).replace(/'/g, '%27');
      return `
      <div class="card" style="min-width:280px;flex:1">
        <div class="card-header">
          <span class="card-title">🌡️ ${t.name}</span>
          <span class="badge ${statusColor(t.status)}">${t.status}</span>
        </div>
        <div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-end;margin-bottom:14px">
          <div>
            <div class="sub-val">Current Temp</div>
            <div class="big-val c-pool" style="font-size:36px">${Math.round(t.temp_f)}<span class="big-unit">°F</span></div>
          </div>
          <div>
            <div class="sub-val">Cool Setpoint</div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:4px">
              <button class="btn" onclick="nestAdjust(-1, decodeURIComponent('${devEnc}'))" style="font-size:16px;padding:4px 12px">−</button>
              <span class="big-val" id="nest-sp-${safeId}" style="font-size:26px">${Math.round(spVal)}</span>
              <span class="big-unit">°F</span>
              <button class="btn" onclick="nestAdjust(1, decodeURIComponent('${devEnc}'))" style="font-size:16px;padding:4px 12px">+</button>
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
  const isSummer  = month >= 5 && month <= 8; // Jun-Sep
  if (isSummer && isWeekday) {
    if (h >= 15 && h < 20) return { label:'On-Peak',   cls:'peak',     rate:0.23 };
    if ((h >= 9 && h < 15) || (h >= 20 && h < 23)) return { label:'Shoulder', cls:'shoulder',  rate:0.18 };
    return { label:'Off-Peak', cls:'off-peak', rate:0.10 };
  }
  if (!isSummer && isWeekday) {
    if (h >= 5 && h < 21) return { label:'On-Peak', cls:'shoulder', rate:0.18 };
    return { label:'Off-Peak', cls:'off-peak', rate:0.10 };
  }
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

function pushHist(arr, v) { arr.push(v); if(arr.length > SPARK_LEN) arr.shift(); }

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

// Swipe gesture support for cockpit sub-view switching
(function() {
  let ts=0, tx=0;
  const cockpitSubs = ['live','microgrid','trading','backup'];
  function curSub() {
    return cockpitSubs.find(s => { var el=document.getElementById('csub-'+s); return el && el.style.display !== 'none'; });
  }
  document.addEventListener('touchstart', e=>{ts=e.touches[0].clientX; tx=e.touches[0].clientY;}, {passive:true});
  document.addEventListener('touchend', e=>{
    const dx=e.changedTouches[0].clientX-ts, dy=e.changedTouches[0].clientY-tx;
    if(Math.abs(dx)<60||Math.abs(dy)>Math.abs(dx)*0.7) return;
    const cockpitEl = document.getElementById('view-cockpit');
    if(!cockpitEl || cockpitEl.style.display==='none') return;
    const cur = curSub(); if(!cur) return;
    const idx = cockpitSubs.indexOf(cur);
    if(dx<0 && idx<cockpitSubs.length-1) setCockpitSub(cockpitSubs[idx+1]);
    if(dx>0 && idx>0) setCockpitSub(cockpitSubs[idx-1]);
  }, {passive:true});
  // Keyboard arrow keys for cockpit sub-view switching
  document.addEventListener('keydown', e=>{
    const cockpitEl = document.getElementById('view-cockpit');
    if(!cockpitEl || cockpitEl.style.display==='none') return;
    const cur = curSub(); if(!cur) return;
    const idx = cockpitSubs.indexOf(cur);
    if(e.key==='ArrowRight' && idx<cockpitSubs.length-1) setCockpitSub(cockpitSubs[idx+1]);
    if(e.key==='ArrowLeft' && idx>0) setCockpitSub(cockpitSubs[idx-1]);
  });
})();

// Flag for SPAN token (set by Python template)
const SPAN_TOKEN_CONFIGURED = {{ 'true' if config_span_token else 'false' }};

// SSE connection
const evtSrc = new EventSource('/api/stream');
evtSrc.onmessage = e => { try { renderState(JSON.parse(e.data)); } catch(err) { console.error(err); } };
evtSrc.onerror = () => console.warn('SSE disconnected — retrying...');

// Initial load — start on Energy Cockpit
showView('energy');
fetch('/api/state').then(r=>r.json()).then(renderState).catch(console.error);

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

// ── Cockpit Sub-Nav ──────────────────────────────────────────────────
function setCockpitSub(sub) {
  // Update sub-nav buttons
  document.querySelectorAll('.csub-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.csub === sub);
  });
  // Show/hide sub-content panels
  ['live', 'microgrid', 'trading', 'backup'].forEach(function(s) {
    var el = document.getElementById('csub-' + s);
    if (el) el.style.display = s === sub ? '' : 'none';
  });
  // Persist
  localStorage.setItem('jarvis-cockpit-sub', sub);
}

// Init: restore last sub or default to microgrid
(function() {
  var _initSub = localStorage.getItem('jarvis-cockpit-sub') || 'microgrid';
  setCockpitSub(_initSub);
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

    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()

    _start_rtsp_threads()   # start background RTSP frame capture

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
