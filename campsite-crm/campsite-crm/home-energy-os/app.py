"""
Jarvis Home Energy OS — Phase 1 Dashboard
Port: 8892
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import span
import enphase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(push_loop())
    log.info("Jarvis Home Energy OS started on port 8892")
    yield


app = FastAPI(title="Jarvis Home Energy OS", lifespan=lifespan)

# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

# In-memory state cache
_state: dict = {}
_state_ts: float = 0.0
CACHE_TTL = 2.0  # seconds

# Active WebSocket connections
_connections: set[WebSocket] = set()


async def fetch_state() -> dict:
    """Fetch all device data and return unified state dict."""
    now = time.time()
    global _state, _state_ts
    if now - _state_ts < CACHE_TTL and _state:
        return _state

    state: dict = {
        "ts": int(now),
        "grid": {},
        "solar": {},
        "circuits": [],
        "panel": {},
        "errors": [],
    }

    # --- SPAN Panel ---
    try:
        panel_data = await span.get_panel()
        grid_w = panel_data.get("instantGridPowerW", 0)
        state["grid"] = {
            "watts": round(grid_w, 1),
            "direction": "import" if grid_w > 0 else "export",
        }
        state["panel"] = {
            "relay": panel_data.get("mainRelayState", "UNKNOWN"),
            "dsm_grid": panel_data.get("dsmGridState", "UNKNOWN"),
            "dsm_state": panel_data.get("dsmState", "UNKNOWN"),
            "run_config": panel_data.get("currentRunConfig", "UNKNOWN"),
        }
    except Exception as e:
        log.warning(f"SPAN panel error: {e}")
        state["errors"].append(f"SPAN panel: {e}")

    # --- SPAN Circuits ---
    try:
        circuits_data = await span.get_circuits()
        raw = circuits_data.get("circuits", {})
        circuits = []
        for cid, c in raw.items():
            # SPAN reports negative watts for consuming circuits (power flows panel→circuit)
            w = abs(c.get("instantPowerW", 0))
            circuits.append({
                "id": cid,
                "name": c.get("name", "Unknown"),
                "watts": round(w, 1),
                "relay": c.get("relayState", "UNKNOWN"),
                "priority": c.get("priority", "NON_ESSENTIAL"),
                "tabs": c.get("tabs", []),
                "controllable": c.get("isUserControllable", False),
            })
        # Sort by watts descending
        circuits.sort(key=lambda x: -x["watts"])
        state["circuits"] = circuits
    except Exception as e:
        log.warning(f"SPAN circuits error: {e}")
        state["errors"].append(f"SPAN circuits: {e}")

    # --- Enphase Solar ---
    try:
        prod = await enphase.get_production()
        state["solar"] = {
            "watts_now": prod.get("wattsNow", 0),
            "wh_today": prod.get("wattHoursToday", 0),
            "wh_lifetime": prod.get("wattHoursLifetime", 0),
            "available": True,
        }
    except Exception as e:
        log.warning(f"Enphase error: {e}")
        state["solar"] = {"watts_now": 0, "wh_today": 0, "available": False}
        state["errors"].append(f"Enphase: {e}")

    _state = state
    _state_ts = now
    return state


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    index = STATIC_DIR / "index.html"
    return HTMLResponse(index.read_text())


@app.get("/api/state")
async def api_state():
    state = await fetch_state()
    return JSONResponse(state)


@app.get("/api/health")
async def health():
    return {"status": "ok", "ts": int(time.time())}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _connections.add(ws)
    log.info(f"WS connected ({len(_connections)} total)")
    try:
        # Send initial state immediately
        state = await fetch_state()
        await ws.send_text(json.dumps(state))
        # Keep alive — state is pushed by the background task
        while True:
            await ws.receive_text()  # client heartbeats
    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(ws)
        log.info(f"WS disconnected ({len(_connections)} total)")


async def push_loop():
    """Background task: fetch state every 2s and push to all WS clients."""
    while True:
        await asyncio.sleep(2)
        if not _connections:
            continue
        try:
            global _state_ts
            _state_ts = 0  # force refresh
            state = await fetch_state()
            msg = json.dumps(state)
            dead = set()
            for ws in list(_connections):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.add(ws)
            _connections.difference_update(dead)
        except Exception as e:
            log.warning(f"Push loop error: {e}")



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8892, reload=False)
