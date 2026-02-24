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
    )
except ImportError:
    SPAN_HOST = "192.168.68.93"; SPAN_TOKEN = ""
    ENPHASE_HOST = "192.168.68.63"; ENPHASE_SERIAL = "202324023651"
    ENPHASE_TOKEN = ""; ENPHASE_EMAIL = ""; ENPHASE_PASSWORD = ""
    PENTAIR_HOST = "192.168.68.91"; PENTAIR_PORT = 6681
    TESLA_WC_HOST = "192.168.68.87"
    TESLA_HOST = ""; TESLA_EMAIL = ""; TESLA_PASSWORD = ""
    DASHBOARD_PORT = 8793; POLL_INTERVAL_SECONDS = 5

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
    from config import NEST_ACCESS_TOKEN
except ImportError:
    NEST_ACCESS_TOKEN = ""

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
}
_sse_subscribers = []
_sse_lock = threading.Lock()


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
        if SPAN_TOKEN:
            panel = _span_get("/api/v1/panel")
            grid_power = panel.get("instantGridPowerW", 0)
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
            _state["enphase"] = {
                "status": status,
                "production_w": round(prod_w, 0),
                "consumption_w": round(cons_w, 0),
                "net_w": round(prod_w - cons_w, 0),
                "firmware": "D8.3.5167",
                "serial": ENPHASE_SERIAL,
            }
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

        # charging_w = grid_v × currentA (single-phase: phase A is active leg)
        grid_v = v.get("grid_v", 0)
        current_a = v.get("currentA_a", 0)
        charging_w = round(grid_v * current_a, 0)

        # evse_state: 4=charging, 5=complete/ready, 9=not charging, 0=booting
        evse_state = v.get("evse_state", 0)
        state_map = {0: "booting", 1: "auth_required", 4: "charging", 5: "complete",
                     6: "fault", 7: "disconnected", 8: "wait_car", 9: "standby"}
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


# ── Tesla Gateway Adapter ─────────────────────────────────────────────────────

_tesla_token = None
_tesla_token_ts = 0


def _tesla_login():
    global _tesla_token, _tesla_token_ts
    if not TESLA_HOST or not TESLA_EMAIL:
        return None
    url = f"https://{TESLA_HOST}/api/login/Basic"
    data = json.dumps({
        "username": "customer",
        "email": TESLA_EMAIL,
        "password": TESLA_PASSWORD,
        "force_sm_off": False,
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5, context=_ssl_ctx) as r:
        resp = json.loads(r.read())
    token = resp.get("token", "")
    _tesla_token = token
    _tesla_token_ts = time.time()
    # CRITICAL: Re-enable Sitemaster after login
    _tesla_get("/api/sitemaster/run", token=token)
    return token


def _tesla_get(path, token=None):
    if not TESLA_HOST:
        raise RuntimeError("Tesla host not configured")
    token = token or _tesla_token
    url = f"https://{TESLA_HOST}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=5, context=_ssl_ctx) as r:
        return json.loads(r.read())


def poll_tesla():
    global _tesla_token
    if not TESLA_HOST:
        with _state_lock:
            _state["tesla"]["status"] = "unconfigured"
        return False
    try:
        if not _tesla_token or (time.time() - _tesla_token_ts) > 3600:
            _tesla_login()
        aggregates = _tesla_get("/api/meters/aggregates")
        soe_data = _tesla_get("/api/system_status/soe")
        grid_status = _tesla_get("/api/system_status/grid_status")

        solar_w = aggregates.get("solar", {}).get("instant_power", 0)
        battery_w = aggregates.get("battery", {}).get("instant_power", 0)
        grid_w = aggregates.get("site", {}).get("instant_power", 0)
        load_w = aggregates.get("load", {}).get("instant_power", 0)
        soe = soe_data.get("percentage", 0)
        grid_state = grid_status.get("grid_status", "?")

        with _state_lock:
            _state["tesla"] = {
                "status": "online",
                "soe": round(soe, 1),
                "solar_w": round(solar_w, 0),
                "battery_w": round(battery_w, 0),
                "grid_w": round(grid_w, 0),
                "load_w": round(load_w, 0),
                "grid_state": grid_state,
                "islanded": grid_state == "SystemIslandedActive",
            }
        return True
    except Exception as e:
        log.warning("Tesla poll error: %s", e)
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

        # Prefer Tesla for energy flows (most complete source)
        # Fallback: SPAN grid_power is the real import/export; Enphase has solar production
        if t.get("status") == "online":
            solar = t["solar_w"]
            load = t["load_w"]
            battery = t["battery_w"]
            grid = t["grid_w"]
        else:
            solar = e.get("production_w", 0)
            # SPAN grid_power: positive = importing, negative = exporting
            span_grid = s.get("grid_power", 0)
            grid = span_grid
            battery = 0
            # Home load = solar production + grid import (or - grid export)
            load = solar + span_grid

        pool_w = p.get("pump", {}).get("power_w", 0)

        _state["summary"] = {
            "solar_w": solar,
            "load_w": load,
            "battery_w": battery,
            "grid_w": grid,
            "pool_w": pool_w,
            "self_powered_pct": round(min(100, solar / max(load, 1) * 100), 1) if load > 0 else 0,
        }
        _state["ts"] = time.time()


# ── Wyze + Ring Camera Adapter ────────────────────────────────────────────────

def poll_cameras():
    cameras = []

    # Wyze
    if WYZE_API_KEY and WYZE_KEY_ID:
        try:
            from wyze_sdk import Client
            client = Client(api_key=WYZE_API_KEY, key_id=WYZE_KEY_ID)
            devices = client.cameras.list()
            for cam in devices:
                cameras.append({
                    "name": cam.nickname or cam.mac,
                    "mac": cam.mac,
                    "type": "wyze",
                    "status": "online" if cam.is_online else "offline",
                    "last_seen": str(cam.last_seen) if hasattr(cam, 'last_seen') else "",
                    "snapshot_path": f"/api/camera/{cam.mac}/snapshot",
                })
        except Exception as e:
            log.warning("Wyze poll error: %s", e)

    # Ring
    if RING_EMAIL and RING_PASSWORD:
        try:
            from ring_doorbell import Ring, Auth
            auth = Auth("JarvisHomeEnergy/1.0", None, lambda *args: None)
            auth.fetch_token(RING_EMAIL, RING_PASSWORD)
            ring = Ring(auth)
            ring.update_data()
            for device in ring.video_doorbell_devices():
                cameras.append({
                    "name": device.name or "Ring Doorbell",
                    "mac": getattr(device, 'id', 'ring'),
                    "type": "ring",
                    "status": "online" if device.is_subscribed else "offline",
                    "last_motion": str(device.last_motion) if hasattr(device, 'last_motion') else "",
                    "snapshot_path": f"/api/camera/ring_{getattr(device, 'id', '0')}/snapshot",
                })
        except Exception as e:
            log.warning("Ring poll error: %s", e)

    with _state_lock:
        _state["cameras"] = cameras
    return True


# ── Nest Thermostat Adapter ───────────────────────────────────────────────────

def poll_nest():
    if not NEST_ACCESS_TOKEN:
        with _state_lock:
            _state["nest"]["status"] = "unconfigured"
        return False
    try:
        import nest_thermostat
        napi = nest_thermostat.App(access_token=NEST_ACCESS_TOKEN)
        thermostats = napi.thermostats
        if not thermostats:
            raise RuntimeError("No thermostats found")
        t = list(thermostats.values())[0]
        with _state_lock:
            _state["nest"] = {
                "status": "online",
                "temp_f": t.temperature,
                "setpoint_f": t.target,
                "mode": t.mode,
                "hvac_state": t.hvac_state,
                "humidity": t.humidity,
                "name": t.name,
            }
        return True
    except Exception as e:
        log.warning("Nest poll error: %s", e)
        with _state_lock:
            _state["nest"]["status"] = "error"
        return False


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  POLLING LOOP                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def _poll_loop():
    import concurrent.futures
    log.info("Polling loop started (interval=%ds, parallel)", POLL_INTERVAL_SECONDS)
    while True:
        # Run all device polls concurrently — Pentair can take 45s, don't let it block solar/SPAN
        with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
            futs = [ex.submit(f) for f in (poll_pentair, poll_span, poll_enphase, poll_tesla, poll_wall_connector, poll_cameras, poll_nest)]
            concurrent.futures.wait(futs, timeout=60)
        _update_summary()
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
            from ring_doorbell import Ring, Auth
            auth = Auth("JarvisHomeEnergy/1.0", None, lambda *args: None)
            auth.fetch_token(RING_EMAIL, RING_PASSWORD)
            ring = Ring(auth)
            ring.update_data()
            device_id = cam_id[5:]
            for d in ring.video_doorbell_devices():
                if str(getattr(d, 'id', '')) == device_id:
                    url = d.get_snapshot()
                    r = _requests.get(url, timeout=5)
                    return Response(r.content, mimetype='image/jpeg')
        else:
            if not WYZE_API_KEY:
                return '', 204
            from wyze_sdk import Client
            client = Client(api_key=WYZE_API_KEY, key_id=WYZE_KEY_ID)
            img = client.cameras.get_thumbnail(device_mac=cam_id)
            if img:
                r = _requests.get(img, timeout=5)
                return Response(r.content, mimetype='image/jpeg')
    except Exception as e:
        log.warning("Snapshot error for %s: %s", cam_id, e)
    return '', 204


@app.route("/api/nest/setpoint", methods=["POST"])
def nest_setpoint():
    global NEST_ACCESS_TOKEN
    if not NEST_ACCESS_TOKEN:
        return jsonify({"ok": False, "error": "not configured"})
    try:
        data = request.get_json()
        temp = float(data.get('temp', 70))
        import nest_thermostat
        napi = nest_thermostat.App(access_token=NEST_ACCESS_TOKEN)
        t = list(napi.thermostats.values())[0]
        t.target = temp
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

  /* Flow diagram */
  .flow-diagram { background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 20px; margin: 12px 0; }
  .flow-row { display: flex; align-items: center; justify-content: center; gap: 16px; flex-wrap: wrap; }
  .flow-node { text-align: center; min-width: 80px; }
  .flow-icon { font-size: 28px; margin-bottom: 4px; }
  .flow-label { font-size: 10px; color: var(--text-dim); text-transform: uppercase; }
  .flow-power { font-size: 14px; font-weight: 700; }
  .flow-arrow { font-size: 20px; color: var(--border); }
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
  .camera-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .camera-thumb { width: 100%; aspect-ratio: 16/9; object-fit: cover; background: var(--surface2); display: block; }
  .camera-thumb-placeholder { width: 100%; aspect-ratio: 16/9; background: var(--surface2); display: flex; align-items: center; justify-content: center; color: var(--text-dim); font-size: 32px; }
  .camera-info { padding: 10px 12px; }
  .camera-name { font-weight: 700; font-size: 13px; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .camera-meta { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
  .badge-wyze { background: rgba(0,212,255,.15); color: #00d4ff; }
  .badge-ring { background: rgba(16,185,129,.15); color: var(--battery); }

  /* ── Nest tile ── */
  .nest-cockpit-tile { background: var(--surface2); border-radius: 8px; padding: 10px 14px; display: flex; gap: 12px; align-items: center; }
  .nest-cockpit-temp { font-size: 24px; font-weight: 700; color: var(--pool); }
  .nest-cockpit-label { font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing:.05em; }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head>
<body>

<header>
  <div class="logo">⚡ JARVIS <span>Home Energy OS</span></div>
  <nav>
    <button class="active" onclick="showView('cockpit')">Energy Cockpit</button>
    <button onclick="showView('span')">SPAN Circuits</button>
    <button onclick="showView('pool')">Pool Control</button>
    <button onclick="showView('devices')">Devices</button>
    <button onclick="showView('tesla-energy')">Tesla Energy</button>
    <button onclick="showView('cybertruck')">Cybertruck</button>
    <button onclick="showView('cameras')">Cameras</button>
    <button onclick="showView('home-control')">Home Control</button>
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

  <!-- Flow Diagram -->
  <div class="flow-diagram">
    <div class="flow-row">
      <div class="flow-node">
        <div class="flow-icon">☀️</div>
        <div class="flow-label">Solar</div>
        <div class="flow-power c-solar" id="f-solar">— W</div>
      </div>
      <div class="flow-arrow">→</div>
      <div class="flow-node" style="min-width:100px">
        <div class="flow-icon">🏠</div>
        <div class="flow-label">Home</div>
        <div class="flow-power c-load" id="f-load">— W</div>
      </div>
      <div class="flow-arrow">←</div>
      <div class="flow-node">
        <div class="flow-icon">🔋</div>
        <div class="flow-label">Battery</div>
        <div class="flow-power c-battery" id="f-battery">— W</div>
        <div class="flow-power" style="font-size:11px;color:var(--text-dim)" id="f-soe">—%</div>
      </div>
      <div class="flow-arrow">↔</div>
      <div class="flow-node">
        <div class="flow-icon">🔌</div>
        <div class="flow-label">Grid</div>
        <div class="flow-power c-grid" id="f-grid">— W</div>
        <div class="flow-power" style="font-size:11px;color:var(--text-dim)" id="f-grid-dir">—</div>
      </div>
    </div>
  </div>

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

  <div class="row">
    <div class="card" style="flex:2;min-width:300px">
      <div class="card-header">
        <span class="card-title" style="font-size:13px;font-weight:700">⚡ Tesla Energy Gateway V2</span>
        <span class="badge" id="tesla-energy-badge">—</span>
      </div>
      <div class="device-detail">192.168.68.86 · MAC: dc:f3:1c:25:1e:cc</div>
      <div class="device-detail">Serial: GF2240460002D2 · Firmware: 25.26.0</div>
      <div class="device-detail">Backup: Whole Home · Utility: SRP</div>
    </div>
    <div class="card" style="flex:1;min-width:200px">
      <div class="card-header"><span class="card-title">Gateway Info</span></div>
      <div class="device-detail">IP: 192.168.68.86</div>
      <div class="device-detail">Serial: GF2240460002D2</div>
      <div class="device-detail">Firmware: 25.26.0</div>
      <div class="device-detail">Backup: Whole Home</div>
      <div class="device-detail">Utility: SRP</div>
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

  <!-- Energy flow tiles — shown only when online -->
  <div id="tesla-energy-tiles" style="display:none">
    <div class="section-title">Live Energy Flow</div>
    <div class="grid grid-4" style="margin-bottom:12px">
      <div class="card energy-solar">
        <div class="card-header"><span class="card-title">Solar</span></div>
        <div class="big-val c-solar" id="te-solar">—</div><span class="big-unit">W</span>
      </div>
      <div class="card energy-battery">
        <div class="card-header">
          <span class="card-title">Battery SOC</span>
          <span id="te-bat-dir" style="font-size:18px;color:var(--battery)">—</span>
        </div>
        <div class="big-val c-battery" id="te-soe">—</div><span class="big-unit">%</span>
        <div class="sub-val" id="te-bat-w">— W</div>
      </div>
      <div class="card energy-grid">
        <div class="card-header">
          <span class="card-title">Grid</span>
          <span class="badge" id="te-grid-badge">—</span>
        </div>
        <div class="big-val c-grid" id="te-grid">—</div><span class="big-unit">W</span>
        <div class="sub-val" id="te-grid-dir">—</div>
      </div>
      <div class="card energy-load">
        <div class="card-header"><span class="card-title">Home Load</span></div>
        <div class="big-val c-load" id="te-load">—</div><span class="big-unit">W</span>
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
  <div id="camera-grid" class="grid grid-3" style="margin-bottom:16px"></div>
</div><!-- /cameras -->


<!-- ═══ HOME CONTROL ════════════════════════════════════════════════════════ -->
<div id="view-home-control" class="view">
  <div class="section-title">Home Control</div>

  <!-- Nest Thermostat -->
  <div class="row">
    <div class="card" id="nest-card" style="min-width:320px;max-width:480px">
      <div class="card-header">
        <span class="card-title">🌡️ Nest Thermostat</span>
        <span class="badge" id="nest-badge">unconfigured</span>
      </div>

      <!-- Unconfigured state -->
      <div id="nest-setup-msg" style="color:var(--text-dim);font-size:12px">
        Add your Nest access token in the <strong>Settings</strong> tab to connect.
        <br><br>
        <button class="btn primary" onclick="showView('settings')">Go to Settings →</button>
      </div>

      <!-- Configured state -->
      <div id="nest-data" style="display:none">
        <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:flex-end;margin-bottom:16px">
          <div>
            <div class="sub-val">Current Temp</div>
            <div class="big-val c-pool" id="nest-temp">—</div><span class="big-unit">°F</span>
          </div>
          <div>
            <div class="sub-val">Setpoint</div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:4px">
              <button class="btn" id="nest-down" onclick="nestAdjust(-1)" style="font-size:16px;padding:4px 12px">−</button>
              <span class="big-val" id="nest-setpoint" style="font-size:26px">—</span>
              <span class="big-unit">°F</span>
              <button class="btn" id="nest-up" onclick="nestAdjust(1)" style="font-size:16px;padding:4px 12px">+</button>
            </div>
          </div>
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <div>
            <div class="sub-val">Mode</div>
            <span class="badge" id="nest-mode">—</span>
          </div>
          <div>
            <div class="sub-val">HVAC State</div>
            <span class="badge" id="nest-hvac">—</span>
          </div>
          <div>
            <div class="sub-val">Humidity</div>
            <span style="font-size:13px;font-weight:600" id="nest-humidity">—</span>
          </div>
          <div>
            <div class="sub-val">Name</div>
            <span style="font-size:12px;color:var(--text-dim)" id="nest-name">—</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</div><!-- /home-control -->


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
        <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Email (optional)</div>
        <input type="email" id="wyze-email" placeholder="you@example.com"
          style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;color:var(--text);font-family:inherit;font-size:12px;outline:none">
      </div>
      <div>
        <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Password (optional)</div>
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
const views = ['cockpit','span','pool','devices','tesla-energy','cybertruck','cameras','home-control','settings'];
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

  const teslaOnline = td.status === 'online';
  if (teSetup) teSetup.style.display = teslaOnline ? 'none' : 'block';
  if (teTiles) teTiles.style.display = teslaOnline ? 'block' : 'none';

  if (teslaOnline) {
    const batW  = td.battery_w || 0;
    const gridW2 = td.grid_w || 0;
    if (document.getElementById('te-solar')) {
      document.getElementById('te-solar').textContent = Math.round(td.solar_w || 0);
      document.getElementById('te-soe').textContent   = Math.round(td.soe || 0);
      document.getElementById('te-bat-w').textContent  = fmt(Math.abs(batW));
      document.getElementById('te-bat-dir').textContent = batW > 50 ? '↓ discharging' : (batW < -50 ? '↑ charging' : '○ idle');
      document.getElementById('te-grid').textContent  = Math.round(Math.abs(gridW2));
      document.getElementById('te-grid-dir').textContent = gridW2 > 50 ? 'Importing' : (gridW2 < -50 ? 'Exporting' : 'Balanced');
      const tgb = document.getElementById('te-grid-badge');
      tgb.textContent  = td.islanded ? 'islanded' : 'grid-tie';
      tgb.className    = 'badge ' + (td.islanded ? 'warning' : 'online');
      document.getElementById('te-load').textContent  = Math.round(td.load_w || 0);
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
      Grid state: <strong>${td.grid_state || '—'}</strong>
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

  // ── Cameras ──
  renderCameras(s.cameras || []);

  // ── Nest ──
  renderNest(s.nest || {});

  // ── Settings badges ──
  const settingsTeslaBadge = document.getElementById('settings-tesla-badge');
  if (settingsTeslaBadge) { settingsTeslaBadge.textContent = td.status||'—'; settingsTeslaBadge.className = 'badge ' + statusColor(td.status); }
  const wyzeBadge = document.getElementById('wyze-cfg-badge');
  if (wyzeBadge) { const wyzeCfg = (s.cameras||[]).some(c=>c.type==='wyze'); wyzeBadge.textContent = wyzeCfg ? 'connected' : 'unconfigured'; wyzeBadge.className = 'badge ' + (wyzeCfg ? 'online' : 'offline'); }
  const ringBadge = document.getElementById('ring-cfg-badge');
  if (ringBadge) { const ringCfg = (s.cameras||[]).some(c=>c.type==='ring'); ringBadge.textContent = ringCfg ? 'connected' : 'unconfigured'; ringBadge.className = 'badge ' + (ringCfg ? 'online' : 'offline'); }
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

function refreshCameraImg(mac) {
  const img = document.getElementById('cam-img-' + mac);
  if (img) img.src = '/api/camera/' + mac + '/snapshot?t=' + Date.now();
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

  // Build HTML for each camera
  grid.innerHTML = cameras.map(cam => {
    const mac = cam.mac || cam.type;
    const badgeClass = cam.type === 'wyze' ? 'badge-wyze' : 'badge-ring';
    const icon = cam.type === 'wyze' ? '📷' : '🔔';
    const lastInfo = cam.last_motion
      ? `Last motion: ${cam.last_motion}`
      : (cam.last_seen ? `Last seen: ${cam.last_seen}` : '');
    return `<div class="camera-card">
      <img id="cam-img-${mac}" class="camera-thumb"
           src="/api/camera/${mac}/snapshot?t=${Date.now()}"
           onerror="this.style.display='none';document.getElementById('cam-ph-${mac}').style.display='flex'"
           onload="document.getElementById('cam-ph-${mac}').style.display='none';this.style.display='block'"
           alt="${cam.name}">
      <div id="cam-ph-${mac}" class="camera-thumb-placeholder">${icon}</div>
      <div class="camera-info">
        <div class="camera-name">
          <span>${cam.name}</span>
          <span class="badge ${cam.status==='online'?'online':'offline'}">${cam.status||'?'}</span>
        </div>
        <div class="camera-meta">
          <span class="badge ${badgeClass}" style="margin-right:6px">${cam.type||'?'}</span>
          ${lastInfo}
        </div>
      </div>
    </div>`;
  }).join('');

  // Set up auto-refresh intervals per camera
  cameras.forEach(cam => {
    const mac = cam.mac || cam.type;
    if (!_camRefreshTimers[mac]) {
      _camRefreshTimers[mac] = setInterval(() => refreshCameraImg(mac), 30000);
    }
  });
}

// ══ Nest helpers ══════════════════════════════════════════════════════════════
let _nestSetpoint = 70;

function nestAdjust(delta) {
  _nestSetpoint += delta;
  document.getElementById('nest-setpoint').textContent = _nestSetpoint;
  fetch('/api/nest/setpoint', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({temp: _nestSetpoint})
  }).then(r=>r.json()).then(d => {
    if (d.ok) toast('✓ Setpoint → ' + _nestSetpoint + '°F');
    else toast('✗ ' + (d.error||'Error'), 5000);
  }).catch(e => toast('✗ ' + e, 5000));
}

function renderNest(nest) {
  const badge    = document.getElementById('nest-badge');
  const cockpitBadge = document.getElementById('nest-cockpit-badge');
  const setupMsg = document.getElementById('nest-setup-msg');
  const dataDiv  = document.getElementById('nest-data');
  const cfgBadge = document.getElementById('nest-cfg-badge');
  const cockpitContent = document.getElementById('nest-cockpit-content');

  if (!nest) return;
  const status = nest.status || 'unconfigured';

  if (badge) { badge.textContent = status; badge.className = 'badge ' + statusColor(status); }
  if (cockpitBadge) { cockpitBadge.textContent = status; cockpitBadge.className = 'badge ' + statusColor(status); }
  if (cfgBadge) { cfgBadge.textContent = status; cfgBadge.className = 'badge ' + statusColor(status); }

  const isOnline = status === 'online';
  if (setupMsg) setupMsg.style.display = isOnline ? 'none' : 'block';
  if (dataDiv)  dataDiv.style.display  = isOnline ? 'block' : 'none';

  if (isOnline) {
    const temp     = nest.temp_f    || 0;
    const setpoint = nest.setpoint_f || 0;
    _nestSetpoint  = setpoint;

    const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setEl('nest-temp',     Math.round(temp));
    setEl('nest-setpoint', Math.round(setpoint));
    setEl('nest-humidity', (nest.humidity || 0) + '%');
    setEl('nest-name',     nest.name || '—');

    const modeBadge = document.getElementById('nest-mode');
    const hvacBadge = document.getElementById('nest-hvac');
    const modeMap = { heat: 'online', cool: 'partial', off: 'offline', auto: 'warning' };
    const hvacMap = { heating: 'online', cooling: 'partial', idle: 'offline' };
    if (modeBadge) { modeBadge.textContent = nest.mode || 'off'; modeBadge.className = 'badge ' + (modeMap[nest.mode] || 'offline'); }
    if (hvacBadge) { hvacBadge.textContent = nest.hvac_state || 'idle'; hvacBadge.className = 'badge ' + (hvacMap[nest.hvac_state] || 'offline'); }

    // Cockpit tile
    if (cockpitContent) {
      cockpitContent.innerHTML = `
        <div style="display:flex;gap:16px;align-items:center">
          <div><div class="sub-val">Current</div><div class="nest-cockpit-temp">${Math.round(temp)}°</div></div>
          <div><div class="sub-val">Set</div><div style="font-size:18px;font-weight:600">${Math.round(setpoint)}°</div></div>
          <div>
            <div class="sub-val">Mode</div>
            <span class="badge ${modeMap[nest.mode]||'offline'}">${nest.mode||'off'}</span>
          </div>
        </div>
      `;
    }
  } else if (cockpitContent) {
    cockpitContent.innerHTML = `<div style="color:var(--text-dim);font-size:11px">${status} — click to configure</div>`;
  }
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
