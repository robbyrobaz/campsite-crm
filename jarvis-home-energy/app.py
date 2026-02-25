#!/usr/bin/env python3
"""
Jarvis Home Energy OS — Unified Home Energy Dashboard
Covers: SPAN Panel · Enphase Solar · Pentair Pool · Tesla Powerwall
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
    PENTAIR_HOST = "192.168.68.91"; PENTAIR_PORT = 6681
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

app = Flask(__name__)

# ── Shared State ──────────────────────────────────────────────────────────────
_state_lock = threading.Lock()
_state = {
    "ts": 0,
    "span": {"status": "unconfigured", "door": "?", "uptime": 0, "grid_power": 0, "circuits": []},
    "enphase": {"status": "unconfigured", "production_w": 0, "consumption_w": 0, "net_w": 0, "firmware": "D8.3.5167"},
    "pentair": {"status": "offline", "pool": {}, "spa": {}, "pump": {}, "heater": {}, "circuits": []},
    "tesla": {"status": "unconfigured", "soe": 0, "solar_w": 0, "battery_w": 0, "grid_w": 0, "load_w": 0},
    "wall_connector": {"status": "unconfigured", "vehicle_connected": False, "charging_w": 0, "session_energy_wh": 0, "grid_v": 0, "pcba_temp_c": 0},
    "summary": {"solar_w": 0, "load_w": 0, "battery_w": 0, "grid_w": 0, "net_savings_today": 0},
    "cameras": [],  # list of {name, mac, type, status, last_seen, last_motion, snapshot_path}
    "nest": {"status": "unconfigured", "temp_f": 0, "setpoint_f": 0, "mode": "off", "hvac_state": "idle", "humidity": 0},
    "bhyve": {"status": "unconfigured", "devices": [], "zones": []},
}
_sse_subscribers = []
_sse_lock = threading.Lock()

# Wyze — single cached client (login once, reuse across polls + snapshots)
_wyze_client = None
_wyze_client_lock = threading.Lock()
_wyze_next_retry = 0   # epoch seconds — don't retry auth before this time
_camera_poll_counter = 0  # throttle: refresh camera list every 60s (every 12 ticks at 5s)

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
            }
        return True
    except Exception as e:
        log.warning("Wall Connector poll error: %s", e)
        with _state_lock:
            _state["wall_connector"]["status"] = "error"
        return False


# ── Tesla Fleet API Adapter ───────────────────────────────────────────────────
# Uses teslapy (OAuth already completed) — no local Gateway credentials needed.
# Cache: /home/rob/.openclaw/workspace/jarvis-home-energy/tesla_cache.json

_TESLA_CACHE_FILE = "/home/rob/.openclaw/workspace/jarvis-home-energy/tesla_cache.json"
_TESLA_FLEET_BASE = "https://owner-api.teslamotors.com/api/1"
_tesla_fleet_lock = threading.Lock()


def _get_tesla_fleet_token():
    """Return a valid Fleet API access_token, auto-refreshing via teslapy if expired."""
    with _tesla_fleet_lock:
        t = teslapy.Tesla("rob.hartwig@gmail.com", cache_file=_TESLA_CACHE_FILE)
        try:
            # teslapy.fetch_token() refreshes automatically when the access_token is expired
            if not t.authorized:
                raise RuntimeError("Tesla OAuth not authorized — run oauth flow first")
            # Touch the token to trigger refresh if needed
            t.fetch_token()
            token = t.token["access_token"]
        finally:
            t.close()
        return token


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
    global _ring_next_retry
    if RING_EMAIL and RING_PASSWORD and time.time() >= _ring_next_retry:
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


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  POLLING LOOP                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def _poll_loop():
    import concurrent.futures
    global _camera_poll_counter
    log.info("Polling loop started (interval=%ds, parallel)", POLL_INTERVAL_SECONDS)
    _camera_poll_counter = 11  # trigger camera poll on first tick
    while True:
        # Cameras: poll every 60s (every 12 ticks at 5s) — Wyze login is rate-limited
        _camera_poll_counter += 1
        poll_fns = [poll_pentair, poll_span, poll_enphase, poll_tesla, poll_wall_connector, poll_nest, poll_bhyve]
        if _camera_poll_counter >= 12:
            poll_fns.append(poll_cameras)
            _camera_poll_counter = 0
        # Run all device polls concurrently — Pentair can take 45s, don't let it block solar/SPAN
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
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
    global BHYVE_EMAIL, BHYVE_PASSWORD, _bhyve_token
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
        # Reset token so next poll re-authenticates
        with _bhyve_token_lock:
            _bhyve_token = None
        return jsonify({"ok": True})
    except Exception as e:
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
<title>Jarvis — Home Energy OS</title>
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
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 20px; display: flex; align-items: center; gap: 20px; height: 52px; }
  .logo { font-size: 16px; font-weight: 700; letter-spacing: .05em; color: var(--solar); }
  .logo span { color: var(--text-dim); }
  nav { display: flex; gap: 4px; flex: 1; }
  nav button { background: transparent; border: none; color: var(--text-dim); cursor: pointer; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-family: inherit; transition: all .15s; }
  nav button.active, nav button:hover { background: var(--surface2); color: var(--text); }
  .status-bar { display: flex; gap: 14px; align-items: center; }
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

  /* Pool */
  .pool-body { display: flex; gap: 12px; flex-wrap: wrap; }
  .pool-card { background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; flex: 1; min-width: 160px; }
  .pool-temp { font-size: 36px; font-weight: 700; color: var(--pool); }
  .pool-meta { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
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
  /* Modal overlay */
  #bhyve-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.7); z-index:1000; align-items:center; justify-content:center; }
  #bhyve-modal.show { display:flex; }
  .modal-box { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:24px; min-width:280px; }
  .modal-title { font-size:14px; font-weight:700; margin-bottom:16px; }
  .modal-dur-btns { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; }
  .dur-btn { background:var(--surface2); border:1px solid var(--border); color:var(--text); cursor:pointer; padding:8px 16px; border-radius:8px; font-family:inherit; font-size:12px; transition:all .15s; }
  .dur-btn:hover, .dur-btn.selected { background:rgba(16,185,129,.2); border-color:var(--online); color:var(--online); }
  .modal-actions { display:flex; gap:8px; justify-content:flex-end; }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head>
<body>

<header>
  <div class="logo">⚡ JARVIS <span>Home Energy OS</span></div>
  <nav>
    <button class="active" onclick="showView('cockpit')">Energy Cockpit</button>
    <button onclick="showView('solar')">☀️ Solar</button>
    <button onclick="showView('span')">SPAN Circuits</button>
    <button onclick="showView('pool')">Pool Control</button>
    <button onclick="showView('devices')">Devices</button>
    <button onclick="showView('tesla-energy')">Tesla Energy</button>
    <button onclick="showView('cybertruck')">Cybertruck</button>
    <button onclick="showView('cameras')">Cameras</button>
    <button onclick="showView('home-control')">Home Control</button>
    <button onclick="showView('sprinklers')">Sprinklers</button>
    <button onclick="showView('settings')">Settings</button>
  </nav>
  <div class="status-bar">
    <div id="span-dot" class="dot offline" title="SPAN Panel"></div>
    <div id="enphase-dot" class="dot offline" title="Enphase"></div>
    <div id="pentair-dot" class="dot offline" title="Pentair"></div>
    <div id="tesla-dot" class="dot offline" title="Tesla Gateway"></div>
    <div id="wc-dot" class="dot offline" title="Wall Connector"></div>
    <span class="ts" id="ts">—</span>
  </div>
</header>

<main>

<!-- ═══ ENERGY COCKPIT ═══════════════════════════════════════════════════════ -->
<div id="view-cockpit" class="view active">

  <!-- Animated Power Flow -->
  <div class="card" style="padding:0;overflow:hidden;margin-bottom:16px">
    <div style="padding:12px 16px 4px;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:13px;font-weight:600;color:var(--text)">&#x26A1; Live Power Flow</span>
      <span style="font-size:11px;color:var(--text-dim)" id="flow-total-label">Total load: &#x2014; W</span>
    </div>
    <svg id="power-flow-svg" viewBox="0 0 700 320" preserveAspectRatio="xMidYMid meet"
         style="width:100%;max-height:320px;display:block">

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
          <path d="M0,0 L6,3 L0,6 Z" fill="#6b7280"/>
        </marker>
        <marker id="arr-pool" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#06b6d4"/>
        </marker>
      </defs>

      <!-- ── PATHS (behind nodes) ── -->

      <!-- SRP Grid → Tesla Gateway (bezier) -->
      <path id="path-grid-gw" d="M 535,82 C 535,118 462,130 462,148"
            stroke="#f97316" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-grid)"/>

      <!-- Tesla Gateway → SPAN Panel (bezier) -->
      <path id="path-gw-span" d="M 328,166 C 295,166 270,180 248,182"
            stroke="#f97316" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-grid)"/>

      <!-- Bridge: SRP Grid → SPAN direct (Tesla offline fallback) -->
      <path id="path-grid-span" d="M 533,82 C 510,107 310,103 250,160"
            stroke="#f97316" stroke-width="2" fill="none" opacity="0"
            stroke-dasharray="6 8" marker-end="url(#arr-bridge)"/>

      <!-- Solar 1 (Enphase) → SPAN Panel (bezier) -->
      <path id="path-solar-span" d="M 130,82 C 130,115 190,118 190,150"
            stroke="#f59e0b" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-solar)"/>

      <!-- Solar 2 (SolarEdge) → SPAN Panel (bezier) -->
      <path id="path-solar2-span" d="M 130,160 C 150,165 175,160 190,150"
            stroke="#f59e0b" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-solar)"/>

      <!-- Home Panel → Pool -->
      <path id="path-home-pool" d="M 190,218 C 190,238 95,238 95,248"
            stroke="#06b6d4" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-pool)"/>

      <!-- Tesla Gateway → CT Charger (bezier) -->
      <path id="path-gw-ct" d="M 395,202 C 435,228 476,242 515,248"
            stroke="#22d3ee" stroke-width="3" fill="none" opacity="0.9"
            stroke-dasharray="10 5" marker-end="url(#arr-ev)"/>

      <!-- Bridge: SRP Grid → CT Charger direct (Tesla GW offline fallback) -->
      <path id="path-grid-ct" d="M 535,82 C 535,160 515,200 515,248"
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
        <circle r="4.5" fill="#f97316" filter="url(#pf-glow)">
          <animateMotion dur="1.5s" begin="0s" repeatCount="indefinite"><mpath href="#path-gw-span"/></animateMotion>
        </circle>
        <circle r="3" fill="#f97316" opacity="0.65">
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

      <!-- Solar 1: Enphase node (top-left) -->
      <g id="node-solar" transform="translate(75,22)" style="cursor:pointer" onclick="showView('solar')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="110" height="60" fill="#1c1917" stroke="#f59e0b" stroke-width="1.5"/>
        <text x="55" y="20" text-anchor="middle" font-size="17" fill="#f59e0b">&#x2600;&#xFE0F;</text>
        <text x="55" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">ENPHASE</text>
        <text id="lbl-solar" x="55" y="53" text-anchor="middle" font-size="13" fill="#f59e0b" font-weight="bold" font-family="sans-serif">&#x2014; W</text>
      </g>

      <!-- Solar 2: SolarEdge node (below Enphase) -->
      <g id="node-solar2" transform="translate(75,100)" style="cursor:pointer" onclick="showView('solar')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="110" height="60" fill="#1c1917" stroke="#f59e0b" stroke-width="1.5"/>
        <text x="55" y="20" text-anchor="middle" font-size="17" fill="#f59e0b">&#x2600;&#xFE0F;</text>
        <text x="55" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">SOLAREDGE</text>
        <text id="lbl-solar2" x="55" y="53" text-anchor="middle" font-size="13" fill="#f59e0b" font-weight="bold" font-family="sans-serif">&#x2014; W</text>
      </g>

      <!-- SRP Grid node (top-right) -->
      <g id="node-grid" transform="translate(480,22)" style="cursor:pointer" onclick="showView('tesla-energy')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect id="rect-grid" rx="12" ry="12" width="110" height="60" fill="#1c1917" stroke="#f97316" stroke-width="1.5"/>
        <text x="55" y="20" text-anchor="middle" font-size="17" fill="#f97316">&#x1F50C;</text>
        <text x="55" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">SRP GRID</text>
        <text id="lbl-grid" x="55" y="53" text-anchor="middle" font-size="13" fill="#f97316" font-weight="bold" font-family="sans-serif">&#x2014; W</text>
        <text id="lbl-grid-sub" x="55" y="70" text-anchor="middle" font-size="8" fill="#a3a3a3" font-family="sans-serif" visibility="hidden">&#x2014;</text>
      </g>

      <!-- Tesla Gateway node (center) -->
      <g id="node-gateway" transform="translate(328,130)" style="cursor:pointer" onclick="showView('tesla-energy')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="134" height="72" fill="#1c1917" stroke="#3b82f6" stroke-width="1.5"/>
        <text x="67" y="20" text-anchor="middle" font-size="17" fill="#3b82f6">&#x1F50B;</text>
        <text x="67" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">TESLA GATEWAY V2</text>
        <text id="lbl-gw" x="67" y="53" text-anchor="middle" font-size="12" fill="#94a3b8" font-family="sans-serif">&#x2014;</text>
        <text id="lbl-gw-soe" x="67" y="66" text-anchor="middle" font-size="10" fill="#60a5fa" font-family="sans-serif">&#x2014;</text>
      </g>

      <!-- Home Panel node (mid-left) — merged SPAN + House Load -->
      <g id="node-home" transform="translate(132,150)" style="cursor:pointer" onclick="showView('span')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="116" height="68" fill="#1c1917" stroke="#8b5cf6" stroke-width="1.5"/>
        <text x="58" y="20" text-anchor="middle" font-size="17" fill="#8b5cf6">&#x1F3E0;</text>
        <text x="58" y="35" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">HOME PANEL</text>
        <text id="lbl-home" x="58" y="55" text-anchor="middle" font-size="13" fill="#8b5cf6" font-weight="bold" font-family="sans-serif">&#x2014; W</text>
      </g>

      <!-- CT Charger node (mid-right-bottom) -->
      <g id="node-ct" transform="translate(455,248)" style="cursor:pointer" onclick="showView('cybertruck')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="120" height="60" fill="#1c1917" stroke="#22d3ee" stroke-width="1.5"/>
        <text x="60" y="20" text-anchor="middle" font-size="17" fill="#22d3ee">&#x1F697;</text>
        <text x="60" y="34" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">CYBERTRUCK CT</text>
        <text id="lbl-ct" x="60" y="52" text-anchor="middle" font-size="12" fill="#22d3ee" font-weight="bold" font-family="sans-serif">idle</text>
      </g>

      <!-- Pool node (bottom-left) -->
      <g id="node-pool" transform="translate(40,248)" style="cursor:pointer" onclick="showView('pool')"
         onmouseover="this.style.opacity=0.75" onmouseout="this.style.opacity=1">
        <rect rx="12" ry="12" width="110" height="60" fill="#1c1917" stroke="#06b6d4" stroke-width="1.5"/>
        <text x="55" y="20" text-anchor="middle" font-size="17" fill="#06b6d4">&#x1F3CA;</text>
        <text x="55" y="34" text-anchor="middle" font-size="9" fill="#a3a3a3" font-family="sans-serif" letter-spacing="1">POOL</text>
        <text id="lbl-pool" x="55" y="52" text-anchor="middle" font-size="12" fill="#06b6d4" font-weight="bold" font-family="sans-serif">&#x2014; W</text>
      </g>

      <!-- Bridge mode label (shown when Tesla offline) -->
      <g id="pf-bridge-label" visibility="hidden">
        <rect x="248" y="89" rx="6" ry="6" width="165" height="17" fill="#1c1917" stroke="#f97316" stroke-width="0.8" stroke-dasharray="3 2" opacity="0.85"/>
        <text x="330" y="101" text-anchor="middle" font-size="8.5" fill="#f97316" font-family="sans-serif">&#x26A1; SPAN-bridged &#xB7; no Tesla GW</text>
      </g>

      <!-- Normal source label (shown when Tesla online) -->
      <g id="pf-source-label" visibility="visible">
        <text x="350" y="312" text-anchor="middle" font-size="9" fill="#4b5563" font-family="sans-serif">Jarvis bridges SPAN + Tesla Gateway data</text>
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
    <div class="card">
      <div class="card-header"><span class="card-title">Setup</span></div>
      <div class="sub-val" style="margin-bottom:8px">Token registration requires physical panel access:</div>
      <ol style="color:var(--text-dim);font-size:11px;padding-left:16px;line-height:2">
        <li>Open panel door</li>
        <li>Press door sensor button 3×</li>
        <li>Run: <code style="color:var(--solar)">python3 -c "from app import span_register; span_register()"</code></li>
        <li>Paste token into config.py → SPAN_TOKEN</li>
      </ol>
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
  <div class="section-title">Pentair IntelliCenter · 192.168.68.91</div>

  <div class="pool-body">
    <!-- Pool body -->
    <div class="pool-card">
      <div class="card-header">
        <span class="card-title">Pool</span>
        <span class="badge online" id="pool-body-badge">—</span>
      </div>
      <div class="pool-temp" id="pc-pool-temp">—°F</div>
      <div class="pool-meta" id="pc-pool-setpoint">Setpoint: — / — °F</div>
      <div class="pool-meta" id="pc-pool-heat">Heat: —</div>
    </div>

    <!-- Spa body -->
    <div class="pool-card">
      <div class="card-header">
        <span class="card-title">Spa</span>
        <span class="badge online" id="spa-body-badge">—</span>
      </div>
      <div class="pool-temp" id="pc-spa-temp">—°F</div>
      <div class="pool-meta" id="pc-spa-setpoint">Setpoint: — / — °F</div>
    </div>

    <!-- Pump -->
    <div class="pool-card">
      <div class="card-header"><span class="card-title">VSF Pump · PMP01</span></div>
      <div class="pool-temp c-pool" id="pc-pump-rpm">— RPM</div>
      <div class="pool-meta" id="pc-pump-gpm">— GPM · — W</div>
      <div class="pool-meta" id="pc-pump-status">—</div>
    </div>

    <!-- Heater -->
    <div class="pool-card">
      <div class="card-header"><span class="card-title">Gas Heater · H0001</span></div>
      <div class="pool-temp" id="pc-heater-status" style="font-size:22px">—</div>
      <div class="pool-meta">Status from IntelliCenter</div>
      <div style="margin-top:10px;display:flex;gap:8px">
        <button class="btn primary" onclick="pentairSet('H0001',{STATUS:'ON'})">Enable</button>
        <button class="btn danger" onclick="pentairSet('H0001',{STATUS:'OFF'})">Disable</button>
      </div>
    </div>
  </div>

  <!-- Circuit Control -->
  <div class="section-title" style="margin-top:16px">Circuits</div>
  <div class="card">
    <div id="pool-circuits"></div>
  </div>

  <!-- Quick Actions -->
  <div class="section-title" style="margin-top:12px">Quick Actions</div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <button class="btn primary" onclick="pentairSet('C0006',{STATUS:'ON'})">Pool ON</button>
    <button class="btn danger" onclick="pentairSet('C0006',{STATUS:'OFF'})">Pool OFF</button>
    <button class="btn primary" onclick="pentairSet('C0001',{STATUS:'ON'})">Spa ON</button>
    <button class="btn danger" onclick="pentairSet('C0001',{STATUS:'OFF'})">Spa OFF</button>
    <button class="btn" onclick="pentairSet('GRP01',{STATUS:'ON'})">All Lights ON</button>
    <button class="btn" onclick="pentairSet('GRP01',{STATUS:'OFF'})">All Lights OFF</button>
    <button class="btn primary" onclick="pentairSet('FTR01',{STATUS:'ON'})">Cleaner ON</button>
    <button class="btn danger" onclick="pentairSet('FTR01',{STATUS:'OFF'})">Cleaner OFF</button>
  </div>
</div><!-- /pool -->


<!-- ═══ DEVICES ══════════════════════════════════════════════════════════════ -->
<div id="view-devices" class="view">
  <div class="section-title">Discovered Devices</div>
  <div class="grid grid-2">

    <div class="card">
      <div class="device-card">
        <div class="device-icon">⚡</div>
        <div class="device-info">
          <div class="device-name">SPAN Panel <span class="badge" id="dev-span-badge">—</span></div>
          <div class="device-detail">span-nj-2307-006gl.local · 192.168.68.93:80</div>
          <div class="device-detail">Serial: nj-2307-006gl · FW: spanos2/r202603/05 · Model: 00200</div>
          <div class="device-detail" id="dev-span-door">Door: — · Uptime: —</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="device-card">
        <div class="device-icon">☀️</div>
        <div class="device-info">
          <div class="device-name">Enphase IQ Gateway <span class="badge" id="dev-enphase-badge">—</span></div>
          <div class="device-detail">envoy.local · 192.168.68.63:443</div>
          <div class="device-detail">Serial: 202324023651 · FW: D8.3.5167 · imeter: true</div>
          <div class="device-detail" id="dev-enphase-prod">Production: —</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="device-card">
        <div class="device-icon">🏊</div>
        <div class="device-info">
          <div class="device-name">Pentair IntelliCenter <span class="badge online">online</span></div>
          <div class="device-detail">pentair.local · 192.168.68.91:6681 (TCP) / :6680 (WS)</div>
          <div class="device-detail">Bodies: Pool (B1101), Spa (B1202)</div>
          <div class="device-detail">Pump: VSF (PMP01) · Heater: Gas (H0001) · SWG: IntelliChlor</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="device-card">
        <div class="device-icon">🔋</div>
        <div class="device-info">
          <div class="device-name">Tesla Gateway V2 <span class="badge offline" id="tesla-gw-badge">not found</span></div>
          <div class="device-detail" id="tesla-gw-detail">Not found on 192.168.68.0/22 — set TESLA_HOST in config.py</div>
          <div class="device-detail">Auth: Bearer token · username=customer · password=last-5 of serial</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="device-card">
        <div class="device-icon">⚡</div>
        <div class="device-info">
          <div class="device-name">Tesla Wall Connector Gen 3 <span class="badge offline" id="wc-badge">—</span></div>
          <div class="device-detail">TeslaWallConnector_OEB496 · 192.168.68.87 · No auth</div>
          <div class="device-detail" id="wc-detail">—</div>
          <div class="device-detail" id="wc-session">—</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="device-card">
        <div class="device-icon">📷</div>
        <div class="device-info">
          <div class="device-name">Wyze Camera</div>
          <div class="device-detail">192.168.68.88 · MAC: 28:df:eb:d0:dc:ca</div>
          <div class="device-detail">Occupancy inference — future integration</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="device-card">
        <div class="device-icon">🌡️</div>
        <div class="device-info">
          <div class="device-name">Nest Thermostat</div>
          <div class="device-detail">192.168.68.65 · MAC: 18:b4:30:7a:f3:b5 (Nest Labs/Google)</div>
          <div class="device-detail">HVAC integration — future milestone</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="device-card">
        <div class="device-icon">🌐</div>
        <div class="device-info">
          <div class="device-name">TP-Link Deco Network</div>
          <div class="device-detail">Router: 192.168.68.1 · Nodes: .74, .83 · Subnet: 192.168.68.0/22</div>
          <div class="device-detail">Presence detection — future integration via Deco API</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="device-card">
        <div class="device-icon">📦</div>
        <div class="device-info">
          <div class="device-name">NAS</div>
          <div class="device-detail">192.168.68.54 · NAS.local</div>
          <div class="device-detail">Network attached storage</div>
        </div>
      </div>
    </div>

  </div>

  <div class="section-title" style="margin-top:16px">Setup Checklist</div>
  <div class="card">
    <div style="line-height:2.2;font-size:12px">
      <div>✅ Pentair IntelliCenter — live (TCP 6681 responding)</div>
      <div>✅ Enphase IQ Gateway — found (needs Enphase account JWT in ENPHASE_TOKEN)</div>
      <div>⚠️ SPAN Panel — found (needs one-time physical token registration)</div>
      <div>❌ Tesla Gateway — not on network (set TESLA_HOST when IP known)</div>
      <div>📋 SRP Utility — future (cloud polling, set SRP credentials)</div>
    </div>
  </div>
</div><!-- /devices -->


<!-- ═══ TESLA ENERGY ════════════════════════════════════════════════════════ -->
<div id="view-tesla-energy" class="view">

  <!-- Header row -->
  <div class="row">
    <div class="card" style="flex:2;min-width:300px">
      <div class="card-header">
        <span class="card-title" style="font-size:13px;font-weight:700">⚡ Tesla Energy Gateway V2</span>
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

  <!-- Setup card — shown when password not set or status != online -->
  <div id="tesla-setup-card" class="card" style="border-color:var(--warning);margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">⚙️ Setup Required</span>
      <span class="badge warning">unconfigured</span>
    </div>
    <div style="color:var(--text-dim);font-size:12px;margin-bottom:12px">
      Local password required — enter the password you set during Tesla app commissioning.<br>
      This is the local gateway password created in the Tesla app when setting up the Powerwall (not your Tesla account password).
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <input type="password" id="tesla-pw-input" placeholder="Gateway local password…"
        style="flex:1;min-width:200px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;
               padding:8px 12px;color:var(--text);font-family:inherit;font-size:13px;outline:none">
      <button class="btn primary" onclick="saveTeslaPassword()" style="white-space:nowrap">Save &amp; Connect</button>
    </div>
    <div id="tesla-pw-status" style="font-size:11px;margin-top:8px;color:var(--text-dim)"></div>
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
  <div class="section-title">Home Control</div>

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

<!-- ═══ SETTINGS ════════════════════════════════════════════════════════════ -->
<div id="view-settings" class="view">
  <div class="section-title">Integration Settings</div>

  <!-- Wyze Cameras -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">📷 Wyze Cameras</span>
      <span class="badge" id="wyze-cfg-badge">unconfigured</span>
    </div>
    <div style="color:var(--text-dim);font-size:11px;margin-bottom:12px">
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

  <!-- Ring Doorbell -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">🔔 Ring Doorbell</span>
      <span class="badge" id="ring-cfg-badge">unconfigured</span>
    </div>
    <div style="color:var(--text-dim);font-size:11px;margin-bottom:12px">
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

  <!-- Nest Thermostat -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">🌡️ Nest Thermostat</span>
      <span class="badge" id="nest-cfg-badge">unconfigured</span>
    </div>
    <div style="color:var(--text-dim);font-size:11px;margin-bottom:12px">
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

  <!-- B-Hyve Sprinkler -->
  <div class="card" style="margin-bottom:12px">
    <div class="card-header">
      <span class="card-title">💧 B-Hyve Sprinkler</span>
      <span class="badge" id="bhyve-cfg-badge">unconfigured</span>
    </div>
    <div style="color:var(--text-dim);font-size:11px;margin-bottom:12px">
      Orbit B-Hyve cloud account credentials. Used to authenticate with api.orbitbhyve.com.
      Device: 192.168.68.66 (cloud-only, no local API).
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

  <!-- Tesla (existing) -->
  <div class="card">
    <div class="card-header">
      <span class="card-title">⚡ Tesla Gateway</span>
      <span class="badge" id="settings-tesla-badge">—</span>
    </div>
    <div style="color:var(--text-dim);font-size:11px;margin-bottom:12px">
      Local gateway password — set during Tesla app commissioning. Not your Tesla account password.
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <input type="password" id="settings-tesla-pw" placeholder="Gateway local password…"
        style="flex:1;min-width:200px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;
               padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
      <button class="btn primary" onclick="saveTeslaPasswordFromSettings()">Save &amp; Connect</button>
      <span id="settings-tesla-status" style="font-size:11px;color:var(--text-dim)"></span>
    </div>
  </div>

</div><!-- /settings -->

</main>
<div id="toast"></div>

<script>
const views = ['cockpit','solar','span','pool','devices','tesla-energy','cybertruck','cameras','home-control','sprinklers','settings'];
function showView(v) {
  views.forEach(id => {
    document.getElementById('view-'+id).classList.toggle('active', id===v);
  });
  document.querySelectorAll('nav button').forEach((b,i) => b.classList.toggle('active', views[i]===v));
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
  const ts = s.ts ? new Date(s.ts*1000).toLocaleTimeString() : '—';
  document.getElementById('ts').textContent = ts;

  // Status dots
  const sd = s.span||{};  const ed = s.enphase||{}; const pd = s.pentair||{}; const td = s.tesla||{}; const wc = s.wall_connector||{};
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
  document.getElementById('battery-sub').textContent = td.status==='online' ? 'Tesla Gateway V2 · online' : 'Tesla Gateway · not configured';

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
      return `<div class="circuit-tile ${c.relay==='CLOSED'?c.color:'off'}" data-name="${c.name}" title="${c.id}" style="cursor:pointer;padding-bottom:${svg?'22px':'10px'}" onclick="if(chartsReady)selectCircuit(this.dataset.name)">
        <div class="ct-name">${c.name}</div>
        <div><span class="ct-power">${Math.abs(c.power_w)||0}</span><span class="ct-unit"> W</span></div>
        <div class="ct-relay">${c.relay||'?'} · ${c.priority||'?'}</div>
        ${svg}
      </div>`;
    }).join('');
  } else if (sd.status==='no_token') {
    circGrid.innerHTML = '';
  }
  updateSpanCharts(sd);

  // ── Pool View ──
  const bpb = document.getElementById('pool-body-badge');
  bpb.textContent = pool.status||'?';
  bpb.className = 'badge ' + (pool.status==='ON'?'online':'offline');
  document.getElementById('pc-pool-temp').textContent = pool.temp ? pool.temp+'°F' : '—°F';
  document.getElementById('pc-pool-setpoint').textContent = `Setpoint: ${pool.setpoint_lo||'?'} / ${pool.setpoint_hi||'?'} °F`;
  document.getElementById('pc-pool-heat').textContent = `Heat: ${pool.heat_source||'?'}`;

  const spa = pd.spa||{};
  const spab = document.getElementById('spa-body-badge');
  spab.textContent = spa.status||'?';
  spab.className = 'badge ' + (spa.status==='ON'?'online':'offline');
  document.getElementById('pc-spa-temp').textContent = spa.temp ? spa.temp+'°F' : '—°F';
  document.getElementById('pc-spa-setpoint').textContent = `Setpoint: ${spa.setpoint_lo||'?'} / ${spa.setpoint_hi||'?'} °F`;

  document.getElementById('pc-pump-rpm').textContent = pump.rpm != null ? pump.rpm+' RPM' : '— RPM';
  document.getElementById('pc-pump-gpm').textContent = pump.gpm != null ? `${pump.gpm} GPM · ${pump.power_w} W` : '— GPM';
  document.getElementById('pc-pump-status').textContent = `Status: ${pump.status||'?'}`;
  document.getElementById('pc-heater-status').textContent = (pd.heater||{}).status||'—';

  const poolCirc = document.getElementById('pool-circuits');
  poolCirc.innerHTML = (pd.circuits||[]).map(c => `
    <div class="circuit-row">
      <div class="circuit-status ${c.status}"></div>
      <div class="circuit-name-col">${c.name} <span class="circuit-id">(${c.id})</span></div>
      <div style="display:flex;gap:6px">
        <button class="btn" style="padding:3px 10px;font-size:10px" onclick="pentairSet('${c.id}',{STATUS:'ON'})">ON</button>
        <button class="btn" style="padding:3px 10px;font-size:10px" onclick="pentairSet('${c.id}',{STATUS:'OFF'})">OFF</button>
      </div>
    </div>
  `).join('');

  // ── Devices View ──
  const db1 = document.getElementById('dev-span-badge');
  db1.textContent = sd.status||'?'; db1.className = 'badge ' + statusColor(sd.status);
  document.getElementById('dev-span-door').textContent =
    `Door: ${sd.door||'?'} · Uptime: ${sd.uptime ? Math.round(sd.uptime/3600)+'h' : '?'}`;
  const db2 = document.getElementById('dev-enphase-badge');
  db2.textContent = ed.status||'?'; db2.className = 'badge ' + statusColor(ed.status);
  document.getElementById('dev-enphase-prod').textContent =
    `Production: ${fmt(ed.production_w)} · Consumption: ${fmt(ed.consumption_w)}`;

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

  // ── Settings badges ──
  const settingsTeslaBadge = document.getElementById('settings-tesla-badge');
  if (settingsTeslaBadge) { settingsTeslaBadge.textContent = td.status||'—'; settingsTeslaBadge.className = 'badge ' + statusColor(td.status); }
  const wyzeBadge = document.getElementById('wyze-cfg-badge');
  if (wyzeBadge) { const wyzeCfg = (s.cameras||[]).some(c=>c.type==='wyze'); wyzeBadge.textContent = wyzeCfg ? 'connected' : 'unconfigured'; wyzeBadge.className = 'badge ' + (wyzeCfg ? 'online' : 'offline'); }
  const ringBadge = document.getElementById('ring-cfg-badge');
  if (ringBadge) { const ringCfg = (s.cameras||[]).some(c=>c.type==='ring'); ringBadge.textContent = ringCfg ? 'connected' : 'unconfigured'; ringBadge.className = 'badge ' + (ringCfg ? 'online' : 'offline'); }
  // bhyve badge in settings is handled by renderBhyve() above
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

function refreshCameraImg(mac) {
  const img = document.getElementById('cam-img-' + mac);
  if (img) {
    img.src = '/api/camera/' + mac + '/snapshot?t=' + Date.now();
    // Also refresh modal if this camera is open
    const mImg = document.getElementById('cam-modal-img');
    if (mImg && mImg.dataset.mac === mac) {
      mImg.src = '/api/camera/' + mac + '/snapshot?t=' + Date.now();
    }
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

  // Load snapshot
  mImg.dataset.mac  = mac;
  mImg.style.display = 'none';
  mPh.style.display  = 'flex';
  mPh.innerHTML      = icon;

  const src = '/api/camera/' + mac + '/snapshot?t=' + Date.now();
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
    return `<div class="camera-card" onclick="openCameraModal('${mac}')">
      <img id="cam-img-${mac}" class="camera-thumb"
           src="/api/camera/${mac}/snapshot?t=${Date.now()}"
           onerror="this.style.display='none';document.getElementById('cam-ph-${mac}').style.display='flex'"
           onload="document.getElementById('cam-ph-${mac}').style.display='none';this.style.display='block'"
           alt="${cam.name}">
      <div id="cam-ph-${mac}" class="camera-thumb-placeholder" style="display:flex">${icon}<div style="font-size:10px;color:var(--text-dim)">No snapshot</div></div>
      <div class="camera-info">
        <div class="camera-name">
          <span>${liveDot}${cam.name}</span>
          ${statusBadge}
        </div>
        <div class="camera-meta">
          <span class="badge ${badgeClass}" style="margin-right:6px">${cam.type||'?'}</span>
          ${lastInfo}
        </div>
      </div>
    </div>`;
  }).join('');

  // Auto-refresh intervals for all cameras (Wyze now has thumbnails too)
  cameras.forEach(cam => {
    const mac = cam.mac || cam.type;
    if (!_camRefreshTimers[mac]) {
      _camRefreshTimers[mac] = setInterval(() => refreshCameraImg(mac), 30000);
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

// Flag for SPAN token (set by Python template)
const SPAN_TOKEN_CONFIGURED = {{ 'true' if config_span_token else 'false' }};

// SSE connection
const evtSrc = new EventSource('/api/stream');
evtSrc.onmessage = e => { try { renderState(JSON.parse(e.data)); } catch(err) { console.error(err); } };
evtSrc.onerror = () => console.warn('SSE disconnected — retrying...');

// Initial load
fetch('/api/state').then(r=>r.json()).then(renderState).catch(console.error);
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

    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False, threaded=True)
