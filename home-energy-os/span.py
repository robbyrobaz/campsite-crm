"""SPAN Panel API client."""

import os
import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

SPAN_IP = os.getenv("SPAN_IP", "192.168.68.93")
SPAN_TOKEN = os.getenv("SPAN_TOKEN", "")

HEADERS = {"Authorization": f"Bearer {SPAN_TOKEN}"}
BASE = f"http://{SPAN_IP}/api/v1"
TIMEOUT = 5.0


async def get_panel() -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{BASE}/panel", headers=HEADERS)
        r.raise_for_status()
        return r.json()


async def get_circuits() -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{BASE}/circuits", headers=HEADERS)
        r.raise_for_status()
        return r.json()
